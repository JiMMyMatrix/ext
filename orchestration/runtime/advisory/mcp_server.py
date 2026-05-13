import asyncio
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Deque, Dict, Set, Tuple

from anthropic import AsyncAnthropic
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Policy knobs for the current governor/executor + advisor architecture
# ---------------------------------------------------------------------------

HEADLESS_WINDOW_SECONDS = 3600
HEADLESS_MAX_CALLS_PER_WINDOW = 15
AGGREGATE_WINDOW_SECONDS = 3600
AGGREGATE_MAX_CALLS = 40
ARCHITECT_ESCALATION_THRESHOLD = 3
ARCHITECT_RESET_TIMEOUT_SECONDS = 300
ADVISORY_BACKEND_TIMEOUT_SECONDS = 500
MAX_DISTINCT_TOOLS_PER_CYCLE = 3
_VALID_CYCLE_ID = re.compile(
    r"^(governor/[\w.-]+|[\w.-]+/[\w.-]+/[\w.-]+/[\w.-]+/[\w.-]+)$"
)
REPO_ROOT = Path(os.environ.get("ORCHESTRATION_REPO_ROOT") or os.getcwd()).resolve()
SOURCE_ROOT = Path(os.environ.get("ORCHESTRATION_SOURCE_ROOT") or REPO_ROOT).resolve()
CORGI_RUNTIME_CONTEXT = "corgi-governor-runtime"
CORGI_DEVELOPMENT_CONTEXT = "corgi-development-consulting"
ADVISORY_CONTEXT = os.environ.get("CORGI_ADVISORY_CONTEXT") or CORGI_RUNTIME_CONTEXT
ADVISORY_CALLER_ROLE = os.environ.get("CORGI_ADVISORY_CALLER_ROLE") or ""
STATE_DIR = Path(
    os.environ.get("CORGI_ADVISORY_STATE_DIR")
    or REPO_ROOT / ".agent" / "orchestration" / "advisory"
).resolve()
STATE_DUMP_PATH = str(STATE_DIR / "mcp_state.json")
MINIMAX_DEFAULT_API_KEY_FILE = Path(
    os.environ.get("MINIMAX_API_KEY_FILE") or STATE_DIR / "minimax_api_key"
)
MINIMAX_DEFAULT_OPENAI_BASE_URL = "https://api.minimax.io/v1"
MINIMAX_DEFAULT_MODEL = "MiniMax-M2.7"
CLAUDE_HEADLESS_MODEL = os.environ.get("CLAUDE_HEADLESS_MODEL") or "claude-opus-4-7"
# Previous Claude headless baseline retained for traceability: claude-sonnet-4-6.
CLAUDE_HEADLESS_PREVIOUS_MODEL_ANNOTATION = "claude-sonnet-4-6"
mcp = FastMCP(
    "Corgi_Governor_Advisor"
    if ADVISORY_CONTEXT == CORGI_RUNTIME_CONTEXT
    else "Corgi_Development_Consulting"
)

# ---------------------------------------------------------------------------
# Runtime state trackers
# ---------------------------------------------------------------------------

policy_lock = asyncio.Lock()
headless_call_timestamps: Deque[float] = deque()
aggregate_timestamps: Deque[float] = deque()
architect_tracker: Dict[Tuple[str, str], Dict[str, float | int]] = {}
review_tracker: set[Tuple[str, str]] = set()
cycle_tool_tracker: Dict[str, Set[str]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_runtime_context() -> bool:
    return ADVISORY_CONTEXT == CORGI_RUNTIME_CONTEXT


def _is_development_context() -> bool:
    return ADVISORY_CONTEXT == CORGI_DEVELOPMENT_CONTEXT


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _resolve_context_path(raw_path: str, *, must_exist: bool = True) -> Path | str:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    resolved = candidate.resolve()
    if _is_runtime_context() and not _path_is_within(resolved, REPO_ROOT):
        return (
            "POLICY_ERROR:"
            " Corgi runtime advisor file access is constrained to the target "
            f"workspace ({REPO_ROOT}). Requested: {resolved}"
        )
    if must_exist and not resolved.exists():
        return f"Error: File not found at {raw_path}."
    return resolved


def _resolve_context_work_dir(work_dir: str | None) -> Path | str:
    if not work_dir:
        return REPO_ROOT
    resolved = _resolve_context_path(work_dir)
    if isinstance(resolved, str):
        return resolved
    if not resolved.is_dir():
        return f"Error: The provided work_dir '{work_dir}' does not exist on the filesystem."
    return resolved


def _runtime_prompt_boundary_error(prompt: str) -> str | None:
    if not _is_runtime_context():
        return None
    absolute_candidates = re.findall(r"(?<![\w:])/[^\s`'\"<>|;&]+", prompt)
    relative_escape_candidates = re.findall(r"(?<!\S)[^\s`'\"<>|;&]*\.\./[^\s`'\"<>|;&]*", prompt)
    for raw_candidate in [*absolute_candidates, *relative_escape_candidates]:
        if raw_candidate.startswith("//"):
            continue
        candidate = Path(raw_candidate).expanduser()
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        resolved = candidate.resolve()
        if not _path_is_within(resolved, REPO_ROOT):
            return (
                "POLICY_ERROR:"
                " Corgi runtime advisor prompts may not request filesystem access "
                f"outside the target workspace ({REPO_ROOT}). Requested: {resolved}"
            )
    return None


async def _authorize_tool_call(tool_name: str) -> str | None:
    if _is_runtime_context():
        if ADVISORY_CALLER_ROLE != "governor":
            return (
                "POLICY_ERROR:"
                f" {tool_name} is available only to the Corgi Governor in runtime "
                f"context. caller_role={ADVISORY_CALLER_ROLE or 'unset'}"
            )
        return None
    if _is_development_context():
        if ADVISORY_CALLER_ROLE not in {"developer", "governor"}:
            return (
                "POLICY_ERROR:"
                f" {tool_name} is available only to explicit development consulting "
                f"callers in development context. caller_role={ADVISORY_CALLER_ROLE or 'unset'}"
            )
        return None
    return (
        "POLICY_ERROR:"
        f" unknown advisory context {ADVISORY_CONTEXT!r}; expected "
        f"{CORGI_RUNTIME_CONTEXT!r} or {CORGI_DEVELOPMENT_CONTEXT!r}."
    )


def get_api_key(env_var: str, fallback_path: str | None = None) -> str | None:
    key = os.environ.get(env_var)
    if key:
        return key

    if fallback_path:
        try:
            with open(fallback_path, "r", encoding="utf-8") as handle:
                return handle.read().strip()
        except Exception:
            pass

    return None



def read_file_content(file_path: str) -> str:
    try:
        resolved = _resolve_context_path(file_path)
        if isinstance(resolved, str):
            return resolved
        with open(resolved, "r", encoding="utf-8") as handle:
            return handle.read()
    except Exception as exc:
        return f"Error reading file: {exc}"



def _normalize_error_signature(error_log: str) -> str:
    for raw_line in error_log.splitlines():
        line = raw_line.strip()
        if line:
            return line[:200]
    return "no_error_signature"


def _validate_sections(response: str, required: list[str]) -> str:
    missing = [section for section in required if section not in response]
    if not missing:
        return response
    return (
        "FORMAT_WARNING: response missing sections: "
        f"{missing}. Treat this response as unstructured fallback.\n\n"
        f"{response}"
    )


async def _dump_state() -> None:
    async with policy_lock:
        payload = {
            "headless_call_timestamps": list(headless_call_timestamps),
            "aggregate_timestamps": list(aggregate_timestamps),
            "architect_tracker": {
                f"{key0}||{key1}": value
                for (key0, key1), value in architect_tracker.items()
            },
            "review_tracker": sorted(f"{key0}||{key1}" for key0, key1 in review_tracker),
            "cycle_tool_tracker": {
                cycle_id: sorted(tool_names)
                for cycle_id, tool_names in cycle_tool_tracker.items()
            },
        }

    os.makedirs(os.path.dirname(STATE_DUMP_PATH), exist_ok=True)
    with open(STATE_DUMP_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


async def _load_state() -> None:
    try:
        with open(STATE_DUMP_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return
    except json.JSONDecodeError:
        return

    async with policy_lock:
        headless_call_timestamps.clear()
        headless_call_timestamps.extend(
            float(item) for item in payload.get("headless_call_timestamps", [])
        )

        aggregate_timestamps.clear()
        aggregate_timestamps.extend(
            float(item) for item in payload.get("aggregate_timestamps", [])
        )

        architect_tracker.clear()
        for raw_key, value in payload.get("architect_tracker", {}).items():
            if "||" not in raw_key:
                continue
            key0, key1 = raw_key.split("||", 1)
            if isinstance(value, dict):
                architect_tracker[(key0, key1)] = dict(value)

        review_tracker.clear()
        for raw_key in payload.get("review_tracker", []):
            if "||" not in raw_key:
                continue
            key0, key1 = raw_key.split("||", 1)
            review_tracker.add((key0, key1))

        cycle_tool_tracker.clear()
        for cycle_id, tool_names in payload.get("cycle_tool_tracker", {}).items():
            cycle_tool_tracker[str(cycle_id)] = {str(item) for item in tool_names}


async def _persist_and_return(response: str) -> str:
    await _dump_state()
    return response


async def _register_cycle_call(cycle_id: str | None, tool_name: str) -> str | None:
    if not cycle_id:
        return None
    if not _VALID_CYCLE_ID.match(cycle_id):
        return (
            "POLICY_ERROR:"
            f" malformed cycle_id={cycle_id!r}. Expected active dispatch_ref or governor/<timestamp>."
        )

    async with policy_lock:
        used = cycle_tool_tracker.setdefault(cycle_id, set())
        used.add(tool_name)
        if len(used) > MAX_DISTINCT_TOOLS_PER_CYCLE:
            return (
                "POLICY_ERROR:"
                f"cycle_id={cycle_id} exceeded distinct advisor-tool limit "
                f"({MAX_DISTINCT_TOOLS_PER_CYCLE}). Used={sorted(used)}"
            )

    return None


async def _consume_headless_quota() -> str | None:
    now = time.time()
    async with policy_lock:
        while (
            headless_call_timestamps
            and now - headless_call_timestamps[0] > HEADLESS_WINDOW_SECONDS
        ):
            headless_call_timestamps.popleft()

        if len(headless_call_timestamps) >= HEADLESS_MAX_CALLS_PER_WINDOW:
            return (
                "POLICY_ERROR:"
                f"headless quota exceeded: {HEADLESS_MAX_CALLS_PER_WINDOW} "
                "calls per rolling hour."
            )

        headless_call_timestamps.append(now)

    return None


async def _consume_aggregate_quota() -> str | None:
    now = time.time()
    async with policy_lock:
        while aggregate_timestamps and now - aggregate_timestamps[0] > AGGREGATE_WINDOW_SECONDS:
            aggregate_timestamps.popleft()

        if len(aggregate_timestamps) >= AGGREGATE_MAX_CALLS:
            return (
                "POLICY_ERROR:"
                f" aggregate advisor quota exceeded: {AGGREGATE_MAX_CALLS} "
                "calls per rolling hour."
            )

        aggregate_timestamps.append(now)

    return None


async def _record_review_once(file_path: str, cycle_id: str | None) -> str | None:
    if not cycle_id:
        return "POLICY_ERROR: routine_code_review requires cycle_id."

    key = (os.path.abspath(file_path), cycle_id)
    async with policy_lock:
        if key in review_tracker:
            return (
                "POLICY_ERROR:"
                f"file={file_path} already reviewed in cycle_id={cycle_id}."
            )
        review_tracker.add(key)

    return None


async def _bump_architect_counter(file_path: str, error_log: str) -> int:
    now = time.time()
    bug_key = (os.path.abspath(file_path), _normalize_error_signature(error_log))

    async with policy_lock:
        entry = architect_tracker.get(bug_key)
        if entry and now - float(entry["ts"]) > ARCHITECT_RESET_TIMEOUT_SECONDS:
            entry["count"] = 0

        if not entry:
            architect_tracker[bug_key] = {"count": 0, "ts": now}

        architect_tracker[bug_key]["count"] = (
            int(architect_tracker[bug_key]["count"]) + 1
        )
        architect_tracker[bug_key]["ts"] = now
        return int(architect_tracker[bug_key]["count"])


async def _reset_architect_counter(file_path: str, error_log: str) -> None:
    bug_key = (os.path.abspath(file_path), _normalize_error_signature(error_log))
    async with policy_lock:
        architect_tracker.pop(bug_key, None)


# ---------------------------------------------------------------------------
# Tool backends
# ---------------------------------------------------------------------------


def _run_claude_code_sync(prompt: str, work_dir: str | None = None) -> str:
    resolved_work_dir = _resolve_context_work_dir(work_dir)
    if isinstance(resolved_work_dir, str):
        return resolved_work_dir

    cmd = [
        "claude",
        prompt,
        "-p",
        "--model",
        CLAUDE_HEADLESS_MODEL,
        "--output-format",
        "text",
        "--tools",
        "Read,Glob,LS,Grep,FileSearch,Bash(git status,git diff,git log,git show)",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=ADVISORY_BACKEND_TIMEOUT_SECONDS,
            cwd=str(resolved_work_dir),
            env={**os.environ},
            stdin=subprocess.DEVNULL,
        )

        if result.returncode != 0:
            return (
                f"Error: claude exited with code {result.returncode}\n"
                f"Stderr: {result.stderr}\n"
                f"Stdout: {result.stdout}"
            )

        return (
            result.stdout.strip()
            if result.stdout
            else "Warning: Empty response from Claude Code."
        )
    except subprocess.TimeoutExpired:
        return f"Error: Claude Code headless exceeded {ADVISORY_BACKEND_TIMEOUT_SECONDS}s timeout."
    except Exception as exc:
        return f"Unexpected Error executing Claude Code: {exc}"


def _minimax_openai_endpoint() -> str:
    raw_base = (
        os.environ.get("MINIMAX_OPENAI_BASE_URL")
        or os.environ.get("MINIMAX_BASE_URL")
        or MINIMAX_DEFAULT_OPENAI_BASE_URL
    ).rstrip("/")
    if raw_base.endswith("/chat/completions"):
        return raw_base
    return f"{raw_base}/chat/completions"


def _minimax_api_key() -> str | None:
    fallback_path = os.environ.get("MINIMAX_API_KEY_FILE")
    if not fallback_path and MINIMAX_DEFAULT_API_KEY_FILE.exists():
        fallback_path = str(MINIMAX_DEFAULT_API_KEY_FILE)
    return get_api_key("MINIMAX_API_KEY", fallback_path)


def _strip_minimax_thinking(text: str) -> str:
    return re.sub(r"(?is)<think>.*?</think>\s*", "", text).strip()


def _redact_secret(text: str, secret: str | None) -> str:
    if not secret:
        return text
    return text.replace(secret, "[redacted]")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def _minimax_message_content(payload: dict) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return _strip_minimax_thinking(content)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return _strip_minimax_thinking("\n".join(parts))
    return ""


def _run_minimax_openai_sync(prompt: str, system_hint: str | None = None) -> str:
    api_key = _minimax_api_key()
    if not api_key:
        return (
            "MiniMax API configuration error: missing MINIMAX_API_KEY or "
            "MINIMAX_API_KEY_FILE."
        )

    messages: list[dict[str, str]] = []
    if system_hint:
        messages.append({"role": "system", "content": system_hint})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": os.environ.get("MINIMAX_MODEL") or MINIMAX_DEFAULT_MODEL,
        "messages": messages,
        "temperature": _env_float("MINIMAX_TEMPERATURE", 0.2),
        "max_tokens": _env_int("MINIMAX_MAX_TOKENS", 2048),
        "reasoning_split": True,
    }
    request = urllib.request.Request(
        _minimax_openai_endpoint(),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=ADVISORY_BACKEND_TIMEOUT_SECONDS) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = _redact_secret(exc.read().decode("utf-8", errors="replace"), api_key)[:1000]
        return f"MiniMax API error {exc.code}: {body}"
    except urllib.error.URLError as exc:
        return f"MiniMax API connection error: {exc.reason}"
    except TimeoutError:
        return f"MiniMax API exceeded {ADVISORY_BACKEND_TIMEOUT_SECONDS}s timeout."
    except Exception as exc:
        return f"Unexpected MiniMax API error: {exc}"

    content = _minimax_message_content(response_payload)
    return content if content else "Warning: Empty response from MiniMax API."


def _run_minimax_sync(prompt: str, system_hint: str | None = None) -> str:
    return _run_minimax_openai_sync(prompt, system_hint)


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def consult_claude_headless(
    prompt: str,
    work_dir: str | None = None,
    cycle_id: str | None = None,
) -> str:
    """
    Read-only multi-file analysis via Claude Code headless.

    Allowed capabilities:
    - read files
    - search across the repo
    - inspect git state with read-only git commands

    Not allowed:
    - file edits
    - writes
    - build/test execution
    - arbitrary shell commands
    """
    auth_error = await _authorize_tool_call("consult_claude_headless")
    if auth_error:
        return await _persist_and_return(auth_error)

    aggregate_error = await _consume_aggregate_quota()
    if aggregate_error:
        return await _persist_and_return(aggregate_error)

    cycle_error = await _register_cycle_call(cycle_id, "consult_claude_headless")
    if cycle_error:
        return await _persist_and_return(cycle_error)

    quota_error = await _consume_headless_quota()
    if quota_error:
        return await _persist_and_return(quota_error)

    structured_prompt = (
        "Return structured text only.\n\n"
        f"Runtime filesystem boundary: inspect only files under {REPO_ROOT}. "
        "Do not read absolute paths, parent directories, symlink escapes, or "
        "source-root files outside that target workspace. If the user task asks "
        "for anything outside that boundary, return POLICY_ERROR.\n\n"
        "Use exactly these sections:\n"
        "SUMMARY:\n"
        "...\n\n"
        "KEY_FINDINGS:\n"
        "- ...\n\n"
        "RECOMMENDED_ACTIONS:\n"
        "- ...\n\n"
        "VERIFICATION_HINTS:\n"
        "- ...\n\n"
        "LIMITATIONS:\n"
        "- ...\n\n"
        f"User task:\n{prompt}"
    )
    boundary_error = _runtime_prompt_boundary_error(prompt)
    if boundary_error:
        return await _persist_and_return(boundary_error)

    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(
        None,
        _run_claude_code_sync,
        structured_prompt,
        work_dir,
    )
    return await _persist_and_return(
        _validate_sections(
            response,
            ["SUMMARY:", "KEY_FINDINGS:", "RECOMMENDED_ACTIONS:"],
        )
    )


@mcp.tool()
async def consult_architect(
    task_description: str,
    file_path: str,
    error_log: str,
    cycle_id: str | None = None,
    stack_hint: str | None = None,
) -> str:
    """
    Debugging and architecture consultation via Claude API.

    Escalates from Haiku to Sonnet only after repeated failures on the same
    file and same normalized error signature.
    """
    auth_error = await _authorize_tool_call("consult_architect")
    if auth_error:
        return await _persist_and_return(auth_error)

    aggregate_error = await _consume_aggregate_quota()
    if aggregate_error:
        return await _persist_and_return(aggregate_error)

    cycle_error = await _register_cycle_call(cycle_id, "consult_architect")
    if cycle_error:
        return await _persist_and_return(cycle_error)

    api_key = get_api_key("ANTHROPIC_API_KEY", "/root/.anthropic_key")
    if not api_key:
        return await _persist_and_return("Error: Missing ANTHROPIC_API_KEY.")

    client = AsyncAnthropic(api_key=api_key)
    count = await _bump_architect_counter(file_path, error_log)

    code_context = read_file_content(file_path)
    if code_context.startswith("Error"):
        return await _persist_and_return(code_context)

    escalated = count >= ARCHITECT_ESCALATION_THRESHOLD
    if escalated:
        model_id = "claude-sonnet-4-6"
        prefix = f"STATUS: ESCALATED\nMODEL: {model_id}\nATTEMPT: {count}"
        max_tokens = 4096
    else:
        model_id = "claude-haiku-4-5-20251001"
        prefix = f"STATUS: STANDARD\nMODEL: {model_id}\nATTEMPT: {count}"
        max_tokens = 2048

    system_prompt = (
        "You are a senior software debugging advisor.\n"
        "Work across languages and stacks.\n"
        "Be precise. Give diagnosis, likely root cause, and a bounded fix plan.\n"
        "Return structured text only with these sections:\n"
        "SUMMARY:\n"
        "ROOT_CAUSE:\n"
        "FIX_PLAN:\n"
        "RISKS:\n"
        "VERIFY:\n"
    )
    if stack_hint:
        system_prompt += f"\nStack hint: {stack_hint}"

    prompt = (
        f"## Task\n{task_description}\n\n"
        f"## Error Log\n```\n{error_log}\n```\n\n"
        f"## Source ({file_path})\n```\n{code_context}\n```"
    )

    try:
        response = await client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        if escalated:
            await _reset_architect_counter(file_path, error_log)
        return await _persist_and_return(
            _validate_sections(
                f"{prefix}\n{response.content[0].text}",
                ["SUMMARY:", "ROOT_CAUSE:", "FIX_PLAN:", "RISKS:", "VERIFY:"],
            )
        )
    except Exception as exc:
        return await _persist_and_return(f"API Error: {exc}")


@mcp.tool()
async def routine_code_review(
    feature_goal: str,
    file_path: str,
    cycle_id: str,
    stack_hint: str | None = None,
) -> str:
    """
    One review per file per cycle. Lightweight sanity-check review only.
    """
    auth_error = await _authorize_tool_call("routine_code_review")
    if auth_error:
        return await _persist_and_return(auth_error)

    aggregate_error = await _consume_aggregate_quota()
    if aggregate_error:
        return await _persist_and_return(aggregate_error)

    cycle_error = await _register_cycle_call(cycle_id, "routine_code_review")
    if cycle_error:
        return await _persist_and_return(cycle_error)

    review_error = await _record_review_once(file_path, cycle_id)
    if review_error:
        return await _persist_and_return(review_error)

    api_key = get_api_key("ANTHROPIC_API_KEY", "/root/.anthropic_key")
    if not api_key:
        return await _persist_and_return("Error: Missing ANTHROPIC_API_KEY.")

    client = AsyncAnthropic(api_key=api_key)
    code = read_file_content(file_path)
    if code.startswith("Error"):
        return await _persist_and_return(code)

    system_prompt = (
        "You are a performance- and correctness-focused reviewer.\n"
        "Work across languages and stacks.\n"
        "Return structured text only with these sections:\n"
        "SUMMARY:\n"
        "TOP_ISSUES:\n"
        "SUGGESTED_FIXES:\n"
        "RISK_LEVEL:\n"
    )
    if stack_hint:
        system_prompt += f"\nStack hint: {stack_hint}"

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": f"Goal: {feature_goal}\n\n```\n{code}\n```",
                }
            ],
        )
        return await _persist_and_return(
            _validate_sections(
                "STATUS: OK\n"
                "MODEL: claude-haiku-4-5-20251001\n"
                f"{response.content[0].text}",
                ["SUMMARY:", "TOP_ISSUES:", "SUGGESTED_FIXES:", "RISK_LEVEL:"],
            )
        )
    except Exception as exc:
        return await _persist_and_return(f"API Error: {exc}")


@mcp.tool()
async def consult_minimax(
    prompt: str,
    system_hint: str | None = None,
    cycle_id: str | None = None,
) -> str:
    """
    Cost-effective general advisor with no project filesystem access.
    """
    auth_error = await _authorize_tool_call("consult_minimax")
    if auth_error:
        return await _persist_and_return(auth_error)

    aggregate_error = await _consume_aggregate_quota()
    if aggregate_error:
        return await _persist_and_return(aggregate_error)

    cycle_error = await _register_cycle_call(cycle_id, "consult_minimax")
    if cycle_error:
        return await _persist_and_return(cycle_error)

    structured_prompt = (
        "Return structured text only.\n\n"
        "Use exactly these sections:\n"
        "SUMMARY:\n"
        "REASONING:\n"
        "RECOMMENDED_ACTIONS:\n"
        "LIMITATIONS:\n"
    )

    loop = asyncio.get_running_loop()
    final_prompt = f"{structured_prompt}\n\n{prompt}"
    response = await loop.run_in_executor(None, _run_minimax_sync, final_prompt, system_hint)
    return await _persist_and_return(
        _validate_sections(
            response,
            ["SUMMARY:", "REASONING:", "RECOMMENDED_ACTIONS:"],
        )
    )


try:
    asyncio.run(_load_state())
except RuntimeError:
    pass


if __name__ == "__main__":
    mcp.run()
