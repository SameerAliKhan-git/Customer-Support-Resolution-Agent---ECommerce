# Requirements Traceability & Architectural Decision Records (ADRs)

[![Requirements Coverage](https://img.shields.io/badge/Requirements-100%25%20Covered-brightgreen.svg)](docs/REQUIREMENTS.md)
[![Status](https://img.shields.io/badge/Architecture-Verified-blue.svg)](docs/ARCHITECTURE.md)

This document maps original product requirements from the project brief to concrete implementations, tests, and architectural decision records (ADRs).

---

## 📑 Table of Contents
- [Requirements Traceability Matrix](#requirements-traceability-matrix)
- [Architectural Decision Records (ADRs)](#architectural-decision-records-adrs)
  - [ADR 01: Human-in-the-Loop Financial Gating](#adr-01-human-in-the-loop-financial-gating)
  - [ADR 02: Deterministic Policy Retrieval Baseline](#adr-02-deterministic-policy-retrieval-baseline)
  - [ADR 03: Atomic Reservation Pattern](#adr-03-atomic-reservation-pattern)
  - [ADR 04: Forward-Only Migration Policy](#adr-04-forward-only-migration-policy)
  - [ADR 05: Lease-Backed Durable Queue](#adr-05-lease-backed-durable-queue)
- [Scope Boundaries & Non-Functional Requirements](#scope-boundaries--non-functional-requirements)

---

## 📋 Requirements Traceability Matrix

| Requirement ID | Brief Requirement | Implementation Module | Automated Test / Verification | Status |
| :---: | :--- | :--- | :--- | :---: |
| **REQ-01** | **Complaint-to-Resolution Workflow**<br>Autonomous classification, order lookup, and resolution proposals. | `app/workflows/graph.py`<br>`app/services/complaint_service.py` | `tests/integration/test_workflow.py`<br>`evals/run_evals.py` (60/60) | **✅ PASS** |
| **REQ-02** | **Customer Data Isolation**<br>Strict customer ownership enforcement; prevent cross-tenant data leaks. | `app/api/tickets.py`<br>`app/workflows/investigation.py` | `tests/integration/test_oidc_qualification.py` | **✅ PASS** |
| **REQ-03** | **Policy-Grounded Reasoning**<br>Verifiable section citations from versioned policies; reject low-confidence claims. | `app/services/policy_service.py`<br>`app/workflows/retrieval.py` | `tests/unit/test_policy_retrieval.py` | **✅ PASS** |
| **REQ-04** | **Mandatory Human Review Gate**<br>Zero automatic refunds; every proposal requires an authenticated reviewer approval. | `app/services/approval_service.py`<br>`app/api/approvals.py` | `tests/unit/test_approval_service.py`<br>`tests/integration/test_workflow.py` | **✅ PASS** |
| **REQ-05** | **Verified Settlement & Idempotency**<br>Pin unique provider key per proposal; verify provider status before updating ticket. | `app/services/refund_service.py`<br>`app/integrations/payments.py` | `tests/integration/test_payment_sandbox_matrix.py` | **✅ PASS** |
| **REQ-06** | **Zero Double-Spending**<br>Conditional database row updates reserve available balance at proposal time. | `app/db/models.py`<br>`app/services/approval_service.py` | `tests/integration/test_multiprocess_contention.py` | **✅ PASS** |
| **REQ-07** | **Crash & Restart Resilience**<br>Durable LangGraph checkpoints survive process interruptions and restarts. | `app/workflows/graph.py`<br>`scripts/verify_restart.py` | `scripts/verify_restart.py` (2 restarts verified) | **✅ PASS** |
| **REQ-08** | **Enterprise Identity & MFA**<br>OIDC discovery, RS256 JWKS validation, and mandatory MFA for support staff. | `app/auth/oidc.py`<br>`app/auth/security.py` | `tests/integration/test_oidc_qualification.py` | **✅ PASS** |
| **REQ-09** | **Live Credential Protection**<br>Fatal guard against accidental `sk_live_` initialization in development/staging. | `app/integrations/payments.py`<br>`app/config.py` | `tests/integration/test_payment_sandbox_matrix.py` | **✅ PASS** |
| **REQ-10** | **Asynchronous Job Scheduling**<br>Database-backed `work_items` queue with worker row leases and heartbeat monitoring. | `app/services/jobs.py`<br>`scripts/worker.py` | `tests/integration/test_topology.py`<br>`tests/integration/test_multiprocess_contention.py` | **✅ PASS** |

---

## 🏛️ Architectural Decision Records (ADRs)

### ADR 01: Human-in-the-Loop Financial Gating
- **Context:** Automated refunds in e-commerce can lead to financial losses due to prompt injection or model hallucination.
- **Decision:** All financial tools (`execute_approved_refund`) are decoupled from agent tools. The agent may only invoke `create_refund_proposal`, triggering a LangGraph `interrupt()`. Refunds require explicit human review in `app/api/approvals.py`.
- **Consequences:** Ensures zero unauthorized refunds. Rejection cleanly releases financial reservations.

### ADR 02: Deterministic Policy Retrieval Baseline
- **Context:** Heavy neural embedding models add external API dependencies, latency, and indeterminacy to policy matching.
- **Decision:** Employ 128-dimensional hashed lexical projections with strict lexical overlap scoring and an abstention threshold.
- **Consequences:** Completely offline, deterministic, ultra-fast (sub-millisecond), zero API cost, and transparent reasoning citations.

### ADR 03: Atomic Reservation Pattern
- **Context:** Concurrent requests for the same order could attempt to refund the same balance twice.
- **Decision:** Proposals execute `UPDATE payments SET available_balance = available_balance - :amount WHERE id = :id AND available_balance >= :amount`. If 0 rows are affected, proposal creation aborts with `InsufficientBalanceError`.
- **Consequences:** Eliminates race conditions even across multi-process workers.

### ADR 04: Forward-Only Migration Policy
- **Context:** Modifying applied migrations introduces schema divergence across development and production environments.
- **Decision:** Migration files in `migrations/versions/` are strictly immutable once committed. Schema drift is caught via `alembic check` in CI.
- **Consequences:** Guaranteed database consistency across SQLite and PostgreSQL.

### ADR 05: Lease-Backed Durable Queue
- **Context:** Celery or Redis adds operational overhead for single-store installations.
- **Decision:** Implement durable queue table `work_items` directly in PostgreSQL using `FOR UPDATE SKIP LOCKED` and rolling leases.
- **Consequences:** Zero external dependencies beyond PostgreSQL, unified backup snapshots, and automatic crash recovery.

---

## 🎯 Scope Boundaries & Non-Functional Requirements

- **Supported Currencies:** Single store, single currency (`USD`).
- **Excluded Features:** Chargeback dispute representment, automated fraud scoring, and partial return logistics (deliberately out of scope for MVP).
- **Audit Logging:** All transitions (proposal, review, execution, reconciliation) write immutable records to `audit_logs`.
