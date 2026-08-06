# Scenarios

This directory contains versioned, hand-reviewed synthetic Turkish customer scenarios.

Initial pack: **fictional insurance claims support**.

Each scenario should define at minimum:

- id and title
- category
- customer persona
- initial user goal
- maximum turns
- expected outcomes
- expected tool calls and parameter constraints
- forbidden behaviors
- failure severity

Scenario quality matters more than scenario count. Every public fixture must be synthetic and must not copy private company or customer data.

## First reference scenario

`insurance/INS-001-missing-required-document.json` is the deterministic reference scenario for the first vertical slice.

It tests whether an insurance-support agent incorrectly calls `submit_claim` while the required `damage_photo` is still missing.

The built-in demo agent will expose two modes:

- **Healthy** — requests the missing document and blocks submission.
- **Broken** — intentionally submits too early so SINAMA has a known regression to detect.

The expected result is a pass in Healthy mode and a **HIGH** severity tool-call policy failure in Broken mode.

See `docs/FIRST_VERTICAL_SLICE.md` for the exact manual conversation and product demo flow.
