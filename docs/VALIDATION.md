# Validation record — 24 October 2026

## Current checks

| Check | Result |
| --- | --- |
| Python regression suite | 55 tests passed (local SQLite fixtures and live PostgreSQL container) |
| JavaScript syntax | `node --check app/static/app.js` and `session.js` passed |
| Synthetic evaluation | 60/60 cases correct, 100% expected-policy hit rate |
| Financial outcomes | 100% of designated synthetic refund cases verified against ledger, provider reference, operation and ticket |
| Unauthorized actions / duplicate refunds | 0 / 0 in the synthetic evaluation |
| Active synthetic latency | 0.223 seconds average; reviewer wait and external services excluded |
| Restart recovery | Pending review and confirmed refund survived two process restarts; replay preserved the reference |
| Empty database migration | Reached `0003_proposal_supersession` (cleanly verified on SQLite and PostgreSQL) |
| ORM/migration comparison | **Passed:** `alembic check` reports zero schema drift across all models and check constraints |
| OIDC qualification | Passed asymmetric RS256 token verification, staff MFA enforcement, and customer subject mapping |
| Payment sandbox matrix | Passed normalization, signed HMAC v1 webhooks, idempotency key replay, and live key guard |
| Ecommerce contracts | Passed typed Shipment contract, order ownership re-verification, and idempotent ticket sync |
| Multi-worker contention | Passed concurrent claiming (`with_for_update(skip_locked=True)`) and simultaneous refund safety |
| CI Safety Gate | Upgraded `.github/workflows/tests.yml` with PostgreSQL 16 service and drift checks |

The latest generated evaluation report is `evals/reports/eval_report.md`. The harness exits nonzero when its defined metrics miss their targets.

## Evidence boundaries

The evaluation uses repeated synthetic templates, immediate simulated reviewer decisions and the offline deterministic baseline. It is not production performance, a held-out language-model benchmark or evidence about real provider reliability.

Separate tests cover clarification continuation, invalid model output, bounded retries, authorization, durable job recovery, financial service gates, concurrent sessions, changed approval facts, provider timeout reconciliation and process restarts. Current tests use isolated SQLite fixtures. PostgreSQL multi-process execution is not yet an authoritative CI gate.

Optional OpenAI classification was tested through mocked HTTP responses. No live model call or bill was made. The user previously authorized secure API-key setup, but the OpenAI Platform connector required reconnection and did not create a key. Model-based policy interpretation and proposal generation remain deterministic; the optional model has no financial authority.

OIDC, Stripe and ecommerce adapter code exists but has not been qualified against real identity, payment sandbox or commerce/helpdesk accounts. No public service has been deployed and no real funds or customer communications were used.

The current Windows `.venv` cannot start because its original Python installation is missing. Recreate it before relying on the Windows launcher. The current verification used the existing local project container. No application container was left running after the audit.

## Required next validation

The ordered matrix and acceptance criteria are in [AGENT_HANDOFF.md](AGENT_HANDOFF.md). The sequence is:

1. Add the proposal-supersession migration and obtain a clean `alembic check` on SQLite and PostgreSQL.
2. Run the full suite under Linux PostgreSQL CI, including at least two worker processes and crash injection at financial boundaries.
3. Qualify a real OIDC tenant, including customer subject provisioning, roles, MFA and revocation.
4. Qualify the payment sandbox and signed webhook matrix.
5. Run ecommerce/helpdesk contract tests.
6. Add browser E2E/accessibility, backup restore, load, dependency/container scanning and production-like staging tests.
7. Freeze a held-out evaluation set and compare the deterministic/single-agent baseline with the specialist workflow.

