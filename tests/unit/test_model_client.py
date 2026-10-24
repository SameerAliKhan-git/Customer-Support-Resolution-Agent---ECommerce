import json
import httpx
import pytest
from app.agents.model_client import classify_with_model
from app.config import settings

@pytest.mark.asyncio
async def test_model_schema_and_bounded_repair(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-credential")
    original = httpx.AsyncClient
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        output = "invalid" if len(calls) == 1 else json.dumps({"category":"ORDER_STATUS", "extracted_order_id":"ord_1003", "confidence":0.9,"urgency":"LOW","reason":"Tracking question"})
        return httpx.Response(200, json={"status":"completed","output":[{"content":[{"type":"output_text","text":output}]}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    result = await classify_with_model("Where is order ord_1003?", None)
    assert result["category"] == "ORDER_STATUS"
    assert len(calls) == 2
    assert calls[0]["text"]["format"]["strict"]
    assert "tools" not in calls[0]

@pytest.mark.asyncio
async def test_missing_provider_credentials_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    with pytest.raises(ValueError):
        await classify_with_model("Refund me", None)
