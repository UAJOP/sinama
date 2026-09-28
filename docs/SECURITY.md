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

## Workspace tenant boundary

Business evidence is owned by a workspace. A tenant-stamped run also belongs to
a project in that same workspace, and database constraints keep its results
and baselines on the parent run's workspace/project. Users receive access through active workspace membership; user identity alone
does not grant tenant access. Public visibility is valid only for controlled
system workspaces, and a database constraint prevents personal/team workspaces
from becoming public.

RLS helper functions live in the non-exposed `app_private` schema. They are
`SECURITY DEFINER`, use an empty controlled search path and reference relations
with fully qualified names. RLS policies grant:

- anonymous read access only to the public system workspace and safe plan
  metadata;
- authenticated read access to public evidence and active member workspaces;
- self-only profile reads; and
- member-only, read-only subscription access.

Customer roles have no direct tenant-table INSERT/UPDATE/DELETE/TRUNCATE,
TRIGGER or REFERENCES privileges in Checkpoint 1A. Bootstrap writes pass through
a hardened, idempotent function. `alembic_version` is inaccessible to `anon`
and `authenticated`, has RLS enabled with no customer policy, and the privileged
migration role retains access. The account repair function explicitly removes
default execute access from `PUBLIC`, `anon` and `service_role`; only
`authenticated` may invoke it, and it derives identity exclusively from
`auth.uid()`.

The current production runtime remains a table owner with `BYPASSRLS` and is
therefore **not tenant-isolated yet**. This is an explicit Checkpoint 1A
limitation, not an application filtering guarantee. Checkpoint 1B must introduce
the separate non-owner `NOINHERIT`/`NOBYPASSRLS` runtime role and transaction-
local authenticated/JWT context. The migration/backup owner stays separate.

Until that transition, existing FastAPI endpoints still use the owner connection
and may expose legacy public and external-agent (including AJOOP) run history.
Real customer
signup/data ingestion must not be enabled. Supabase email signup and anonymous
sign-in remain disabled until the authenticated product flow is deliberately
released.

User deletion may remove its profile or membership, but must not cascade into
workspace projects, runs, results or baselines. Product evidence uses future
archive/retention workflows rather than customer-facing hard deletion.

The 0005 `SECURITY DEFINER` functions are owned by the migration role. Repair
reads `auth.users`, which has RLS enabled in production, so that owner must keep
`BYPASSRLS` (production `postgres` has it). Checkpoint 1B must not transfer
these functions to the non-owner, `NOBYPASSRLS` runtime role.

The best-effort signup trigger reports only the failure SQLSTATE and leaves the
Auth insertion intact. Repair fills only missing bootstrap rows: it never
reactivates or promotes an existing membership and never replaces a
subscription that has ended. Operations can run this privileged, aggregate
health check without returning profile metadata or payload contents. It counts
accounts whose bootstrap never completed; a membership that exists but is not
active, or a subscription that has ended, is not a bootstrap gap:

```sql
SELECT count(DISTINCT auth_user.id) AS accounts_needing_bootstrap_repair
FROM auth.users AS auth_user
LEFT JOIN public.profiles AS profile ON profile.id = auth_user.id
LEFT JOIN public.workspaces AS workspace
  ON workspace.personal_owner_id = auth_user.id
 AND workspace.kind = 'personal'
 AND workspace.visibility = 'private'
LEFT JOIN public.workspace_members AS member
  ON member.workspace_id = workspace.id
 AND member.user_id = auth_user.id
LEFT JOIN public.subscriptions AS subscription
  ON subscription.workspace_id = workspace.id
WHERE profile.id IS NULL
   OR workspace.id IS NULL
   OR member.user_id IS NULL
   OR subscription.id IS NULL;
```

Downgrading 0005 never reopens access. RLS stays enabled on `test_runs`,
`scenario_results`, `run_baselines` and `alembic_version`, and the broad
anon/authenticated grants that 0005 revoked are not restored. The downgrade is
also refused once customer tenancy state exists.

The PostgreSQL CI shim mirrors the `auth`/`public` grants captured in the
production pre-migration dump. Migrations run through a real LOGIN session as a
non-superuser migrator. Like production `postgres`, it has `BYPASSRLS` and holds
TRIGGER/REFERENCES on `auth.users` without inheriting that table's owner.
`auth.users` has RLS enabled, as in production, and its writes run as
`supabase_auth_admin`. Public-schema default ACLs grant ALL to `anon`,
`authenticated` and `service_role`. Role memberships are not part of that dump,
so the shim *assumes* the migrator may `SET ROLE` to the `auth.users` owner, and
separately proves that the downgrade fails closed when it cannot. None of this
is proof of real Supabase behavior. A throwaway Supabase rehearsal remains a
release gate before promotion to production/main. It must cover `auth.users`
ownership and role membership, trigger create/drop permissions, exact default
ACLs and GoTrue trigger interaction.

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
