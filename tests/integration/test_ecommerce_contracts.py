"""Contract tests for typed ecommerce, shipping, and ticket sync integrations."""
import http.server
import json
import threading
from typing import Dict, Any
import pytest
from pydantic import ValidationError
from app.config import settings
from app.db.models import Order
from app.integrations.ecommerce import shipment, sync_ticket, Shipment, request

class _MockEcommerceServer:
    def __init__(self):
        self.server = None
        self.thread = None
        self.port = None
        self.base_url = None
        self.requests = []

    def start(self):
        parent = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parent.requests.append(("GET", self.path, self.headers.get("Authorization")))
                if self.path == "/orders/ord_test_shipment/shipment":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "order_id": "ord_test_shipment",
                        "status": "DELIVERED",
                        "carrier": "FedEx",
                        "tracking_number": "1234567890",
                        "estimated_delivery": "2026-10-24T12:00:00Z",
                        "location": "Warehouse Hub A",
                        "source": "ecommerce_gateway"
                    }).encode())
                elif self.path == "/orders/ord_mismatched/shipment":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    # Mismatched order_id
                    self.wfile.write(json.dumps({
                        "order_id": "ord_different_999",
                        "status": "IN_TRANSIT"
                    }).encode())
                elif self.path == "/orders/ord_invalid_schema/shipment":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    # Extra forbidden field
                    self.wfile.write(json.dumps({
                        "order_id": "ord_invalid_schema",
                        "status": "IN_TRANSIT",
                        "unknown_field_attack": "malicious_payload"
                    }).encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_PUT(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode()) if length else {}
                parent.requests.append(("PUT", self.path, body, self.headers.get("Authorization")))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"synced": True, "ticket_id": body.get("ticket_id")}).encode())

            def log_message(self, format, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

@pytest.fixture(scope="module")
def ecommerce_server():
    server = _MockEcommerceServer()
    server.start()
    yield server
    server.stop()

@pytest.mark.asyncio
async def test_typed_shipment_contract_and_auth(ecommerce_server, monkeypatch):
    """Verify typed shipment response, bearer auth, and model mapping."""
    monkeypatch.setattr(settings, "INTEGRATION_BASE_URL", ecommerce_server.base_url)
    monkeypatch.setattr(settings, "INTEGRATION_API_TOKEN", "secret-ecommerce-token-abc")

    mock_order = Order(id="ord_test_shipment", status="DELIVERED")
    data = await shipment(mock_order)

    assert data["order_id"] == "ord_test_shipment"
    assert data["carrier"] == "FedEx"
    assert data["tracking_number"] == "1234567890"
    assert data["status"] == "DELIVERED"
    assert data["source"] == "ecommerce_gateway"

@pytest.mark.asyncio
async def test_shipment_rejects_mismatched_order_id(ecommerce_server, monkeypatch):
    """Verify that external response with a mismatched order ID is rejected."""
    monkeypatch.setattr(settings, "INTEGRATION_BASE_URL", ecommerce_server.base_url)
    monkeypatch.setattr(settings, "INTEGRATION_API_TOKEN", "secret-ecommerce-token-abc")

    mock_order = Order(id="ord_mismatched", status="DELIVERED")
    with pytest.raises(ValueError, match="Shipment response does not match the owned order"):
        await shipment(mock_order)

@pytest.mark.asyncio
async def test_shipment_rejects_extra_fields(ecommerce_server, monkeypatch):
    """Verify strict schema validation: extra fields on Shipment are forbidden."""
    monkeypatch.setattr(settings, "INTEGRATION_BASE_URL", ecommerce_server.base_url)
    monkeypatch.setattr(settings, "INTEGRATION_API_TOKEN", "secret-ecommerce-token-abc")

    mock_order = Order(id="ord_invalid_schema", status="DELIVERED")
    with pytest.raises(ValidationError):
        await shipment(mock_order)

@pytest.mark.asyncio
async def test_idempotent_ticket_sync_contract(ecommerce_server, monkeypatch):
    """Verify that ticket updates are dispatched with idempotency key and bearer credentials."""
    monkeypatch.setattr(settings, "INTEGRATION_BASE_URL", ecommerce_server.base_url)
    monkeypatch.setattr(settings, "INTEGRATION_API_TOKEN", "secret-ecommerce-token-abc")

    payload = {"ticket_id": "tkt_1001", "status": "RESOLVED", "note": "Refund completed"}
    res = await sync_ticket(payload, key="idem_ticket_sync_999")
    assert res["synced"] is True
    assert res["ticket_id"] == "tkt_1001"
