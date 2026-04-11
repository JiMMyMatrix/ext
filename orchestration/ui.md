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
- human-facing execution window only
- concise transcript-oriented experience
- compact composer
- execution/activity visibility
- approval/interrupt affordances when needed

The UX must not become:
- a second governor
- a workflow-truth source
- a hidden operator console
