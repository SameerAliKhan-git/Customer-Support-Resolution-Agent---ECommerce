# Continuation instructions for coding agents

Read [docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md) before planning or changing this repository. It is the source of truth for current implementation status, verified evidence, unresolved work, acceptance criteria and external decisions. Read [docs/PRODUCTION_READINESS_AUDIT.md](docs/PRODUCTION_READINESS_AUDIT.md) only as historical evidence; its original open-item tables include findings that have since been fixed.

## Current state

- The local synthetic MVP works and has current regression evidence.
- The system is not production-ready for real customer data or real funds.
- The first blocking engineering task is migration `0003` for `refund_proposals.supersedes_proposal_id`, its index and self-referential foreign key. Do not edit the already-applied `0002` migration.
- After fixing the migration, follow the P0 items in `docs/AGENT_HANDOFF.md` in order. Do not skip PostgreSQL, multi-process, real OIDC, payment-sandbox or ecommerce contract qualification.

## Rules that must remain true

- Every refund requires a stored reviewer approval bound to the exact immutable proposal.
- Customer identity comes from authentication, and order ownership is checked in service code.
- Eligibility and amounts are enforced by deterministic application code at proposal time and again before execution.
- Retry or reconciliation must reuse the original durable operation and provider idempotency key.
- Never report a refund as successful until the provider result and local business state are verified.
- Do not reset or delete databases to resolve state. Back up and migrate them.
- Do not use live payment credentials until the sandbox matrix and release controls pass.
- Keep chargebacks, fraud adjudication, complex partial returns and multi-store behavior outside scope unless the user explicitly expands it.

## Required workflow

1. Reproduce the relevant baseline before changing code.
2. Implement one bounded backlog item with its acceptance criteria.
3. Add meaningful tests for financial, authorization, recovery or integration behavior.
4. Run the affected checks plus migration drift checks when models or migrations change.
5. Update `docs/AGENT_HANDOFF.md` with dated evidence and move an item out of the backlog only after its acceptance criteria pass.
6. State which evidence is local, synthetic, sandbox, staging or production. Never present one category as another.

The Windows `.venv` checked during the 24 October 2026 audit was broken because its base Python installation was missing. Recreate it or use the existing project container. Exact commands and evidence boundaries are in [docs/VALIDATION.md](docs/VALIDATION.md).
