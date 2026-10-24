"""Business-date policy selection, shared by retrieval and financial enforcement."""
from datetime import date, datetime
from sqlalchemy import select
from app.db.models import PolicyChunk

async def applicable_chunks(db, business_date=None, policy_id=None):
    effective = (business_date.date() if isinstance(business_date, datetime) else business_date) or date.today()
    statement = select(PolicyChunk)
    if policy_id:
        statement = statement.where(PolicyChunk.policy_id == policy_id)
    chunks = (await db.execute(statement)).scalars().all()
    chunks = [c for c in chunks if c.metadata_json.get("effective_date", "0001-01-01") <= effective.isoformat()
        and (not c.metadata_json.get("effective_to") or effective.isoformat() < c.metadata_json["effective_to"])]
    versions = {}
    for c in chunks:
        key = (c.metadata_json.get("effective_date", ""), tuple(int(p) for p in c.version.split(".")))
        versions[c.policy_id] = max(versions.get(c.policy_id, ("", ())), key)
    return [c for c in chunks if (c.metadata_json.get("effective_date", ""), tuple(int(p) for p in c.version.split("."))) == versions[c.policy_id]]
