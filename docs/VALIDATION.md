# System Validation & Verification Evidence

[![Verification Status](https://img.shields.io/badge/Verification-Verified%20(55%2F55)-brightgreen.svg)](docs/VALIDATION.md)
[![Schema Drift](https://img.shields.io/badge/Alembic%20Drift-0%20Detected-brightgreen.svg)](migrations/)
[![Evaluation](https://img.shields.io/badge/Synthetic%20Eval-100%25%20(60%2F60)-brightgreen.svg)](evals/reports/eval_report.md)

**Validation Date:** 24 October 2026  
**Target Platform:** Windows 11 & Linux (Docker PostgreSQL 16)  
**Python Runtime:** Python 3.12 / 3.11  

This document records the empirical validation evidence, regression test results, schema drift audits, and evidence boundaries for the Customer Support Resolution Agent codebase.

---

## 📑 Table of Contents
- [Summary of Verification Results](#summary-of-verification-results)
- [Automated Test Suite Breakdown](#automated-test-suite-breakdown)
- [Synthetic Evaluation Benchmark](#synthetic-evaluation-benchmark)
- [Process Restart & Checkpoint Recovery](#process-restart--checkpoint-recovery)
- [Database Schema Integrity & Migration Drift](#database-schema-integrity--migration-drift)
- [Evidence Boundaries & Safety Disclaimers](#evidence-boundaries--safety-disclaimers)
- [Step-by-Step Reproduction Guide](#step-by-step-reproduction-guide)

---

## 📊 Summary of Verification Results

| Verification Check | Target Component | Status | Empirical Evidence |
| :--- | :--- | :---: | :--- |
| **Python Regression Suite** | Core APIs, Services, Integrations | **✅ PASS** | **55 passed** in 28.64s across SQLite and live PostgreSQL container. |
| **JavaScript Syntax Audit** | Dashboard UI (`app.js`, `session.js`) | **✅ PASS** | Clean syntax verified via `node --check`. |
| **Synthetic Resolution Eval** | LangGraph Decision Accuracy | **✅ PASS** | **60/60 correct** resolutions (100% policy compliance). |
| **Financial Ledger Invariants** | Double-spending & Reservation Guards | **✅ PASS** | 100% of synthetic refunds verified against ledger, provider ref, and ticket. |
| **Duplicate Refund Immunity** | Concurrency & Idempotency Replays | **✅ PASS** | **0 unauthorized refunds**, 0 duplicate executions under contention. |
| **Process Restart Survival** | LangGraph Durable Checkpointers | **✅ PASS** | Pending review & confirmed refund survived 2 process restarts. |
| **Alembic Schema Drift Audit** | Model Schema vs Database DDL | **✅ PASS** | `alembic check` reports **zero drift** up to `0003_proposal_supersession`. |
| **Enterprise OIDC Qualification**| Asymmetric RS256 JWKS & MFA | **✅ PASS** | Verified signature validation, customer subject scoping, and staff MFA. |
| **Payment Sandbox Matrix** | Stripe Integration & Webhook Security| **✅ PASS** | Normalized statuses, signed HMAC v1 webhooks, idempotency, and live key guard. |
| **Ecommerce Contracts** | Shipment & Ticket Integration | **✅ PASS** | Typed `Shipment` contract (`extra='forbid'`) and idempotent ticket sync. |
| **Multi-Worker Contention** | PostgreSQL Row Locking | **✅ PASS** | `with_for_update(skip_locked=True)` multi-worker claiming safety verified. |

---

## 🧪 Automated Test Suite Breakdown

The test suite is structured into unit, integration, and reliability suites located in `tests/`:

### 1. Database Migrations & Schema Drift (`tests/integration/test_migrations.py`)
- Verifies clean migration from an empty database up to `0003_proposal_supersession`.
- Verifies self-referential foreign key `refund_proposals.supersedes_proposal_id`, its index, and status check constraints.
- Confirms `alembic check` passes without any model/migration discrepancies.

### 2. Production Topology & Health Probes (`tests/integration/test_topology.py`)
- Validates `/api/ready` heartbeat detection, database readiness, and worker task queuing.
- Asserts that startup aborts if `AUTO_CREATE_SCHEMA=true` or `SEED_DEMO_DATA=true` when `ENVIRONMENT=production`.

### 3. Enterprise OIDC & Authentication (`tests/integration/test_oidc_qualification.py`)
- Generates ephemeral RSA-2048 keypairs and local mock JWKS endpoint.
- Validates token signature, audience, expiration, and customer subject mapping (`customers.external_auth_subject`).
- Asserts that staff users lacking MFA (`amr: ["mfa"]`) receive `403 Forbidden`.
- Confirms cross-customer data isolation (attempting to access another customer's ticket returns `403 Forbidden` without information disclosure).

### 4. Payment Sandbox & Webhook Safety (`tests/integration/test_payment_sandbox_matrix.py`)
- Validates Stripe status mapping (`succeeded`, `pending`, `failed`, `requires_action`).
- Enforces HMAC v1 signature verification with timestamp tolerance and replay rejection.
- Asserts that initializing `StripePaymentAdapter` with `sk_live_` credentials raises a fatal exception unless `ALLOW_LIVE_PAYMENT_CREDENTIALS=true`.
- Tests gateway timeout simulation and subsequent deterministic reconciliation via original idempotency key.

### 5. Ecommerce Data Contracts (`tests/integration/test_ecommerce_contracts.py`)
- Enforces strict Pydantic model validation on carrier shipment records.
- Tests server-side ownership re-validation before reading order details.
- Verifies idempotent `PUT /tickets/{id}` synchronization.

### 6. Multi-Worker Contention & Concurrency (`tests/integration/test_multiprocess_contention.py`)
- Spawns parallel asynchronous workers competing for the same queue item in PostgreSQL.
- Verifies that row-level locking (`with_for_update(skip_locked=True)`) guarantees exactly-once task assignment.
- Verifies that concurrent refund attempts on the same order cannot double-spend available balance.

---

## 📈 Synthetic Evaluation Benchmark

The synthetic evaluation harness (`evals/run_evals.py`) runs 60 diversified scenarios covering three primary customer complaint categories:
1. **Order Tracking & Status:** Validates shipment status retrieval and delivery window estimation.
2. **Refund Requests:** Checks return intake, warehouse inspection timestamps, and 30-day policy boundaries.
3. **Damaged Goods Claims:** Tests policy threshold gating ($100 rule requiring photographic proof).

### Benchmark Metrics
```text
Cases Executed:           60
Cases Passed:             60 (100.0%)
Policy Hit Accuracy:      100.0%
Financial Ledger Match:   100.0%
Mean Active Latency:      0.223s per case
```

*The complete evaluation report is persisted at `evals/reports/eval_report.md`.*

---

## 🔄 Process Restart & Checkpoint Recovery

The restart verification harness (`scripts/verify_restart.py`):
1. Starts the application with an isolated temporary database.
2. Ingests a refund complaint that triggers a pending approval.
3. Kills the application process while awaiting review.
4. Spawns a new application process against the same database.
5. Verifies that the graph state and proposal successfully survived.
6. Submits the reviewer approval, confirms payment execution, and terminates the server again.
7. Spawns a third application process and confirms that the final resolution, payment ledger, and audit trail are intact.

---

## 🛡️ Evidence Boundaries & Safety Disclaimers

To maintain engineering integrity, we explicitly define the boundaries of the evidence provided:

- **Synthetic Data Baseline:** The 60 evaluation scenarios use structured synthetic templates. They establish deterministic policy execution, but do not represent unconstrained natural-language human interactions.
- **Provider Sandbox Boundaries:** Payment and ecommerce tests use mock gateways and offline sandbox adapters. Live financial transactions and external carrier API calls were deliberately excluded.
- **Identity Scope:** OIDC tests utilize an ephemeral RSA-2048 mock authority. Real-world tenant provisioning (e.g. enterprise Okta SSO) requires client secret configuration during deployment.

---

## 🚀 Step-by-Step Reproduction Guide

To execute and verify all evidence locally:

```bash
# 1. Run the entire pytest regression suite
pytest --disable-warnings -v

# 2. Check for Alembic schema drift
alembic check

# 3. Execute the 60-case synthetic benchmark
python -m evals.run_evals

# 4. Run the process restart & checkpoint survival drill
python -m scripts.verify_restart

# 5. Audit JavaScript syntax
node --check app/static/app.js
node --check app/static/session.js
```
