# Orchestration Runtime

This directory contains runtime-adjacent assets for the shipped orchestration
surface.

## Contents
- `actors/`: actor runtime config templates
- `advisory/`: Governor-only advisory runtime support
- `config.toml`: governor session runtime template

## Advisory MCP Registration
`config.toml` registers the Governor advisory MCP server through the repo-root
`mcp_server.py` compatibility entrypoint. That shim delegates to
`orchestration/scripts/serve_advisory_mcp.py`, which selects the approved
Python interpreter, prefers the repo-local advisory virtualenv when present,
falls back to Homebrew Python when appropriate, sets `ORCHESTRATION_REPO_ROOT`,
and then launches
`orchestration/runtime/advisory/mcp_server.py`.

Prepare or refresh the repo-local advisory Python environment with:

```bash
python3 orchestration/scripts/setup_advisory_mcp_env.py
```

The canonical CLI route is:

```bash
python3 orchestration/scripts/orchestrate.py advisory serve
```

## Rule
Runtime helpers here support orchestration. They do not create a second source
of workflow truth.
