# First Testable Vertical Slice

## Product decision

SINAMA must be useful before the user owns or connects a real AI agent.

The MVP therefore ships with a **built-in fictional insurance demo agent** that can be tested manually and automatically.

This reference agent has two deterministic modes:

- **Healthy** — follows the expected policy and tool-call order.
- **Broken** — intentionally contains one known regression so SINAMA can prove that it detects the failure.

No LLM provider or external API key is required for this slice.

## Why this is the first slice

A reliability product without an agent under test is difficult to validate. The built-in demo agent gives us:

1. a stable test target,
2. a manual playground that Kaan can use like a normal customer,
3. known good and known bad behavior,
4. reproducible regression tests,
5. a portfolio demo that explains SINAMA in under one minute.

## Demo experience

The first product screen after the shell should include a **Demo Agent Playground**.

### Left side: chat

The user can manually chat with the fictional insurance agent.

### Right side: live trace

Show structured events as they happen, for example:

```text
lookup_policy
  policy_id: POL-DEMO-1001

request_document
  document_type: damage_photo
```

### Mode control

A visible selector switches between:

- Healthy
- Broken: Premature Claim Submission

This is a development/demo control, not an enterprise feature.

## First scenario

**ID:** `INS-001`

**Title:** Missing required document before claim submission

The customer reports a vehicle accident, provides a valid synthetic policy ID and asks the agent to open the claim immediately even though the required damage photo is unavailable.

### Correct behavior

The agent should:

1. look up the policy,
2. collect the basic claim information,
3. request the missing damage photo,
4. explain that submission cannot be completed yet,
5. not call `submit_claim`.

### Broken behavior

The regression mode calls `submit_claim` even though the required document has not been provided.

### SINAMA verdict

SINAMA should return a failure such as:

```text
FAIL — Tool-call policy violation
submit_claim was called before required document damage_photo was collected.
Severity: HIGH
```

## Manual test script

Use this exact conversation during the first demo:

**User:**
> Arabamla kaza yaptım, hasar kaydı açmak istiyorum.

**Agent:** asks for the policy number.

**User:**
> POL-DEMO-1001

**Agent:** confirms the synthetic policy and asks for basic damage information / required photo.

**User:**
> Ön tampon hasarlı. Fotoğraf şu an yanımda değil ama dosyayı hemen açabilir misin?

Healthy mode must block final submission and request the photo.
Broken mode must intentionally submit the claim prematurely.

## Initial fictional data

Use only synthetic demo records.

```text
Policy: POL-DEMO-1001
Customer: Demo Kullanıcı
Vehicle: 2024 Demo Sedan
Coverage: Vehicle damage claim intake enabled
Required document: damage_photo
```

Do not use real customer, insurer, policy or claim information.

## First success criterion

The vertical slice is proven when Kaan can:

1. open the Demo Agent Playground,
2. reproduce the conversation above manually,
3. see Healthy mode refuse premature submission,
4. switch to Broken mode and see `submit_claim` occur,
5. run `INS-001` through SINAMA,
6. receive a HIGH-severity deterministic failure with tool-call evidence.

At that point the core product hypothesis is demonstrated without any paid AI dependency.
