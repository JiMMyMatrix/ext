# Intake

## Purpose
Intake is the front door for human requests inside the unified system.

## Allowed Responsibilities
- receive raw natural-language human input
- normalize the request into a bounded draft
- ask bounded clarification when needed
- hand off a draft for orchestration acceptance

## Forbidden Responsibilities
- becoming the Governor
- using advisor tools
- deciding merge-ready
- deciding interrupt legality
- deciding actor authority
- writing dispatch truth
- performing substantive repo work

## Required Outputs
- `raw_human_request.md`
- `request_draft.json`
- eventually `accepted_intake.json` after orchestration acceptance

## Handoff Rule
Governor should consume accepted intake, not reinterpret the raw human prompt
as a parallel authority source.
