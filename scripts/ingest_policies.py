"""Standalone CLI tool for ingesting policy markdown files into the vector database."""
import asyncio
from app.db.session import AsyncSessionLocal, init_db
from app.policies.rag_engine import policy_rag_service

async def main():
    await init_db()
    async with AsyncSessionLocal() as session:
        count = await policy_rag_service.ingest_directory("app/policies/documents", session)
        print(f"Policy ingestion complete! {count} chunks indexed with embeddings and citations.")

if __name__ == "__main__":
    asyncio.run(main())
