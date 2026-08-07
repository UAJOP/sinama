# Security and Secrets Policy

## Rules

1. Never commit API keys, passwords, service-role tokens, database credentials or customer secrets.
2. Use `.env.example` only for variable names and safe local defaults.
3. Keep privileged provider/database keys server-side in the FastAPI runtime.
4. Never expose secrets through `NEXT_PUBLIC_*` variables.
5. Do not use real customer conversations or private client workflows in public demo data.
6. Redact authorization headers and secret-bearing request fields from logs and traces.
7. Treat agent endpoints as untrusted external systems: apply timeouts, response-size limits and schema validation.
8. Store only the minimum test evidence required for debugging.

## Public demo data

The initial insurance domain is fictional. Names, policy numbers, claim IDs, documents and conversations must be synthetic.

## Environment handling

Local development:

```text
.env.example  -> committed template
.env          -> local secrets, ignored by Git
```

Hosted environments should use the provider's encrypted environment-variable/secret management rather than repository files.

## Logging

Do not log:

- API keys or bearer tokens
- passwords
- full authentication headers
- database connection strings
- sensitive uploaded document contents

When request/response evidence is needed, persist a sanitized representation.

## External agent outbound policy

External agent URLs are untrusted input. Before every turn SINAMA:

- accepts only HTTP/HTTPS, and requires HTTPS when `SINAMA_ENVIRONMENT=production` or the app is running on Railway,
- rejects URL user information, fragments, localhost and internal-only host suffixes,
- rejects loopback, private, link-local, reserved, multicast, unspecified and other non-global IP addresses,
- resolves domain names, rejects the destination when any returned IPv4 or IPv6 address is non-public, and pins the connection to an already validated public address while preserving Host/TLS SNI validation,
- blocks known cloud-metadata names and addresses,
- disables redirects instead of trusting an unvalidated redirect destination,
- ignores environment-provided HTTP proxy settings for external-agent requests,
- applies one bounded deadline across DNS validation and the HTTP turn,
- streams responses and stops once the configured byte limit is exceeded, and
- converts transport/schema failures into fixed safe messages without response bodies, request URLs or authorization values.

Bearer tokens arrive only in runtime request bodies, are represented as secret values server-side, are captured only by the active in-process run task and are not persisted in summaries, evidence or logs.

## Reporting

This repository is currently a portfolio/MVP project. Security issues should be reported privately to the repository owner rather than demonstrated against a public deployment.
