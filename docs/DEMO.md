# Reproduce the demonstration

> This walkthrough uses synthetic records and the mock payment provider. It proves the local demo behavior only; it is not payment-sandbox, staging or production evidence. For current verification and remaining release gates, see [VALIDATION.md](VALIDATION.md) and [AGENT_HANDOFF.md](AGENT_HANDOFF.md).

Start the app using the README and open http://127.0.0.1:8000. Synthetic refunds change the demo ledger permanently so repeated runs correctly report no available balance. For a clean demonstration, select a new disposable database filename in `.env`; preserve existing databases if their audit history matters.

## A: Approved refund

Select scenario A and submit the complaint. Inspect the returned order, inspection result, payment balance and cited policy sections. Approve the proposal in the reviewer panel. Confirm the provider reference in the final result and `REFUND_SUCCEEDED` in the audit history.

## B: Blocked request

Select scenario B. The order is outside the standard return window and has no return intake. The application answers with the return policy and does not create an approval or refund operation.

## C: Timeout recovery

Select scenario C, submit and approve. The simulated provider accepts the refund but times out on the response. The workflow records `REFUND_TIMEOUT_RECONCILIATION_REQUIRED`, queries the same operation key, then records `REFUND_RECONCILED_SUCCESS`. One gateway reference is returned, with one payment effect.

## Restart proof

Run `python -m scripts.verify_restart`. This creates a private database and service, stops the process while awaiting review, starts it again, approves the same workflow, restarts a second time and verifies the confirmed result and reference still exist. It cleans up the subprocesses at completion.

## Captured walkthrough

`demo/walkthrough.gif` is an animated sequence of actual browser screenshots from the three scenarios, with readable pauses. It is a captured walkthrough rather than a real-time screen recording. Individual screenshots are included beside it.
