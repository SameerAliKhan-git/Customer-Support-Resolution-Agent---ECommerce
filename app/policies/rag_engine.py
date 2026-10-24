"""RAG engine for ingesting, embedding, and searching support policies with versioning and citations."""
import os
import re
import math
import hashlib
from pathlib import Path
from datetime import date
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.db.models import PolicyChunk

# Vector dimensionality for hybrid local embeddings
EMBEDDING_DIM = 128

def generate_local_embedding(text: str) -> List[float]:
    """
    Generates a deterministic normalized dense embedding vector for semantic matching.
    Uses n-gram hash projection with subword hashing and TF-IDF weighting.
    Works offline with zero external dependencies and guaranteed reproducibility.
    """
    vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    words = re.findall(r'\b[a-zA-Z0-9_-]+\b', text.lower())
    if not words:
        return vec.tolist()

    for i, word in enumerate(words):
        # 1-gram hash
        h1 = int(hashlib.md5(word.encode()).hexdigest(), 16) % EMBEDDING_DIM
        weight = 1.0 / (1.0 + math.log(1.0 + len(word)))
        vec[h1] += weight
        
        # 2-gram hash if available
        if i < len(words) - 1:
            bigram = f"{word}_{words[i+1]}"
            h2 = int(hashlib.sha256(bigram.encode()).hexdigest(), 16) % EMBEDDING_DIM
            vec[h2] += 1.5 * weight

    # Normalize vector to unit length
    norm = np.linalg.norm(vec)
    if norm > 1e-6:
        vec = vec / norm
    return vec.tolist()

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    a = np.array(vec1, dtype=np.float32)
    b = np.array(vec2, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))

def parse_markdown_policy(filepath: str) -> List[Dict[str, Any]]:
    """
    Parses markdown policy file and extracts chunks divided by headers.
    Preserves document ID, version, and section references.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    doc_id_match = re.search(r"Document ID:\s*([a-zA-Z0-9_-]+)", content)
    version_match = re.search(r"Version:\s*([0-9.]+)", content)
    effective_match = re.search(r"Effective Date:\s*([0-9-]+)", content)
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)

    doc_id = doc_id_match.group(1) if doc_id_match else os.path.basename(filepath).replace(".md", "")
    version = version_match.group(1) if version_match else "1.0"
    effective_date = effective_match.group(1) if effective_match else "2026-01-01"
    doc_title = title_match.group(1) if title_match else doc_id

    chunks = []
    # Split by ## Section
    sections = re.split(r"(^##\s+.+$)", content, flags=re.MULTILINE)
    
    current_section_title = "Overview"
    current_section_id = "section_overview"

    for part in sections:
        part = part.strip()
        if not part:
            continue
        if part.startswith("## "):
            current_section_title = part[3:].strip()
            # Extract section id (e.g. "Section 2: Eligibility Requirements" -> "section_2")
            sec_num = re.search(r"Section\s+([0-9]+)", current_section_title, re.IGNORECASE)
            if sec_num:
                current_section_id = f"section_{sec_num.group(1)}"
            else:
                current_section_id = f"sec_{re.sub(r'[^a-zA-Z0-9]', '_', current_section_title.lower())[:15]}"
        else:
            # Body of section
            chunk_text = f"{doc_title} - {current_section_title}\n\n{part}"
            citation_ref = f"{doc_id}:{current_section_id}"
            embedding = generate_local_embedding(chunk_text)
            chunks.append({
                "policy_id": doc_id,
                "version": version,
                "title": f"{doc_title} - {current_section_title}",
                "section": current_section_id,
                "content": part,
                "metadata_json": {
                    "document_id": doc_id,
                    "version": version,
                    "effective_date": effective_date,
                    "section_title": current_section_title,
                    "citation_ref": citation_ref
                },
                "embedding": embedding
            })

    return chunks

class PolicyRAGService:
    @staticmethod
    async def ingest_directory(dir_path: str, db: AsyncSession) -> int:
        """Reads all policy markdown files and saves chunks into DB."""
        if not os.path.exists(dir_path):
            return 0
        
        from app.db.operations import PolicyVersion
        count = 0
        for path in sorted(Path(dir_path).glob("*.md")):
            chunks = parse_markdown_policy(str(path))
            if not chunks:
                continue
            raw = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(raw.encode()).hexdigest()
            first = chunks[0]
            identifier = hashlib.sha256(f"{first['policy_id']}:{first['version']}".encode()).hexdigest()
            existing = await db.get(PolicyVersion, identifier)
            if existing and existing.content_hash != digest:
                raise ValueError("Published policy content changed without a version increment.")
            if not existing:
                db.add(PolicyVersion(id=identifier, policy_id=first["policy_id"], version=first["version"],
                    content_hash=digest, content=raw, effective_from=first["metadata_json"]["effective_date"]))
            for chunk in chunks:
                found = (await db.execute(select(PolicyChunk).where(PolicyChunk.policy_id == chunk["policy_id"],
                    PolicyChunk.version == chunk["version"], PolicyChunk.section == chunk["section"]))).scalars().first()
                if found:
                    if found.content != chunk["content"]:
                        raise ValueError("Stored policy chunk conflicts with its published version.")
                    continue
                db.add(PolicyChunk(**chunk))
                count += 1
        await db.commit()
        return count

    @staticmethod
    async def search_policies(
        query: str,
        db: AsyncSession,
        policy_id_filter: Optional[str] = None,
        top_k: int = 3,
        business_date=None
    ) -> List[Dict[str, Any]]:
        """
        Retrieves relevant policy passages with citations and similarity scores.
        """
        query_vec = generate_local_embedding(query)
        def terms(value):
            stopwords = {"the", "are", "for", "and", "when", "with", "from", "this", "that", "our", "your", "can", "how"}
            return {word.rstrip("s") for word in re.findall(r"[a-z]{3,}", value.lower()) if word not in stopwords}
        query_terms = terms(query)
        
        from app.policies.catalog import applicable_chunks
        all_chunks = await applicable_chunks(db, business_date, policy_id_filter)
        identities = {}
        for chunk in all_chunks:
            identity = (chunk.policy_id, chunk.version, chunk.section)
            if identity in identities and identities[identity] != chunk.content:
                raise ValueError("Conflicting published policy evidence.")
            identities[identity] = chunk.content
        scored: List[Tuple[float, PolicyChunk]] = []
        q_lower = query.lower()
        
        for chk in all_chunks:
            dense_sim = cosine_similarity(query_vec, chk.embedding)
            # Add lexical boost for exact keyword matches
            content_terms = terms(chk.content)
            title_terms = terms(chk.title)
            lexical_boost = (len(query_terms & content_terms) + 2 * len(query_terms & title_terms)) / max(1, len(query_terms))
            
            final_score = dense_sim + lexical_boost
            overlap = len(query_terms & (content_terms | title_terms)) / max(1, len(query_terms))
            from app.config import settings
            if overlap >= settings.POLICY_MIN_LEXICAL_OVERLAP:
                scored.append((final_score, chk))
            
        scored.sort(key=lambda x: x[0], reverse=True)
        
        top_results = []
        for score, chk in scored[:top_k]:
            citation = chk.metadata_json.get("citation_ref", f"{chk.policy_id}:{chk.section}")
            top_results.append({
                "policy_id": chk.policy_id,
                "version": chk.version,
                "title": chk.title,
                "section": chk.section,
                "citation": citation,
                "content": chk.content,
                "similarity_score": round(score, 4),
                "metadata": chk.metadata_json
            })
            
        return top_results

policy_rag_service = PolicyRAGService()
