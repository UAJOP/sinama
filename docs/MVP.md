# SINAMA MVP Scope

## Milestone 0 — Foundation

- [x] Define product problem and target user
- [x] Define MVP architecture
- [x] Define repository structure
- [x] Add safe environment-variable template
- [x] Create development branch
- [ ] Scaffold frontend and backend applications

## Milestone 1 — First vertical slice

Goal: one end-to-end test run with no paid API dependency.

- [x] FastAPI health endpoint
- [x] Next.js dashboard shell
- [x] mock insurance agent endpoint
- [x] scenario schema
- [x] 5 hand-reviewed Turkish scenarios
- [x] scenario runner
- [x] deterministic pass/fail evaluators
- [ ] run detail view with transcript and tool trace

Definition of done:

A developer can run the project locally, execute the five demo scenarios against the mock agent and inspect why each scenario passed or failed.

## Milestone 2 — Reliability features

- [ ] expand to 20 hand-reviewed scenarios
- [ ] hallucination evaluator
- [ ] handoff evaluator
- [ ] prompt-injection / policy scenarios
- [ ] JSON/tool parameter validation
- [ ] run summary metrics
- [ ] severity classification

## Milestone 3 — Regression testing

- [ ] version labels for agent configurations
- [ ] compare two test runs
- [ ] highlight new regressions and resolved failures
- [ ] release-readiness summary
- [ ] CI-friendly exit status or API result

## Milestone 4 — Portfolio-ready release

- [ ] 50–100 curated Turkish scenarios
- [ ] polished README and architecture diagram
- [ ] screenshots / demo recording
- [ ] portfolio case study on kaanbalci.com
- [ ] public demo deployment
- [ ] subdomain target: `sinama.kaanbalci.com`

## MVP quality bar

The project is not considered complete because the dashboard looks polished. It is complete when test outcomes are reproducible, evidence is inspectable and a change in agent behavior can be detected as a regression.
