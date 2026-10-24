# Operations

For the ordered implementation backlog, external decisions and release acceptance criteria, start with [AGENT_HANDOFF.md](AGENT_HANDOFF.md). This document describes current controls; it is not evidence that external integrations have been qualified.

## Configuration

Copy `.env.example` to `.env` for local development. Start from the repository root. `DATABASE_URL` and `SYNC_DATABASE_URL` must identify the same database. Run `python -m scripts.migrate` before a deployed release. Development may use automatic table creation and demo seeding; production deliberately refuses to start unless `AUTO_CREATE_SCHEMA=false` and `SEED_DEMO_DATA=false`.

Production also requires PostgreSQL, OIDC and `ASYNC_WORKFLOWS=true`. Start a dedicated worker using:

```powershell
python -m scripts.worker
```

The API and worker must share the application database and checkpoint database. `/api/ready` checks database access and, when asynchronous workflows are enabled, a fresh worker heartbeat.

Bind to `127.0.0.1` for the demo. To change the port, pass `--port` to uvicorn. Docker Compose also binds its published port to localhost. Database-backed leases are intended to support replacement and concurrent workers, but multiple processes against PostgreSQL have not yet passed the release qualification described in [AGENT_HANDOFF.md](AGENT_HANDOFF.md).

## Authentication

Set `AUTH_MODE=signed` and configure a strong private `SECRET_KEY` in the environment. Default development keys fail closed in signed mode. Generate credentials only in a trusted provisioning process using `app.auth.security.issue_token(user_id, role, name, expires_in=3600)` and distribute them through an appropriate secret channel. Do not commit tokens or keys. Roles are `customer`, `reviewer`, and `admin`.

The demo dashboard deliberately uses development personas. Signed credentials are retained only as a test facility.

For the production path set `AUTH_MODE=oidc`, `OIDC_ISSUER`, `OIDC_AUDIENCE` and `OIDC_CLIENT_ID`. The API fetches OIDC discovery/JWKS, accepts only `RS256`, validates issuer/audience/expiry/issued-at/subject, maps `customer`, `reviewer` and `admin` roles, and requires an MFA-style `amr` value for staff when `OIDC_REQUIRE_STAFF_MFA=true`. Customer subjects must be provisioned in `customers.external_auth_subject`.

This code has not been qualified against a real identity tenant. Token revocation, role-claim mapping, staff offboarding and emergency access remain deployment work.

## Durable jobs and recovery

- `POST /api/complaints` accepts `Idempotency-Key`. With async workflows enabled it returns `202` and a `Location` header.
- Jobs move through `READY`, `RUNNING`, `DONE` and `DEAD`. A lease allows a replacement worker to reclaim abandoned work.
- A worker retries at most eight times with bounded exponential delay.
- The worker expires approvals, requeues persisted decisions after crashes and publishes `worker-heartbeat`.
- Inspect queue/refund/escalation counts through reviewer-only `GET /api/metrics`.
- A production deployment must alert on dead jobs, old ready jobs, stale heartbeat and old pending reconciliations; the repository does not provide an alerting backend.

## Review and recovery

- Review `GET /api/approvals/pending` with a reviewer credential before submitting decisions.
- Repeated decisions return an error. To retry a recorded decision after a process interruption, call the reviewer-only workflow resume endpoint. The request body must satisfy the API schema, but execution loads the actual decision and identity from the database.
- For a timeout, execution queries the original provider key. Do not invent another payment key to bypass a pending operation.
- The mock gateway persists transactions across restarts. Its in-memory `reset()` helper clears only its cache and forced behavior; it does not erase the durable provider ledger.
- Ticket audit history includes events on related proposals, approvals and refund operations. It is not an immutable external audit system.

For Stripe, set `PAYMENT_PROVIDER=stripe` with test-mode `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`. The webhook endpoint is `/api/integrations/stripe/webhook`; it verifies the raw body, timestamp and `v1` HMAC, deduplicates event IDs and stores a minimized inbox record. The adapter has not passed a Stripe sandbox failure matrix, and there is not yet a guard that distinguishes test from live credentials. Do not configure a live key.

For the generic ecommerce bridge, set `INTEGRATION_BASE_URL` and `INTEGRATION_API_TOKEN`. Current contracts are `GET /orders/{order_id}/shipment` and idempotent `PUT /tickets/{ticket_id}`. Provider-specific mappings, rate-limit handling and contract qualification remain P0 work.

## Backup and schema changes

Stop the service before copying SQLite database files. Preserve the entire database, including workflow and mock provider tables. Application-level financial reservations cannot be reconstructed from ticket text alone. Never delete the database just to clear an approval queue containing meaningful records.

Two Alembic revisions are included. Before changing model schemas on an existing installation, write and test a new migration on a backup; never edit an applied revision. `scripts.migrate` backs up recognized SQLite databases before adoption/upgrade.

Current schema warning: `alembic check` detects that `refund_proposals.supersedes_proposal_id`, its index and foreign key are missing from migration head. Create migration `0003` before any staging deployment. PostgreSQL backup/restore and rollback drills are still outstanding.

## Verification

Run pytest, `alembic check`, restart verification and the evaluation from the README. The 60-case evaluation uses repeated synthetic templates and simulated reviewer decisions. It is a regression baseline rather than a production quality or safety certification. Current measured results live in `evals/reports/eval_report.md`.

Current evidence is 33 passing containerized tests, 60/60 synthetic cases and a passing two-restart verification. Current CI runs SQLite only. PostgreSQL CI, multi-process contention, browser E2E, hosted CI evidence and production-like deployment are outstanding. No public service has been deployed.

## Models and embeddings

`LLM_PROVIDER=mock` is the default offline baseline. `LLM_PROVIDER=openai` enables the optional classifier using `LLM_MODEL` (default `gpt-4o-mini`). Credentials must be provisioned through an authorized secure setup flow; no key is shipped. Requests use the Responses API with strict JSON-schema output and `store=false`. Two attempts are allowed, then the workflow escalates. The optional model stage cannot set customer identity, approve refunds or execute financial tools. Live-model behavior and cost have not been measured.

Local retrieval uses 128-dimensional hash projections and lexical scores. It filters future-effective documents and selects the latest available version for each document ID. No external embedding service or vector database is required.

## Rate limits and request controls

- API requests other than health/readiness use a shared database-backed per-IP minute bucket.
- Mutation bodies are limited to 1 MiB; Stripe webhooks are limited to 256 KiB.
- Responses include a request ID, `nosniff`, same-origin referrer policy, no-store caching and CSP; production adds HSTS.
- Current rate limiting is a basic abuse control, not a full tenant/user quota system.

## Release and rollback status

No production runbook or tested rollback exists yet. Before release, document migration ownership, deploy order, rollback compatibility, provider disablement, identity outage behavior and manual reconciliation. Forward-only financial migrations should normally roll back by restoring a verified backup and reverting the application to a compatible release, not by destructive downgrade SQL.

Use `python -m scripts.serve` on Windows so psycopg gets an explicit Selector event loop. Native checkpoint migrations run during startup, before request transactions, to avoid concurrent-index migration waits on open application reads.
