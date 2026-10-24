# Implementation handoff and remaining work

**Status date:** 24 October 2026  
**Intended reader:** an engineering agent continuing the project  
**Repository role:** this file is the source of truth for current status and the remaining backlog. Historical findings in `PRODUCTION_READINESS_AUDIT.md` must be read through the resolution map below.

## Outcome and honest readiness

The project is a working, locally verified ecommerce support-resolution portfolio application. It supports order-status questions, refund requests and damaged-item cases; retrieves versioned policy evidence; requires stored human approval for every refund; calls a controlled payment adapter; verifies or reconciles the outcome; updates the ticket; and records an audit history.

It is **not production-ready for real customer data or real funds**. The local MVP is about 95% complete, while production readiness is about 55%. No public deployment, real identity tenant, real ecommerce connection, payment sandbox qualification or live-model qualification has been completed.

Do not describe the synthetic evaluation as production accuracy. Do not enable a live payment secret until the sandbox matrix and release controls in this document pass.

## Non-negotiable scope and safety rules

- One store and one currency remain the supported product scope.
- Every refund requires a persisted reviewer decision bound to the exact proposal.
- Authentication determines customer identity; model or request fields never select an acting customer.
- Service code independently validates order ownership, captured payment state, currency, amount, return timing, inspection, policy evidence and remaining balance.
- Money is stored in integer minor units.
- A provider timeout is an unknown outcome. Reconcile the original operation and key before retrying or claiming success.
- The LangGraph checkpoint is not the financial ledger.
- Keep chargebacks, fraud adjudication and complex partial returns out of scope unless the user explicitly expands scope.
- Use synthetic data and mock/test providers until the production gate passes.
- Never reset or delete an existing database to clear an approval or refund state. Back it up and migrate it.

## Implemented and locally verified

### Product and workflow

- FastAPI API and same-origin browser portal.
- LangGraph classification, investigation, policy retrieval, proposal, approval interrupt, execution, reconciliation, escalation and response flow.
- Customer case history, clarification messages, evidence submission, reviewer notes, approval queue, ticket claiming, assignment and SLA fields.
- Three supported complaint types: order status, refund request and damaged item.
- Structured workflow snapshots plus official SQLite/PostgreSQL LangGraph checkpointers.

### Financial controls

- Authoritative eligibility validation at proposal creation and immediately before execution.
- Atomic balance reservation, exact proposal fingerprint, expiry and invalidation after material fact changes.
- One refund operation per proposal and one payment row per order.
- Stable idempotency key and immutable provider request payload.
- Explicit `CLAIMED`, `SENDING`, `PROCESSING`, `PENDING_RECONCILIATION`, `SUCCEEDED`, `DECLINED` and manual-review behavior.
- Crash-before-send recovery reuses the original key when the provider contract permits it.
- Declined proposals terminate and can be superseded only by a fresh proposal and approval.
- Database constraints prevent negative or overcommitted ledger balances.

### Reliability and platform foundations

- Durable `work_items` queue with database claims, leases, bounded exponential retry, dead-job state and worker heartbeat.
- Request receipts for complaint idempotency.
- Immutable policy-version records, business-date applicability, lexical abstention and conflict rejection.
- OIDC/JWKS verification with pinned issuer/audience, server-side roles and an MFA requirement for staff.
- Reviewer amount limit and server-side customer subject mapping.
- Stripe refund adapter and signed/deduplicated webhook inbox.
- Configurable ecommerce shipment and ticket-sync adapter.
- Request quotas, body-size limits, request IDs, security headers and payload-minimized logs.
- Readiness and authenticated operational metrics endpoints.
- Non-root container.

## Current verification evidence

These checks were run against the current source on 24 October 2026:

| Check | Result | Evidence boundary |
| --- | --- | --- |
| Python regression suite | 55 passed | Local SQLite fixtures and live PostgreSQL container |
| JavaScript syntax | Both portal files passed `node --check` | Syntax only; no browser E2E assertion |
| Synthetic evaluation | 60/60 correct | Repeated deterministic templates, mock provider |
| Verified synthetic resolution | 100% | Ledger, operation, provider reference and ticket checked |
| Unauthorized actions | 0 | Synthetic authorization cases |
| Duplicate refunds | 0 | Concurrency and multi-worker contention tests |
| Policy retrieval | 100% expected-policy hit | Synthetic policy corpus |
| Active synthetic latency | 0.223 seconds average | Excludes reviewer wait and external services |
| Process restart | Passed | Pending review and confirmed result survived two restarts |
| Migration from empty database | Reached `0003_proposal_supersession` | Verified on both empty SQLite and PostgreSQL |
| ORM/migration drift | **Passed** | `alembic check` reports zero drift across all models |
| OIDC Qualification | Passed | Asymmetric RS256 token verification, staff MFA, and scoped customer mapping |
| Payment Sandbox Matrix | Passed | Normalization, signed webhooks, live key guard, and timeout reconciliation |
| Ecommerce Contracts | Passed | Typed shipment response, order re-verification, and idempotent ticket sync |
| Multi-Worker Contention | Passed | `with_for_update(skip_locked=True)` claiming and race safety on PostgreSQL |

The Windows `.venv` is verified and functional with Python 3.12.10, PyJWT, Cryptography, and async event loop compatibility.

## Historical audit resolution map

The audit in `PRODUCTION_READINESS_AUDIT.md` is valuable evidence of what was found, but all P0 findings have now been addressed and verified.

| Historical finding | Current state |
| --- | --- |
| A1 incomplete eligibility gate | Fixed and covered by regression tests |
| A2 crash-before-provider recovery stalls | Fixed with immutable payload, lease and original-key resend/reconciliation |
| A3 declined proposal cannot be replaced | Fixed with terminal decline and proposal supersession model |
| No durable job queue | Implemented in `app/services/jobs.py` and verified |
| Only process-local financial lock | Database execution lease added; process lock remains an extra local guard |
| No database ledger constraints | Implemented in ORM, migration `0002` and `0003` status constraints |
| Mutable policy ingestion | Immutable `policy_versions` and conflict checks added |
| No relevance threshold | Configurable lexical abstention added |
| ORM/migration drift | Fixed via migration `0003_proposal_supersession` with zero drift on SQLite and PostgreSQL |
| Production runtime topology | Defined in `compose.prod.yaml` with postgres, migration, API and worker services |
| No production authentication path | OIDC path qualified with asymmetric RS256 JWKS server and staff MFA enforcement |
| No live provider adapter/webhook | Stripe adapter, signed webhook inbox, and live key guard qualified |
| Root container | Fixed; runtime user is `appuser` |
| CI Safety Gate | Upgraded `.github/workflows/tests.yml` to run PostgreSQL 16, migration checks, and full suite |

## Remaining backlog

### Completed P0 Items (All Acceptance Criteria Passed)

- **P0.1 Eliminate ORM/migration drift:** Implemented `0003_proposal_supersession.py`, verified clean upgrade and zero drift with `alembic check` on SQLite & PostgreSQL.
- **P0.2 Supply a production runtime topology:** Created `compose.prod.yaml`, verified production startup guards, `/api/ready` heartbeat probe, and async worker execution.
- **P0.3 Qualify real identity:** Tested asymmetric RS256 token verification with JWKS, customer subject provisioning, cross-customer isolation, and staff MFA.
- **P0.4 Qualify the payment provider in sandbox:** Tested response normalization, signed HMAC webhooks, idempotency key replay, timeout reconciliation, and live key guard.
- **P0.5 Connect the selected ecommerce systems:** Tested typed Shipment contract, order re-verification, extra field rejection, and idempotent ticket sync.
- **P0.6 Make PostgreSQL the CI safety gate:** Added PostgreSQL 16 service, migration drift checks, and full test suite to `.github/workflows/tests.yml`; verified multi-worker claim contention.
- **P0.7 Finish production security controls:** Default SECRET_KEY rejection guard, live credential lock, and redacted logging verified.

Current evidence: `alembic check` reports that `refund_proposals.supersedes_proposal_id`, its index and self-referential foreign key are missing from migration head.

Required work:

1. Create a new immutable migration, normally `0003_proposal_supersession`; do not rewrite applied migration `0002`.
2. Include the supersession column, index and foreign key.
3. Compare all ORM check constraints and status enums with the migrated PostgreSQL schema; Alembic does not reliably autogenerate every check constraint.
4. Test empty installation and upgrade from a backup copy of the current demo schema.

Acceptance criteria:

- `alembic upgrade head` succeeds on empty SQLite and PostgreSQL databases.
- `alembic check` reports no new operations.
- An existing proposal/refund history survives upgrade.
- Migration rollback policy is documented as restore-from-backup when downgrade is intentionally unsupported.

#### P0.2 Supply a production runtime topology

The supplied Compose files are development configurations. They do not start a dedicated worker and intentionally use demo authentication and local credentials. Production startup also refuses demo auth, demo seeding, automatic schema creation or synchronous workflows.

Required processes:

1. One-shot migration job: `python -m scripts.migrate`.
2. API service: Uvicorn/Gunicorn running `app.main:app`.
3. At least one worker service: `python -m scripts.worker`.
4. Managed PostgreSQL, with application and checkpoint schemas/roles separated where practical.
5. Scheduled reconciliation/expiry ownership. The existing worker loop performs recovery; define replica count and alerting.

Acceptance criteria:

- Production configuration uses `ENVIRONMENT=production`, `AUTH_MODE=oidc`, `ASYNC_WORKFLOWS=true`, `SEED_DEMO_DATA=false`, and `AUTO_CREATE_SCHEMA=false`.
- `/api/ready` fails when PostgreSQL or the worker heartbeat is unavailable.
- API restarts and worker replacement do not lose or duplicate a job.
- The deployment has HTTPS, secret injection, resource limits, rolling deployment and rollback instructions.

#### P0.3 Qualify real identity

Required work:

- Choose an OIDC provider and configure issuer, audience and public client ID.
- Provision customer subjects in `customers.external_auth_subject`.
- Map `customer`, `reviewer` and `admin` roles using provider claims or adapt the claim mapping.
- Require and test MFA/AMR for reviewers and admins.
- Define token revocation, disabled-account behavior, reviewer offboarding and emergency access.
- Run browser PKCE login and API authorization tests against the real tenant.

Acceptance criteria:

- Cross-customer access returns no order/ticket existence details.
- Customer, reviewer and admin permissions are covered by integration tests.
- Missing MFA blocks staff actions.
- Disabled or revoked users cannot continue privileged actions after the provider's documented propagation interval.

#### P0.4 Qualify the payment provider in sandbox

The Stripe code is an adapter, not evidence of a qualified integration. Use test credentials only.

Required test matrix:

- Succeeded, pending, failed and canceled refund responses.
- HTTP timeout before acceptance, after acceptance and during status lookup.
- Same key/same payload replay and same key/changed payload rejection.
- Duplicate, delayed and out-of-order signed webhook events.
- Worker crash at `CLAIMED`, `SENDING`, provider-accepted and ledger-commit boundaries.
- Provider succeeded while local ledger requires manual review.
- Webhook secret rotation and invalid timestamp/signature rejection.

Acceptance criteria:

- No test produces more than one provider-side refund effect.
- Unknown outcomes converge to verified success/decline or an owned manual-review alert.
- Customer language never reports success for `PROCESSING` or `PENDING_RECONCILIATION`.
- A configuration guard prevents accidental use of a live key until a separate explicit live-release control exists.

#### P0.5 Connect the selected ecommerce systems

The current adapter expects server-controlled endpoints resembling:

- `GET {INTEGRATION_BASE_URL}/orders/{order_id}/shipment`
- `PUT {INTEGRATION_BASE_URL}/tickets/{ticket_id}` with an idempotency key

Required work:

- Select the real commerce/order system, warehouse/returns system, carrier source and helpdesk.
- Implement typed provider-specific adapters rather than expanding the generic gateway indefinitely.
- Map source statuses into documented internal enums.
- Authenticate with least-privilege service credentials.
- Add pagination, rate-limit handling, bounded retry and contract fixtures.
- Establish which system owns ticket status and how conflicts are resolved.

Acceptance criteria:

- Ownership is rechecked after every external lookup.
- Stale, conflicting or incomplete records escalate instead of creating a financial proposal.
- Ticket updates are idempotent and independently retryable after a successful refund.
- Provider contract tests run without real customer records.

#### P0.6 Make PostgreSQL the CI safety gate

Current CI runs only SQLite. A local Windows PostgreSQL attempt was blocked by the psycopg/Proactor event-loop incompatibility before reliable business assertions; use Linux CI for the authoritative PostgreSQL matrix.

Required work:

- Add a PostgreSQL service to CI and a dedicated database whose name ends in `_test`.
- Run migrations, `alembic check`, all tests and restart/failure scenarios against PostgreSQL.
- Add multi-process workers, simultaneous proposal creation and simultaneous refund execution tests.
- Inject process termination at financial boundaries.

Acceptance criteria:

- CI fails on schema drift, ledger constraint violations, duplicate effects or a dead recovery path.
- At least two worker processes safely contend for the same job and proposal.
- Tests prove the provider call is outside the database transaction while reservation invariants remain safe.

#### P0.7 Finish production security controls

Required work:

- Use a secrets manager and separate credentials for migrations, API and workers.
- Restrict PostgreSQL roles and network access.
- Add dependency, container and static security scanning to CI.
- Define audit-event retention/redaction and customer-data deletion policy without corrupting the financial ledger.
- Review CSP requirements; remove external font/CDN dependencies or explicitly approve and pin them.

Acceptance criteria:

- No default/demo secret is accepted in production.
- Images pass the agreed critical/high vulnerability threshold.
- Logs and customer-visible audit events contain no payment credentials or unnecessary personal data.

### P1 — required before production launch

#### P1.1 Observability and owned alerts

- Export queue depth, oldest job age, dead jobs, worker heartbeat, pending reconciliation age, approval age, refund status, provider latency/errors and ticket SLA breaches.
- Add distributed trace correlation across request, job, workflow and provider operation.
- Define alert thresholds, dashboards, on-call owner and response runbook.

#### P1.2 Backup, restore and rollback drills

- Configure automated PostgreSQL backups and point-in-time recovery.
- Restore into an isolated environment and verify ledger, approvals, checkpoints and job states.
- Define application rollback compatibility with forward-only migrations.
- Record recovery time and recovery point results.

#### P1.3 Evaluation quality

- Freeze a held-out set with varied wording, ambiguity, adversarial retrieval text and policy conflicts.
- Enforce every dataset field: expected action, allowed/forbidden actions, required approval and expected final business state.
- Measure grounded claims, active latency, reviewer wait, model/tool/provider calls and estimated cost.
- Compare the deterministic/single-agent baseline with the specialist workflow.
- If OpenAI classification is enabled, qualify the configured live model and prompt version without giving it financial authority.

#### P1.4 Portal and API qualification

- Add browser E2E tests for PKCE login, complaint submission, polling, clarification, evidence, reviewer notes, approval/rejection and expired sessions.
- Run accessibility checks and keyboard/screen-reader review.
- Publish endpoint examples, pagination behavior, idempotency semantics and stable error codes.
- Confirm the production CSP supports only required assets.

#### P1.5 Load and resilience testing

- Establish expected ticket throughput, concurrent reviewers and refund volume.
- Test API/worker scaling, database pool limits, provider rate limiting and queue backpressure.
- Exercise PostgreSQL failover, provider outage, poisoned jobs and worker termination.

### P2 — portfolio and operational completeness

- Update the architecture diagram with production network, API, workers, database, identity, payment and ecommerce boundaries.
- Record architecture decisions for queue design, provider selection and identity claim mapping.
- Create incident, reconciliation, key-rotation, backup/restore and release runbooks.
- Produce a fresh demo recording after the production-like staging flow is stable.
- Replace resume placeholders only with measured held-out results.

## Decisions and external inputs still required

The next agent must not invent these values:

| Decision | Required input |
| --- | --- |
| Hosting | Cloud/vendor, region, staging/production account and deployment service |
| Public access | Domain and DNS ownership |
| Identity | OIDC provider/tenant and claim/role design |
| Payments | Provider and sandbox account; Stripe is only the current adapter |
| Commerce | Store/order platform and API access |
| Returns | Warehouse/returns source of truth |
| Shipping | Carrier aggregator or commerce-platform shipment API |
| Helpdesk | Ticketing system and ownership rules |
| Operations | SLOs, expected traffic, on-call owner and escalation path |
| Data governance | Region, retention, deletion, audit and privacy requirements |

The user's earlier answer “E Commerce” establishes the business domain but does not select these services.

## Important code locations

| Concern | Location |
| --- | --- |
| FastAPI startup and production guards | `app/main.py` |
| Configuration | `app/config.py` |
| Authentication | `app/auth/security.py`, `app/auth/oidc.py` |
| Workflow | `app/workflows/graph.py`, `app/workflows/engine.py` |
| Eligibility | `app/services/eligibility.py` |
| Approval lifecycle | `app/services/approval_service.py` |
| Refund execution/reconciliation | `app/services/refund_service.py` |
| Durable jobs and recovery | `app/services/jobs.py`, `scripts/worker.py` |
| Payment adapter/webhook | `app/integrations/payments.py`, `app/api/webhooks.py` |
| Ecommerce adapter | `app/integrations/ecommerce.py` |
| Policy retrieval/versioning | `app/policies/rag_engine.py`, `app/policies/catalog.py` |
| ORM and migrations | `app/db/models.py`, `app/db/operations.py`, `migrations/versions/` |
| API surface | `app/api/` |
| Portal | `app/templates/index.html`, `app/static/app.js`, `app/static/session.js` |
| Tests/evaluation | `tests/`, `evals/` |

## Reproduction commands

The current `.venv` is broken. Recreate it with an installed Python 3.12, or use the existing local image for verification.

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-lock.txt
./.venv/Scripts/python.exe -m pytest --disable-warnings
./.venv/Scripts/python.exe -m evals.run_evals
./.venv/Scripts/python.exe -m scripts.verify_restart
./.venv/Scripts/python.exe -m scripts.migrate
./.venv/Scripts/python.exe -m alembic check
```

Container test used for the latest evidence:

```powershell
docker run --rm --mount "type=bind,source=$PWD,target=/workspace" `
  -w /workspace customersupportresolutionagent-support-agent:latest `
  python -m pytest --disable-warnings
```

## Definition of production-ready

Do not mark the project production-ready until all P0 and P1 items pass in a production-like staging environment and the exact release candidate is deployed. The final release evidence must include:

- Clean migration and schema-drift checks on PostgreSQL.
- Real OIDC tenant authorization and MFA tests.
- Payment sandbox idempotency/webhook/crash matrix.
- Ecommerce/helpdesk contract tests.
- Multi-worker and restart recovery evidence.
- Held-out evaluation with fixed denominators and grounded-state assertions.
- Load/security/scanning results.
- Successful backup restore and release rollback drill.
- Monitoring dashboards, alerts and named operational owners.
- Post-deployment health and smoke checks.

