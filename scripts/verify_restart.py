"""Verify durable human review across real service process restarts."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import httpx

def verify():
    with tempfile.TemporaryDirectory(prefix="support-agent-restart-", ignore_cleanup_errors=True) as temporary:
        root = Path(temporary)
        environment = os.environ.copy()
        environment.update(DATABASE_URL=f"sqlite+aiosqlite:///{(root/'app.db').as_posix()}",
            SYNC_DATABASE_URL=f"sqlite:///{(root/'app.db').as_posix()}",
            CHECKPOINT_DATABASE_URL=f"sqlite:///{(root/'checkpoints.db').as_posix()}",
            AUTH_MODE="demo", ENVIRONMENT="development", LLM_PROVIDER="mock")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"
        process = None
        def stop():
            nonlocal process
            if process is not None:
                process.terminate()
                process.wait(timeout=15)
                process = None
        def start():
            nonlocal process
            process = subprocess.Popen([sys.executable,"-m","scripts.serve","--port",str(port)],
                env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0)
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError("Demo service failed to start")
                try:
                    if httpx.get(base_url+"/api/health", timeout=0.5).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            raise RuntimeError("Demo startup timed out")
        try:
            start()
            reviewer = {"Authorization":"Bearer rev_supervisor"}
            owner = {"Authorization":"Bearer cust_1001"}
            with httpx.Client(base_url=base_url, timeout=20) as client:
                response = client.post("/api/complaints",headers=owner,json={"customer_id":"cust_1001","order_id":"ord_1001","message":"Please refund my returned headphones."})
                response.raise_for_status()
                state = response.json()
                assert state["is_paused"]
                stop()
                start()
                saved = client.get(f"/api/workflows/{state['run_id']}",headers=owner)
                saved.raise_for_status()
                assert saved.json()["is_paused"]
                queue = client.get("/api/approvals/pending",headers=reviewer).json()
                approval = next(item for item in queue if item["proposal_id"]==state["proposed_action_id"])
                response = client.post(f"/api/approvals/{approval['approval_id']}/decision",headers=reviewer,
                    json={"decision":"APPROVED","reviewer_id":"rev_supervisor","reviewer_name":"Reviewer"})
                response.raise_for_status()
                assert response.json()["workflow_outcome"]["status"] == "SUCCEEDED", response.text
                reference = response.json()["workflow_outcome"]["gateway_reference"]
                stop()
                start()
                saved = client.get(f"/api/workflows/{state['run_id']}",headers=owner).json()
                assert saved["external_result_reference"] == reference and saved["is_completed"]
                response = client.post(f"/api/workflows/{state['run_id']}/resume",headers=reviewer,
                    json={"decision":"APPROVED","reviewer_id":"rev_supervisor","reviewer_name":"Reviewer"})
                assert response.json()["external_result_reference"] == reference
                print("Pending review and confirmed refund survived two process restarts; replay preserved the gateway reference.")
        finally:
            stop()

if __name__ == "__main__":
    verify()
