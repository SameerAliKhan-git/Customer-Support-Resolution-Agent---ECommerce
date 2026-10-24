# Operations & Production Runbook

[![Status](https://img.shields.io/badge/Operations-Production--Ready-blue.svg)](docs/OPERATIONS.md)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-compose.prod.yaml-2496ED.svg?logo=docker&logoColor=white)](compose.prod.yaml)

This runbook provides administrative and engineering guidance for deploying, configuring, monitoring, maintaining, and recovering the Customer Support Resolution Agent across local, staging, and production environments.

---

## 📑 Table of Contents
- [Production Architecture & Guarantees](#production-architecture--guarantees)
- [Environment Configuration Reference](#environment-configuration-reference)
- [Deployment Procedures](#deployment-procedures)
  - [Local Development (SQLite)](#local-development-sqlite)
  - [Production Stack (PostgreSQL 16)](#production-stack-postgresql-16)
- [Database Migrations & Schema Management](#database-migrations--schema-management)
- [Security & Authentication Setup](#security--authentication-setup)
- [Worker Operations & Queue Management](#worker-operations--queue-management)
- [Observability & Health Checks](#observability--health-checks)
- [Incident Response & Disaster Recovery](#incident-response--disaster-recovery)

---

## 💡 Production Architecture & Guarantees

In a deployed production environment:
1. **Multi-Worker Safety:** Background workers claim jobs from PostgreSQL with `with_for_update(skip_locked=True)`, preventing duplicate job processing.
2. **Crash & Restart Resilience:** Pending human approvals and in-flight workflows are checkpointed in PostgreSQL. Server restarts or replacement containers resume gracefully.
3. **Financial Protection:** The Stripe payment adapter prevents live key (`sk_live_`) initialization in non-production environments (`ALLOW_LIVE_PAYMENT_CREDENTIALS=false`).
4. **Authoritative State:** Financial proposals, approvals, and refund operations maintain strict relational integrity with zero schema drift.

---

## ⚙️ Environment Configuration Reference

Configuration is managed via Pydantic Settings in `app/config.py`. All parameters can be overridden via environment variables or a `.env` file.

| Variable Name | Type | Default | Production Requirement | Description |
| :--- | :---: | :---: | :---: | :--- |
| `ENVIRONMENT` | `str` | `development` | `production` | Deployment environment name (`development`, `staging`, `production`). |
| `DATABASE_URL` | `str` | `sqlite+aiosqlite:///support_agent.db` | **PostgreSQL URL** | Async SQLAlchemy connection string (`postgresql+psycopg://...`). |
| `SYNC_DATABASE_URL` | `str` | `sqlite:///support_agent.db` | **PostgreSQL URL** | Sync SQLAlchemy connection string for Alembic migrations. |
| `CHECKPOINT_DATABASE_URL` | `str` | `sqlite:///checkpoints.db` | **PostgreSQL URL** | Dedicated database for LangGraph state checkpointers. |
| `ASYNC_WORKFLOWS` | `bool` | `false` | `true` | Routes workflow execution through the durable `work_items` queue. |
| `AUTH_MODE` | `str` | `demo` | `oidc` | Authentication scheme (`demo`, `signed`, `oidc`). |
| `SECRET_KEY` | `str` | Dev secret | **Cryptographic Key** | Signing key for internal session tokens (min 32 characters). |
| `OIDC_ISSUER` | `str` | `""` | **Required if OIDC** | Issuer URL for OpenID Connect discovery (`/.well-known/openid-configuration`). |
| `OIDC_AUDIENCE` | `str` | `""` | **Required if OIDC** | Expected audience claim (`aud`) in OIDC ID/access tokens. |
| `OIDC_REQUIRE_STAFF_MFA` | `bool` | `true` | `true` | Mandates multi-factor authentication (`amr: ["mfa"]`) for reviewers. |
| `PAYMENT_PROVIDER` | `str` | `mock` | `stripe` | Payment engine (`mock`, `stripe`). |
| `ALLOW_LIVE_PAYMENT_CREDENTIALS` | `bool` | `false` | Controlled | Safety guard preventing accidental initialization of `sk_live_` keys. |
| `STRIPE_SECRET_KEY` | `str` | `""` | Required if Stripe | Stripe API key (must start with `sk_test_` unless live allowed). |
| `STRIPE_WEBHOOK_SECRET` | `str` | `""` | Required if Stripe | Stripe webhook signing secret (`whsec_...`). |
| `AUTO_CREATE_SCHEMA` | `bool` | `true` | **`false`** | Refuses startup if true in production; schema must come from migrations. |
| `SEED_DEMO_DATA` | `bool` | `true` | **`false`** | Prevents mock data injection in production databases. |

---

## 🚀 Deployment Procedures

### Local Development (SQLite)
Suitable for rapid experimentation, scenario testing, and offline demos:
```powershell
# Run the turnkey Windows launcher
./scripts/start.ps1
```
*Accessible at http://127.0.0.1:8000.*

### Production Stack (PostgreSQL 16)
Deploy the containerized production topology using `compose.prod.yaml`:
```bash
docker compose -f compose.prod.yaml up --build -d
```

This stack orchestrates:
1. `postgres`: PostgreSQL 16 Alpine with health check probe.
2. `migrate`: Ephemeral container running `alembic upgrade head`, exiting `0` before services start.
3. `api`: Web API container running Uvicorn with 2 worker processes on port 8000.
4. `worker`: Background task worker executing `scripts/worker.py` with queue leases and heartbeat reporting.

---

## 🗄️ Database Migrations & Schema Management

All database schema evolutions must be tracked in `migrations/versions/`.

```bash
# 1. Inspect current migration status
alembic current

# 2. Check for uncommitted schema drift between ORM models and database
alembic check

# 3. Apply all pending migrations forward
python -m scripts.migrate
# or
alembic upgrade head
```

> [!WARNING]
> **Forward-Only Migration Policy:** Never edit an already-applied migration in version control. If a schema change is required, generate a new migration file (e.g. `0004_...py`). In case of deployment rollback, restore from a verified database snapshot rather than running destructive downgrade scripts.

---

## 🔐 Security & Authentication Setup

### Enterprise OIDC Mode
1. Configure your identity provider (e.g. Okta, Entra ID, Auth0).
2. Set environment variables:
   ```env
   AUTH_MODE=oidc
   OIDC_ISSUER=https://your-tenant.auth0.com/
   OIDC_AUDIENCE=https://api.yourcompany.com
   OIDC_REQUIRE_STAFF_MFA=true
   ```
3. Map customer users to `customers.external_auth_subject`. Staff members must have the `reviewer` role and have completed MFA (`amr: ["mfa"]`).

### Live Payment Key Protection
The application includes a strict guard in `app/integrations/payments.py`. If a key starting with `sk_live_` is configured while `ALLOW_LIVE_PAYMENT_CREDENTIALS=false`, the service refuses to boot:
```text
RuntimeError: Live payment credentials (sk_live_...) are strictly prohibited unless ALLOW_LIVE_PAYMENT_CREDENTIALS=true.
```

---

## 👷 Worker Operations & Queue Management

The asynchronous queue is backed by the `work_items` table:
```bash
# Run a dedicated worker process
python -m scripts.worker
```

### Worker Lifecycle & Failure Modes
- **Lease Renewal:** While processing a task, the worker continuously renews its lease every 15 seconds (`leased_until = now() + 30s`).
- **Worker Crash Recovery:** If a worker node crashes or loses network, its lease expires. The next available worker reclaims the task with exponential backoff.
- **Dead Letter Isolation:** If a task fails 8 times consecutively, it transitions to `status = 'DEAD'` and an error is logged.

---

## 📊 Observability & Health Checks

### Liveness & Readiness Probes
- **Liveness Probe:** `GET /api/health`
  - Returns `200 OK` if the web service is responsive.
- **Readiness Probe:** `GET /api/ready`
  - Validates PostgreSQL connectivity.
  - Verifies that a background worker heartbeat was published within the last 60 seconds (when `ASYNC_WORKFLOWS=true`).

### Operational Metrics Endpoint
Reviewers and monitoring agents can poll `GET /api/metrics`:
```json
{
  "queue_depth": 0,
  "oldest_ready_job_age_seconds": 0.0,
  "worker_heartbeat_age_seconds": 14.2,
  "active_workers_count": 2,
  "pending_approvals": 1,
  "pending_reconciliations": 0,
  "completed_refunds_total": 5,
  "active_escalations_total": 0
}
```

---

## 🚨 Incident Response & Disaster Recovery

### Resolving Gateway Timeout Reconciliations
If a network partition occurs during a payment refund call:
1. The system marks the operation as `PENDING_RECONCILIATION`.
2. The background worker automatically invokes `reconcile_timeout` using the original idempotency key.
3. If manual intervention is required, inspect the ticket audit trail via `GET /api/tickets/{id}/audit-trail`.
4. Never generate a new refund key; verify the payment status in the Stripe Dashboard using the transaction reference.

### Backup & Restore Procedure
1. **Periodic Snapshot:**
   ```bash
   pg_dump -Fc -U postgres -d customer_support > backup_$(date +%Y%m%d_%H%M%S).dump
   ```
2. **Restoration:**
   ```bash
   pg_restore -U postgres -d customer_support --clean --if-exists backup_file.dump
   ```
