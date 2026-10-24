"""Unit tests for policy ingestion, chunking, and semantic citation retrieval."""
import pytest
from app.db.session import AsyncSessionLocal
from app.policies.rag_engine import policy_rag_service

@pytest.mark.asyncio
async def test_policy_rag_retrieval_and_citations():
    async with AsyncSessionLocal() as db:
        results = await policy_rag_service.search_policies(
            query="When are refunds for returned items eligible?",
            db=db,
            top_k=2
        )
        assert len(results) > 0
        assert any("refund_policy_v1" in r["citation"] for r in results)


@pytest.mark.asyncio
async def test_return_policy_window_retrieval():
    async with AsyncSessionLocal() as db:
        results = await policy_rag_service.search_policies(
            query="30 day return window delivery date",
            db=db,
            policy_id_filter="return_policy_v1",
            top_k=2
        )
        assert len(results) > 0
        assert "return_policy_v1:section_1" in results[0]["citation"]
