# Advisory Support

## Two Consulting Surfaces

Corgi intentionally has two separate advisor surfaces:

1. **Corgi Governor runtime advisory** is the product/runtime surface. It is
   launched through `mcp_server.py`, runs in `corgi-governor-runtime` context,
   requires `CORGI_ADVISORY_CALLER_ROLE=governor`, and constrains filesystem
   advisor reads to the current target workspace.
2. **Development consulting** is for building Corgi itself. It is launched
   through `dev_mcp_server.py`, runs in `corgi-development-consulting` context,
   uses developer-scoped state under `.agent/development/advisory`, and is not
   registered in the shipped runtime config.

The two surfaces share implementations so tool behavior stays consistent, but
their launchers, context names, caller roles, state directories, and workspace
boundaries are deliberately different.

## Corgi Governor Runtime Role
The runtime advisory MCP server and its skills are a standard Governor support
mechanism. They are cost-gated and should be used only when the Governor
encounters truly difficult, high-risk, ambiguous, or repeatedly failing
problems.

## Hard Boundary
Only the Governor may use runtime advisor tools.

Not allowed:
- UX
- Intake
- Orchestration control-plane logic acting on its own
- Executor
- Reviewer
- development/test automation pretending to be runtime Governor

## Semantics
- advisor output is advice only
- advisor output is not workflow truth
- advisor output is not interrupt authority
- advisor output is not merge authority
- advisor output is not actor authority

## Runtime Meaning
Advisory tools are a Governor-scoped capability, not a shared system
capability.

They may help the Governor reason, but the Governor remains the single final
decider.

Runtime advisor file access is target-workspace scoped. When Corgi is testing
or operating against a separate target repo, the runtime server uses
`ORCHESTRATION_REPO_ROOT` as that target and `ORCHESTRATION_SOURCE_ROOT` only
for loading Corgi's orchestration code.

## Regular Use
Use the routing skill first when choosing an advisor:
- `consult_minimax` for bounded general reasoning or option comparison without
  repo file access
- `consult_claude_headless` for read-only multi-file repo/code analysis
- `consult_architect` for repeated or non-trivial debugging with a likely
  root-cause file
- `routine_code_review` for one completed file after a bounded change

Default to no advisor for routine work where the Governor already knows the
next safe action. Prefer one advisor first. Use both MiniMax and Claude Headless
only when the issue is truly difficult and a wrong decision would cost more
than two consultations. Do not surface advisor output as a human-facing stop
unless a legal interrupt condition also exists.

## Registration
The shipped runtime registers only the Governor advisory MCP server through
`mcp_server.py`, which is a compatibility shim for
`orchestration/scripts/serve_advisory_mcp.py`. The launcher handles the source
root, target workspace root, Python path, repo-local advisory virtualenv, and
approved/Homebrew interpreter selection before running
`orchestration/runtime/advisory/mcp_server.py`.

Do not register `dev_mcp_server.py` in the Corgi runtime config. Use it only
from the development environment when the developer/Codex pair needs an
advisor.

Prepare the repo-local advisory environment with:

```bash
python3 orchestration/scripts/setup_advisory_mcp_env.py
```

For MiniMax consultations, set `MINIMAX_API_KEY` in the Governor/advisory
process environment. The server uses MiniMax's OpenAI-compatible endpoint by
default (`https://api.minimax.io/v1`) and keeps `consult_grok_advisor` only as
a backward-compatible alias.

For runtime Governor use, the advisory server may read an ignored token file at
the target workspace's `.agent/orchestration/advisory/minimax_api_key`, or a
custom `MINIMAX_API_KEY_FILE`. For development consulting, prefer a separate
ignored token file under `.agent/development/advisory/minimax_api_key` or set
`MINIMAX_API_KEY` explicitly. The Grok fallback is only compatible with MiniMax's
documented npm Grok CLI (`@vibe-kit/grok-cli`); if another `grok` executable is
on PATH, set `MINIMAX_GROK_COMMAND` to the compatible binary or use the direct
MiniMax API path.

The canonical manual command is:

```bash
python3 orchestration/scripts/orchestrate.py advisory serve
```

Development consulting can be launched manually with:

```bash
python3 dev_mcp_server.py
```
