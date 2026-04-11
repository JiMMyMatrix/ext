---
name: spawn-bridge
description: Environment-specific boundary skill for the thin spawn bridge MCP server in this Runpod setup.
---

# Spawn Bridge Skill

This skill lives under the environment-specific, symlink-backed skill root at
`/workspace/.codex_brain/skills/` in this Runpod setup. Treat that path as
valid here, not as a portable repo-default assumption.

## Use this skill when
- you are in `GOVERNOR` mode
- a dispatch has just been emitted
- you must determine whether the next step stays helper-backed or crosses into
  the live chat-window subagent path

## Do not use this skill when
- you are in `CHAT` mode
- no dispatch exists yet
- you are trying to replace the actual live chat-window spawn with a hidden
  MCP-side spawn

## Required sequence
1. After dispatch emission, call the spawn bridge first.
2. If the bridge resolves `helper_runtime`, do not live-spawn anything.
3. If the bridge resolves `live_subagent`, use the prepared handoff artifact
   and then spawn the executor in the live chat window.
   - if the dispatch explicitly requests overlap isolation, the prepared
     handoff may also include isolated worktree metadata and candidate
     packaging instructions
4. After executor completion, if `review_required = true`, call the bridge
   again for reviewer handoff.
5. If live review is still missing, finalization must remain `needs_review`.
6. If the bridge or start guard blocks the dispatch because dependencies are
   incomplete or `scope_reservations` overlap active same-lane work, serialize
   or wait; do not treat that routine block as a human-escalation event by
   default.
7. Dispatch emission, bridge resolution, and handoff preparation are internal workflow steps, not legal human-stop reasons by themselves.

## Tool intent
The bridge is only a boundary formalizer:
- resolve path
- prepare handoff
- record boundary artifacts
- return the exact next live chat-window action

It must not pretend to own a hidden internal spawn API.
It also does not grant integration authority: overlap-isolated candidates
still require governor-side acceptance and serial lane-branch integration.
