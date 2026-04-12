# VS Code UX

## UX Direction
The human-facing interface may closely copy the visual and interaction style of
the VS Code Codex extension.

That is acceptable for the UX layer.

## Important Boundary
The backend architecture must still follow the custom project design in this
repository.

So:
- frontend may imitate Codex closely
- backend behavior must not inherit Codex's default workflow assumptions
- Codex runtime remains the primary chat/runtime/tool substrate
- orchestration remains a supplemental project layer above that substrate

## UX Role
- human-facing webview/sidebar first
- Activity Bar icon as the primary product entry
- concise transcript-oriented experience
- compact composer
- execution/activity visibility
- structured clarification choices when the missing information is classifiable
- approval/full-access affordances when needed
- contextual stop affordance only while governed work is actively running
- no visible hold or reconnect controls in the primary webview UX
- Governor dialogue is allowed for progress, explanation, and idea discussion,
  but remains read-only by default

The UX must not become:
- a second governor
- a workflow-truth source
- a hidden operator console
