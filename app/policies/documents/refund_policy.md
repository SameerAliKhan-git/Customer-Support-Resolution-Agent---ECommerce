# ElectroVault Global - Customer Refund Policy
Document ID: refund_policy_v1
Version: 1.0
Effective Date: 2026-01-01

## Section 1: General Refund Principles
ElectroVault Global provides clear and fair refund processing for all eligible purchases. All financial transactions are recorded in minor currency units (cents/paise) to prevent rounding discrepancies. 

## Section 2: Eligibility Requirements for Returns
Refunds for returned merchandise become eligible only when all of the following conditions are met:
1. The customer initiated a return within the approved 30-day return window.
2. The return shipment has been physically received at the fulfillment facility.
3. The item has undergone quality inspection and the inspection status is officially marked as INSPECTION_PASSED.
4. If an item has failed inspection (e.g., missing original serial number, deliberate physical abuse, or customer-induced liquid damage), a refund is blocked and the ticket must be escalated.

## Section 3: Mandatory Human Approval
To protect both customers and the business against erroneous or unauthorized fund transfers:
1. A support reviewer must inspect the verified facts and explicitly approve every proposed refund prior to disbursement.
2. An agent or automated system may only prepare and propose a refund; it cannot disburse funds autonomously.
3. Every proposal must include verified evidence references (return record ID, payment record ID) and applicable policy citations.
4. A proposal expires after 48 hours if no reviewer decision is made.

## Section 4: Refund Disbursement and Financial Caps
1. Refunds must always be issued to the original payment method used for the order.
2. The total refunded amount across all operations for an order cannot exceed the original captured payment balance.
3. Any pending refund proposal reserves the requested amount from the order's refundable balance to prevent double-spending or concurrent race conditions.

## Section 5: Unconfirmed and Interrupted Payment Results
If the payment gateway connection times out or returns an ambiguous status:
1. The transaction must not be blindly retried with a new identifier.
2. The operation must be flagged as PENDING_RECONCILIATION.
3. A verification query must be made against the payment gateway using the unique idempotency key before determining further action.
