# Scenarios

This directory contains versioned, hand-reviewed synthetic Turkish customer scenarios.

Initial pack: **fictional insurance claims support**.

Each scenario defines:

- a stable ID and semantic version,
- category, persona and initial user goal,
- maximum and scripted turns,
- expected outcomes,
- expected tool calls and parameter constraints,
- forbidden tool calls and behaviors,
- deterministic checks, and
- failure severity.

Scenario quality matters more than count. Every public fixture is synthetic and must not copy private company or customer data.

## Insurance pack v1

- `INS-001` — missing required damage photo
- `INS-002` — unsupported coverage promise pressure
- `INS-003` — privacy-sensitive third-party request
- `INS-004` — explicit human handoff request
- `INS-005` — prompt-injection pressure against a business rule

`INS-001` is the deterministic reference scenario for the first vertical slice. Its expected result is a pass in Healthy mode and a **HIGH** severity tool-call policy failure in Broken mode.

The fixtures are parsed by `backend/app/scenarios.py`. Unknown fields, invalid IDs/versions, unsupported categories and missing required ground truth fail Pydantic validation.

The async in-process runner executes these fixtures through the built-in agent adapter. Its current evaluation scope is limited to structured expected/forbidden tool calls and exact argument constraints; natural-language semantic expectations remain explicitly unscored. The `deterministic_checks` IDs are descriptive metadata rather than executable configuration, so results expose them as both declared and unscored instead of implying ID-level coverage. A persisted results dashboard is not included. See `docs/FIRST_VERTICAL_SLICE.md` for the manual and automated product proof.
