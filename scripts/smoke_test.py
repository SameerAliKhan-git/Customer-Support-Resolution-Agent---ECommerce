"""Exercise a running demo instance. Uses synthetic data and mock refunds only."""
import argparse
import httpx

def run(base_url):
    reviewer = {"Authorization": "Bearer rev_supervisor"}
    with httpx.Client(base_url=base_url, timeout=30) as client:
        assert client.get("/").status_code == 200
        for customer, order, approved in [("cust_1001", "ord_1001", True), ("cust_1002", "ord_1002", False), ("cust_1004", "ord_1008", True)]:
            auth = {"Authorization": f"Bearer {customer}"}
            response = client.post("/api/complaints", headers=auth, json={"customer_id":customer,"order_id":order,"message":"Please refund my returned item."})
            response.raise_for_status()
            state = response.json()
            if approved and state["is_paused"]:
                queue = client.get("/api/approvals/pending", headers=reviewer).json()
                item = next(x for x in queue if x["proposal_id"] == state["proposed_action_id"])
                decision = client.post(f"/api/approvals/{item['approval_id']}/decision", headers=reviewer,
                    json={"decision":"APPROVED","reviewer_id":"rev_supervisor","reviewer_name":"Demo reviewer"})
                decision.raise_for_status()
                assert decision.json()["workflow_outcome"]["status"] == "SUCCEEDED", decision.text
                state = decision.json()["workflow_state"]
            elif approved:
                # Re-running after the same synthetic orders were already refunded is safe.
                assert not state["requires_approval"]
            else:
                assert not state["requires_approval"]
            status = client.get(f"/api/workflows/{state['run_id']}", headers=auth)
            status.raise_for_status()
            print(f"{order}: {status.json()['execution_status']} ({state['run_id']})")
        assert client.get("/api/approvals/pending", headers={"Authorization":"Bearer cust_1001"}).status_code == 403
        print("HTTP smoke checks passed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    run(parser.parse_args().base_url)
