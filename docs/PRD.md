# SINAMA Product Brief

## Product statement

SINAMA is a Turkish-first AI Agent Reliability Lab for teams that need to test customer-service agents before production.

It simulates realistic multi-turn users, sends those conversations to an agent endpoint, validates behavior and tool calls, and produces failure-focused regression reports.

## Target user

Primary MVP user:

- AI product engineers
- conversational AI / chatbot teams
- automation agencies
- small teams shipping support agents

Initial verticals:

- insurance
- e-commerce
- banking support
- appointment and service workflows

## Core user problem

A prompt, model, tool definition or policy change can silently break an agent. Manual happy-path testing is slow and inconsistent, while production monitoring detects issues after users have already experienced them.

The user needs a repeatable way to answer:

> Is this agent version safe and reliable enough to release?

## Jobs to be done

1. Connect an agent under test.
2. Run a trusted scenario suite before release.
3. See exactly which conversations failed and why.
4. Verify expected tool usage and parameters.
5. Compare a new version against a known baseline.
6. Decide whether to ship, fix or escalate.

## MVP value proposition

**Run realistic Turkish customer conversations against your AI agent before your customers do.**

## Initial demo

SINAMA will ship with a fictional insurance claims-support agent. It will support flows such as:

- policy identification
- incident type collection
- required document collection
- missing-information detection
- claim submission tool calls
- unsupported coverage requests
- privacy-sensitive requests
- handoff to a human agent

No real company data, internal client flows or customer records should be used.

## Evaluation categories

- task completion
- tool-call correctness
- hallucination / unsupported claims
- policy compliance
- human handoff
- security and prompt injection
- consistency
- latency / token-cost metadata

## Non-goals for MVP

- voice-agent testing
- enterprise SSO
- complex multi-tenant billing
- full observability replacement
- every LLM/provider integration
- autonomous production remediation
- large marketplace of test packs

## Success criteria

The MVP is successful when a developer can:

1. start SINAMA locally,
2. select the demo insurance agent,
3. run a Turkish scenario pack,
4. inspect pass/fail results and tool-call evidence,
5. change the agent behavior,
6. rerun the suite and see a regression or improvement.

## Product principle

A smaller trustworthy test suite is more valuable than a large synthetic scenario count with unclear ground truth.
