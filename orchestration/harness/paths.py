from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_MISSING = object()
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class HarnessPaths:
	repo_root: Path
	source_root: Path
	orchestration_root: Path
	prompts_root: Path
	contracts_root: Path
	scripts_root: Path
	runtime_root: Path
	actors_root: Path
	agent_root: Path
	intakes_root: Path
	orchestration_state_root: Path
	ui_session_path: Path


def resolve_repo_root(repo_root: str | Path | None = None) -> Path:
	if repo_root is not None:
		return Path(repo_root).resolve()
	return Path(os.environ.get("ORCHESTRATION_REPO_ROOT") or _PACKAGE_ROOT).resolve()


def resolve_source_root(repo_root: str | Path | None = None) -> Path:
	configured = os.environ.get("ORCHESTRATION_SOURCE_ROOT")
	if configured:
		return Path(configured).resolve()
	root = resolve_repo_root(repo_root)
	if (root / "orchestration" / "scripts" / "orchestrate.py").exists():
		return root
	return _PACKAGE_ROOT.resolve()


def resolve_agent_root(root: Path) -> Path:
	configured = os.environ.get("ORCHESTRATION_AGENT_ROOT")
	if not configured:
		return root / ".agent"
	candidate = Path(configured)
	if not candidate.is_absolute():
		candidate = root / candidate
	return candidate.resolve()


def resolve_paths(repo_root: str | Path | None = None) -> HarnessPaths:
	root = resolve_repo_root(repo_root)
	source_root = resolve_source_root(root)
	orchestration_root = source_root / "orchestration"
	agent_root = resolve_agent_root(root)
	orchestration_state_root = agent_root / "orchestration"
	return HarnessPaths(
		repo_root=root,
		source_root=source_root,
		orchestration_root=orchestration_root,
		prompts_root=orchestration_root / "prompts",
		contracts_root=orchestration_root / "contracts",
		scripts_root=orchestration_root / "scripts",
		runtime_root=orchestration_root / "runtime",
		actors_root=orchestration_root / "runtime" / "actors",
		agent_root=agent_root,
		intakes_root=agent_root / "intakes",
		orchestration_state_root=orchestration_state_root,
		ui_session_path=orchestration_state_root / "ui_session.json",
	)


def utc_now() -> str:
	return (
		datetime.now(timezone.utc)
		.replace(microsecond=0)
		.isoformat()
		.replace("+00:00", "Z")
	)


def ensure_dir(path: Path) -> None:
	path.mkdir(parents=True, exist_ok=True)


def ensure_parent(path: Path) -> None:
	ensure_dir(path.parent)


JsonValidator = Callable[[Any, list[str]], None]


def _json_text(payload: Any) -> str:
	return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write_text_atomic(path: Path, text: str) -> None:
	ensure_parent(path)
	tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
	try:
		tmp_path.write_text(text, encoding="utf-8")
		os.replace(tmp_path, path)
	except Exception:
		try:
			tmp_path.unlink()
		except FileNotFoundError:
			pass
		raise


def write_json(path: Path, payload: Any) -> None:
	_write_text_atomic(path, _json_text(payload))


def validate_then_write(path: Path, payload: Any, validator: JsonValidator) -> None:
	failures: list[str] = []
	validator(payload, failures)
	if failures:
		raise ValueError("; ".join(failures))
	write_json(path, payload)


def load_json(path: Path, *, default: Any = _MISSING) -> Any:
	if not path.exists():
		if default is not _MISSING:
			return default
		raise FileNotFoundError(path)
	return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
	ensure_parent(path)
	path.write_text(text, encoding="utf-8")


def repo_relative(path: Path, repo_root: str | Path | None = None) -> str:
	root = resolve_repo_root(repo_root)
	return str(path.resolve().relative_to(root))


def source_or_repo_ref(path: Path, repo_root: str | Path | None = None) -> str:
	resolved = path.resolve()
	root = resolve_repo_root(repo_root)
	try:
		return str(resolved.relative_to(root))
	except ValueError:
		return str(resolved)


def trim_text(text: str | None) -> str:
	return re.sub(r"\s+", " ", (text or "").strip())


def summarize(text: str, limit: int = 72) -> str:
	normalized = trim_text(text)
	if len(normalized) <= limit:
		return normalized
	return normalized[: max(0, limit - 3)].rstrip() + "..."


def unique_strings(values: list[str]) -> list[str]:
	seen: set[str] = set()
	result: list[str] = []
	for value in values:
		candidate = trim_text(value)
		if not candidate:
			continue
		key = candidate.casefold()
		if key in seen:
			continue
		seen.add(key)
		result.append(candidate)
	return result


def slugify(value: str, *, limit: int = 40) -> str:
	normalized = re.sub(r"[^a-z0-9]+", "-", trim_text(value).lower()).strip("-")
	if not normalized:
		return "request"
	return normalized[:limit].strip("-") or "request"


def git_branch_name(repo_root: str | Path | None = None) -> str | None:
	try:
		result = subprocess.run(
			["git", "branch", "--show-current"],
			cwd=resolve_repo_root(repo_root),
			check=False,
			capture_output=True,
			text=True,
		)
	except OSError:
		return None

	branch = result.stdout.strip()
	return branch or None


def default_lane(branch: str | None) -> str:
	if not branch:
		return "lane/intake"
	return "lane/" + branch.replace("/", "-")


def next_intake_ref(prompt: str) -> str:
	timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
	return f"{timestamp}-{slugify(prompt)}"


def constraint_hints_from_text(text: str) -> list[str]:
	constraints: list[str] = []
	segments = re.split(r"[.\n;]+", text)
	for segment in segments:
		candidate = trim_text(segment)
		lower = candidate.lower()
		if not candidate:
			continue
		if any(
			marker in lower
			for marker in (
				"keep ",
				"keeping ",
				"preserve ",
				"preserving ",
				"retain ",
				"without ",
				"must ",
				"should ",
				"constraint",
				"do not ",
				"don't ",
			)
		):
			constraints.append(candidate)
	return unique_strings(constraints)


def prompt_path(name: str, repo_root: str | Path | None = None) -> Path:
	return resolve_paths(repo_root).prompts_root / name


def prompt_ref(name: str, repo_root: str | Path | None = None) -> str:
	return source_or_repo_ref(prompt_path(name, repo_root), repo_root)


def contract_path(name: str, repo_root: str | Path | None = None) -> Path:
	return resolve_paths(repo_root).contracts_root / name


def contract_ref(name: str, repo_root: str | Path | None = None) -> str:
	return source_or_repo_ref(contract_path(name, repo_root), repo_root)


def script_path(name: str, repo_root: str | Path | None = None) -> Path:
	return resolve_paths(repo_root).scripts_root / name


def script_ref(name: str, repo_root: str | Path | None = None) -> str:
	return source_or_repo_ref(script_path(name, repo_root), repo_root)


def actor_config_path(name: str, repo_root: str | Path | None = None) -> Path:
	return resolve_paths(repo_root).actors_root / name


def actor_config_ref(name: str, repo_root: str | Path | None = None) -> str:
	return source_or_repo_ref(actor_config_path(name, repo_root), repo_root)
