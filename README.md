# Customer Support Resolution Agent - ECommerce

A runnable support resolution application with a FastAPI dashboard, LangGraph specialist workflow, local policy retrieval, human refund review, simulated payment execution, reconciliation, and a database audit trail.

> **Continuation handoff:** Integrated coding agents should begin with [AGENTS.md](AGENTS.md), then read [Implementation handoff and remaining work](docs/AGENT_HANDOFF.md). The handoff is the current source of truth for completed work, known schema drift, production blockers, acceptance criteria and required external decisions. Older audit documents preserve historical findings and are not the current backlog by themselves.

## Run on Windows

Python 3.11+ is required (validated with Python 3.12).

```powershell
./scripts/start.ps1
```

Open http://127.0.0.1:8000. API documentation is at http://127.0.0.1:8000/docs.

The launcher installs dependencies, creates SQLite tables, seeds synthetic customers/orders, ingests five policy documents, and starts one local worker. No API keys or paid services are required. Existing customer and payment records are preserved on restart.

The local `.env` created for this walkthrough points to `demo_support.db` and `demo_checkpoints.db`. The pre-existing `support_agent.db` is preserved. `.env.example` documents portable defaults for a new checkout.

Manual setup:

```powershell
py -3 -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe -m scripts.serve
```

`requirements-lock.txt` records the validated environment. Use `pip install -r requirements-lock.txt` to reproduce it. `requirements.txt` specifies compatible minimums and allows updates.

## Try the application

1. Select the successful refund scenario (`cust_1001`, `ord_1001`) and submit. The system verifies the order, payment and warehouse inspection, retrieves policy citations and saves a refund proposal. Money is not moved.
2. Approve or reject in the reviewer panel. Approval executes the mock gateway, verifies the result and resolves the ticket. Rejection releases the reservation and records a customer response.
3. Try the in-transit return, order tracking, high-value damaged goods, or missing-order examples.
4. Select the timeout scenario (`cust_1004`, `ord_1008`). The mock provider records success and simulates a lost response; the workflow reconciles the original operation before reporting success.

Refund proposals reserve available balance. Repeat submissions cannot reserve the same amount twice. Execution uses one durable operation per proposal, including when a caller changes the idempotency key. Workflow snapshots and mock provider records survive restart.

## What is implemented

- Complaint classification, scoped investigation, policy retrieval and resolution proposal nodes.
- Read tools for customer-owned orders, returns and payments; write tools for proposals, approved refunds and ticket updates.
- A reviewer queue, immutable decisions, expiry checks and recorded reviewer identity from authentication.
- Persisted workflow status, approval resume, ticket lifecycle, and linked audit events.
- Refund reservation, duplicate execution protection, gateway timeout simulation and reconciliation.
- A database-backed job queue with claims, leases, retry limits, recovery scanning and worker heartbeat.
- OIDC/JWKS authentication support, staff MFA checks, reviewer limits and customer subject mapping.
- Stripe adapter and signed webhook inbox, plus a configurable ecommerce shipment/ticket adapter. These are unqualified integration foundations, not live connections.
- A browser dashboard showing evidence, citations, history, clarification, approval controls and verified results.
- Request idempotency, quotas, request IDs, security headers, readiness and operational metrics.
- Isolated automated tests, a 60-case synthetic evaluation, Windows launcher, container configuration and CI workflow.

## Implementation boundaries

This is a local portfolio implementation. The default specialist workflow uses deterministic Python rules; retrieval uses hashed text vectors plus lexical scoring. An optional OpenAI structured classifier is implemented behind explicit `LLM_PROVIDER=openai`; it is schema-validated, has two bounded attempts, and exposes no financial tools. Live provider testing requires separately authorized credentials and has not been performed. Eligibility and execution always remain ordinary code. Payments and carrier data are simulated; no real funds move and no customer messages are sent externally.

Default authentication is explicitly a **development demo**: bearer customer IDs and reviewer IDs switch personas. It is intended for localhost. The optional signed-token mode is a test facility. An OIDC path and browser PKCE flow are implemented, including issuer/audience validation and staff MFA checks, but they have not been qualified against a real identity tenant or provisioning process.

The default demo runs workflows synchronously. Setting `ASYNC_WORKFLOWS=true` uses the durable `work_items` queue and requires `python -m scripts.worker`. Database leases and row locking are implemented, but multi-process PostgreSQL qualification is still a release gate. The supplied Compose files are development configurations and do not constitute a production topology. Audit events are append-only through application behavior, not tamper-proof against database administrators.

The supplied Notion brief was read through the browser after connector/public-fetch failures. The implementation follows its synthetic-data scope, three complaint types, controlled tools, approval gates, durable checkpoints, PostgreSQL storage and evaluation requirements. See [requirements and decisions](docs/REQUIREMENTS.md) for the coverage and limitations.

## Verify

See [validation evidence](docs/VALIDATION.md), [captured demo walkthrough](docs/DEMO.md), and the [current handoff backlog](docs/AGENT_HANDOFF.md).

```powershell
./.venv/Scripts/python.exe -m pytest --disable-warnings
./.venv/Scripts/python.exe -m evals.run_evals
./.venv/Scripts/python.exe -m scripts.verify_restart
```

Tests and evaluations create private temporary databases and never reset `support_agent.db`. Evaluation reports are written to `evals/reports/`. Cases are synthetic templates; reported accuracy is not a measure of real-world language understanding. The harness exits nonzero when a metric misses its target.

As of 24 October 2026, the current source passes 55 regression tests (across SQLite and live PostgreSQL container), the 60-case synthetic evaluation passes with 100% resolution accuracy, process restart recovery passes, and `alembic check` verifies zero schema drift following migration `0003_proposal_supersession`. OIDC authentication with asymmetric RS256 JWKS verification, staff MFA enforcement, Stripe response normalization, signed webhooks, live key guard, typed ecommerce shipment contracts, and multi-worker PostgreSQL claiming safety are all qualified with automated test suites.

## Containers

```powershell
docker compose up --build
```

Compose binds only to localhost and persists data in a named volume. For PostgreSQL, use `docker compose -p customer-support-resolution -f compose.postgres.yaml up --build -d` and open port 8001. PostgreSQL data persists in a named volume; local demo credentials are confined to this localhost setup. See [architecture](docs/ARCHITECTURE.md) and [operations](docs/OPERATIONS.md).
