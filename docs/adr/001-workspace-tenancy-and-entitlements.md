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
access. Projects belong to workspaces, and runs/baselines may be scoped to a
project. User identity is never the ownership root for business evidence.

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

Background execution will use a narrow trusted-writer exception: an
authenticated request authorizes and stamps a tenant-owned run, then a trusted
worker continues only by `run_id`. The worker must never trust a later
client-supplied workspace/project identifier.

## Consequences

Revision `0005` is an expand migration: ownership columns remain nullable so the
old pre-auth runtime can continue writing. Downgrade removes 0005-owned tables
and derived ownership columns without rewriting run snapshots, result payloads,
identities or timestamps.

Checkpoint 1A provides schema and policy readiness, not completed production
isolation. The current Railway connection uses the table-owning `postgres` role
with `BYPASSRLS`. Checkpoint 1B must introduce a separate non-owner,
`NOINHERIT`, `NOBYPASSRLS` runtime role and transaction-local authenticated/JWT
context. Migration/backup privilege and the eventual background system writer
remain separate responsibilities.
