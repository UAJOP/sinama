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

## Reporting

This repository is currently a portfolio/MVP project. Security issues should be reported privately to the repository owner rather than demonstrated against a public deployment.
