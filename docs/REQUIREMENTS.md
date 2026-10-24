# Requirements and implementation decisions

Source requested: https://app.notion.com/p/Build-a-Customer-Support-Resolution-Agent-3fa0f9646947801d9715f07086e59ea3

The user supplied the complete brief directly on 23 October 2026, confirming the source requirements. The user also explicitly authorized opening the secure OpenAI API-key setup flow. That flow currently cannot proceed because the OpenAI Platform connection requires reauthentication; no key was created or stored.

For current completion status and executable remaining work, use [AGENT_HANDOFF.md](AGENT_HANDOFF.md). This file records requirements and design decisions; it is not the live backlog.

The source was read through the browser on 22 October 2026 after the connector returned `object_not_found`. Its intended first version uses one store/currency, synthetic customer data, mock shipping/payments, three complaint types, human approval for every refund, and communication inside the demo. Chargeback handling, fraud adjudication and complex partial returns are excluded.

| Source requirement | Implementation | Validation |
| --- | --- | --- |
| Complaint-to-resolution workflow | LangGraph specialist nodes | Integration tests and synthetic evaluation |
| Customer-owned data only | API and read-tool ownership enforcement | Cross-customer and workflow access tests |
| Policy-grounded proposals | Versioned section citations | Retrieval unit tests and evaluation |
| Human approval before refunds | Database approvals and privileged decision endpoint | Pending, rejection and unauthorized resume tests |
| Verified refund execution | Provider response/reconciliation before resolved outcome | Refund and timeout tests |
| No duplicate refund | Original operation reused per proposal | Same-session and separate-session concurrency tests |
| Restart-safe pending review | Official LangGraph durable checkpoints and SQL run index | New-engine read and API state tests |
| Durable request execution | Database work queue, leases, retries, recovery scan and heartbeat | Job recovery regression tests; PostgreSQL multi-process gate remains |
| Production identity foundation | OIDC discovery/JWKS, issuer/audience/role/MFA enforcement | Mocked/local tests; real tenant qualification remains |
| Payment integration foundation | Stripe adapter, stable key, normalized statuses and signed webhook inbox | Mock tests; sandbox matrix remains |
| Ecommerce integration foundation | Typed shipment response and idempotent ticket-sync gateway | Synthetic adapter path; provider contract tests remain |
| Reviewer and system audit trail | Linked ticket/proposal/approval/operation events | Timeout audit regression |
| Runnable deliverable | Windows script, requirements, Docker and CI recipes | Local service and tests; Docker requires separate validation |

## Decisions

- Offline deterministic agents permit a complete demonstration without provider credentials or expense. Optional schema-validated OpenAI classification is implemented and tested with mocked provider responses. Live provider validation is pending credential authorization.
- SQLite and synchronous execution keep the demo small. PostgreSQL, durable jobs and database execution claims are implemented. Multi-worker deployments still require PostgreSQL CI, contention/failover qualification and production deployment configuration.
- Every financial proposal requires human review. No automatic refund threshold bypass is enabled.
- The existing damaged-goods dataset expected four $320 claims to produce refund proposals without evidence. That contradicted section 1 of the local damaged-goods policy, which requires photographic documentation or serial verification above $100. Those expectations were corrected to specialist escalation, with rationale stored on each case. The implementation preserves this evidence requirement.
- Evaluation statuses are computed from measured values; the original report template hardcoded all rows as passed. Tests and evaluations now run against isolated temporary databases.
- No cloud deployment, live payment credentials, live customer support integration or external communication was configured. Suggested endpoint names in the brief map to `/api/complaints`, `/api/workflows`, `/api/tickets` and `/api/approvals`; clarification messages can continue an existing thread.

## Remaining and advanced work

The production-style worker foundation is implemented, but its production topology and PostgreSQL multi-process qualification remain. The specialist-versus-single-agent experiment is still unmeasured; no superiority claim is made. The synthetic evaluation uses the existing templated 60-case dataset plus separate reliability/security tests. It is not a held-out production evaluation. Native policy interpretation and resolution drafting remain deterministic; optional live classification is the only model-backed stage.

Current schema drift, external provider decisions, P0/P1 tasks and definitions of done are maintained only in `AGENT_HANDOFF.md` to prevent duplicate backlogs from diverging.
