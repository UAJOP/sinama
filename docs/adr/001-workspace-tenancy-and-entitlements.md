# ADR 001: Workspace tenancy and entitlement foundation

- Status: Accepted
- Date: 2026-09-28
- Decision scope: Checkpoint 1A database/security foundation

## Context

The original SINAMA MVP stored global run history behind one trusted PostgreSQL
connection. Multi-user SaaS operation needs a durable tenant boundary without
changing evaluator, regression, readiness or current runtime behavior during
the expand phase.

## Decision

Workspace is the ownership root for customer and system business data. Supabase
Auth identifies a user; an active workspace membership authorizes tenant read
access. Projects belong to workspaces, and every tenant-stamped run/baseline
belongs to one project in its workspace. User identity is never the ownership
root for business evidence.
Resource primary keys are opaque UUIDs. `system_key` and `personal_owner_id`
are explicit unique business anchors, so resource identity never encodes an
Auth user identifier.

Subscriptions belong to workspaces. Stable plan codes are separate from
marketing display names, and JSONB plan-entitlement records form the future
data-driven capability layer. Product code must consume entitlements rather
than branch on a plan code. Usage measurement remains independent from billing
and subscription policy. Payment providers will be adapters and do not appear
in the core subscription schema.

RLS is responsible only for deciding which tenant's rows a principal may read.
Entitlements decide what an authorized workspace may do. Anonymous access is
limited to intentionally public system-workspace evidence and safe plan
metadata. Normal tenant principals do not receive direct subscription mutation
or customer-facing hard-delete privileges.

Two fixed system workspaces classify legacy data:

- `sinama-public-demo`: public `built_in_demo` evidence;
- `sinama-legacy-private`: private `external_http` evidence.

Each has an internal project for the migration. Unknown historical targets fail
closed. A personal bootstrap creates a profile, private personal workspace,
owner membership and active free subscription, but **no automatic project**.
Every step is idempotent and keyed by `auth.users.id`, never email. A best-effort
trigger and a no-argument `auth.uid()` repair path share the same implementation.
Repair creates a missing membership but never promotes or reactivates an
existing suspended/removed membership. It creates the initial Free subscription
only for a workspace that has never had one, and never replaces a subscription
that has ended.

Tenant-stamped runs require both a workspace and project. Composite foreign keys
bind a run's project to its workspace and bind results/baselines to the same
parent ownership tuple. Old-runtime rows may temporarily remain `NULL`/`NULL`;
the later contract migration must backfill those stragglers before `NOT NULL`.
Baseline identity is still pack-scoped and must become project-scoped in 1B/1D.

Background execution will use a narrow trusted-writer exception: an
authenticated request authorizes and stamps a tenant-owned run, then a trusted
worker continues only by `run_id`. The worker must never trust a later
client-supplied workspace/project identifier.

## Consequences

Revision `0005` is an expand migration: ownership columns remain nullable so the
old pre-auth runtime can continue writing. Downgrade removes 0005-owned tables
and derived ownership columns without rewriting run snapshots, result payloads,
identities or timestamps, but fails closed after customer tenancy state exists.
It keeps RLS on the evidence tables and `alembic_version` and does not restore
the broad grants 0005 revoked. It drops the `auth.users` trigger directly when
permitted, or by `SET ROLE` to the table owner; otherwise it rolls back unchanged.

Checkpoint 1A provides schema and policy readiness, not completed production
isolation. The current Railway connection uses the table-owning `postgres` role
with `BYPASSRLS`. Checkpoint 1B must introduce a separate non-owner,
`NOINHERIT`, `NOBYPASSRLS` runtime role and transaction-local authenticated/JWT
context. Migration/backup privilege and the eventual background system writer
remain separate responsibilities.

Until 1B, legacy FastAPI endpoints can still expose historical external-agent
(AJOOP) data because the runtime owner bypasses RLS. Real signups, anonymous
sign-ins and customer data ingestion stay disabled. Entitlement resolution must
treat a workspace without a current subscription as Free: the floor, never a
paid capability.

The local PostgreSQL ACL/auth shim is representative only. A real throwaway
Supabase rehearsal of Auth ownership, trigger DDL, default ACLs and GoTrue
interaction is required before production promotion.
