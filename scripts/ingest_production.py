#!/usr/bin/env python3
"""
Production ETL Script: Ingest real ETL 2025 data into v2 Qdrant collections.

Pulls data from production Directus (directus.etl.visualhive.co), transforms to
v2 faceted schema, embeds with text-embedding-3-large (3072 dims), and upserts
into NEW v2 collections in production Qdrant alongside existing v1 collections.

Entity types and their data sources:
  - Exhibitors (129): vector_profile from Directus -> extract 8 facet texts -> embed
  - Attendees (3517): vector_profile from Directus -> extract 8 facet texts -> embed
  - Sessions (82): NO vector_profile -> LLM generates 6 facet texts -> embed
  - Speakers (134): NO vector_profile -> LLM generates 5 facet texts -> embed

V2 collections created (DO NOT touch v1 collections):
  - exhibitors_master, exhibitors_facets
  - attendees_master, attendees_facets
  - sessions_master, sessions_facets
  - speakers_master, speakers_facets

Usage:
    python -m scripts.ingest_production --dry-run          # Preview without writing
    python -m scripts.ingest_production                    # Full ingestion
    python -m scripts.ingest_production --entity sessions  # Ingest only sessions
    python -m scripts.ingest_production --clear            # Clear v2 collections first
"""

import asyncio
import argparse
import json
import sys
import os
import time
import uuid
from typing import Any

sys.path.append(os.getcwd())

from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
from qdrant_client.http.models import (
    PointStruct,
    Distance,
    VectorParams,
    PayloadSchemaType,
)

from src.config import settings
from src.services.qdrant import get_qdrant_service, COLLECTIONS
from src.services.embedding import get_embedding_service
from src.services.directus import DirectusClient
from src.search.facet_config import load_facet_config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Production ETL 2025 event_id used in v1 Qdrant for filtering
EVENT_ID = "etl-2025"

# Facet keys matching production vector_profile schema
PROFILE_FACET_KEYS = [
    "buying_intent",
    "selling_intent",
    "seeking_to_meet",
    "i_am_this_person",
    "services_seeking",
    "services_providing",
    "challenges_facing",
    "problems_i_solve",
]

# Session facet keys (LLM-generated)
SESSION_FACET_KEYS = [
    "session_topic",
    "target_audience",
    "learning_outcomes",
    "industry_relevance",
    "problems_addressed",
    "technologies_covered",
]

# Speaker facet keys (LLM-generated)
SPEAKER_FACET_KEYS = [
    "speaker_expertise",
    "speaking_topics",
    "audience_value",
    "industry_experience",
    "problems_they_solve",
]

# Batch sizes
EMBEDDING_BATCH_SIZE = 50  # OpenAI batch embedding limit
QDRANT_UPSERT_BATCH_SIZE = 100
LLM_CONCURRENCY = 5  # Max concurrent LLM calls for facet generation


# ---------------------------------------------------------------------------
# Directus Client (standalone, not using singleton since this is a script)
# ---------------------------------------------------------------------------
class ProductionDirectusClient:
    """Minimal Directus client for ETL. Uses httpx directly."""

    def __init__(self):
        import httpx

        self.base_url = settings.directus_url
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {settings.directus_api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    async def _paginated_fetch(
        self, collection: str, fields: str = "*", batch_size: int = 500
    ) -> list[dict]:
        """Fetch all records from a collection with pagination."""
        all_records: list[dict] = []
        offset = 0
        while True:
            response = await self.client.get(
                f"/items/{collection}",
                params={
                    "limit": batch_size,
                    "offset": offset,
                    "fields": fields,
                },
            )
            response.raise_for_status()
            batch = response.json().get("data", [])
            if not batch:
                break
            all_records.extend(batch)
            if len(batch) < batch_size:
                break
            offset += batch_size
            print(f"    Fetched {len(all_records)} {collection} records so far...")
        return all_records

    async def get_exhibitors(self) -> list[dict]:
        return await self._paginated_fetch("exhibitor")

    async def get_sessions(self) -> list[dict]:
        return await self._paginated_fetch("session")

    async def get_speakers(self) -> list[dict]:
        return await self._paginated_fetch("speaker")

    async def get_user_profiles(self) -> list[dict]:
        return await self._paginated_fetch("user_profile")

    async def get_general_info(self) -> list[dict]:
        return await self._paginated_fetch("general_info")

    async def close(self):
        await self.client.aclose()


# ---------------------------------------------------------------------------
# LLM Facet Generation (for sessions and speakers without vector_profile)
# ---------------------------------------------------------------------------
async def generate_session_facets(
    anthropic_client: AsyncAnthropic,
    session: dict,
    semaphore: asyncio.Semaphore,
) -> dict[str, str]:
    """Generate faceted text for a session using Claude Haiku."""
    name = session.get("name") or session.get("title") or "Unknown Session"
    description = session.get("description") or ""
    speakers = session.get("speakers") or []
    location = session.get("location") or ""
    session_type = session.get("type") or ""

    prompt = f"""Generate faceted search descriptions for this conference session.
Return a JSON object with exactly these keys, each containing 1-3 sentences of descriptive text:

Session: {name}
Type: {session_type}
Location: {location}
Description: {description}
Speakers: {json.dumps(speakers) if isinstance(speakers, list) else str(speakers)}

Required JSON keys:
- "session_topic": Core subject matter and themes covered
- "target_audience": Who would benefit most from attending (roles, experience levels)
- "learning_outcomes": Key takeaways, skills, or knowledge gained
- "industry_relevance": Which industries or sectors this is relevant to
- "problems_addressed": Business or technical challenges this session helps solve
- "technologies_covered": Specific technologies, tools, or platforms discussed

Return ONLY valid JSON, no markdown or explanation."""

    async with semaphore:
        try:
            response = await anthropic_client.messages.create(
                model=settings.anthropic_haiku_model,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Parse JSON, handle potential markdown wrapping
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            facets = json.loads(text)
            # Ensure all keys present
            for key in SESSION_FACET_KEYS:
                if key not in facets:
                    facets[key] = f"{name}: {description[:100]}"
            return facets
        except Exception as e:
            print(f"    WARNING: LLM facet generation failed for session '{name}': {e}")
            # Fallback: use description for all facets
            fallback_text = f"{name}. {description}" if description else name
            return {key: fallback_text for key in SESSION_FACET_KEYS}


async def generate_speaker_facets(
    anthropic_client: AsyncAnthropic,
    speaker: dict,
    semaphore: asyncio.Semaphore,
) -> dict[str, str]:
    """Generate faceted text for a speaker using Claude Haiku."""
    name = (
        f"{speaker.get('first_name', '')} {speaker.get('last_name', '')}".strip()
        or speaker.get("name", "Unknown Speaker")
    )
    job_title = speaker.get("job_title") or speaker.get("title") or ""
    company = speaker.get("company") or ""
    bio = speaker.get("description") or speaker.get("bio") or ""

    prompt = f"""Generate faceted search descriptions for this conference speaker.
Return a JSON object with exactly these keys, each containing 1-3 sentences of descriptive text:

Speaker: {name}
Job Title: {job_title}
Company: {company}
Bio: {bio}

Required JSON keys:
- "speaker_expertise": Areas of professional expertise and specialization
- "speaking_topics": Topics and themes this speaker covers in talks
- "audience_value": What value and insights attendees gain from this speaker
- "industry_experience": Industries and sectors where this speaker has experience
- "problems_they_solve": Challenges and problems their expertise addresses

Return ONLY valid JSON, no markdown or explanation."""

    async with semaphore:
        try:
            response = await anthropic_client.messages.create(
                model=settings.anthropic_haiku_model,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            facets = json.loads(text)
            for key in SPEAKER_FACET_KEYS:
                if key not in facets:
                    facets[key] = f"{name}, {job_title} at {company}. {bio[:100]}"
            return facets
        except Exception as e:
            print(f"    WARNING: LLM facet generation failed for speaker '{name}': {e}")
            fallback_text = (
                f"{name}, {job_title} at {company}. {bio}"
                if bio
                else f"{name}, {job_title}"
            )
            return {key: fallback_text for key in SPEAKER_FACET_KEYS}


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------
async def batch_embed(
    embedding_service: Any,
    texts: list[str],
    batch_size: int = EMBEDDING_BATCH_SIZE,
) -> list[list[float]]:
    """Embed texts in batches to respect API limits."""
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        embeddings = await embedding_service.embed_batch(batch)
        all_embeddings.extend(embeddings)
        if i + batch_size < len(texts):
            print(f"      Embedded {i + batch_size}/{len(texts)} texts...")
    return all_embeddings


# ---------------------------------------------------------------------------
# Ingestion functions
# ---------------------------------------------------------------------------
async def ingest_exhibitors(
    directus: ProductionDirectusClient,
    qdrant: Any,
    embedding_service: Any,
    dry_run: bool = False,
) -> dict[str, int]:
    """Ingest exhibitors with 8 facets from vector_profile."""
    print("\n" + "=" * 50)
    print("  EXHIBITORS")
    print("=" * 50)

    exhibitors = await directus.get_exhibitors()
    print(f"  Fetched {len(exhibitors)} exhibitors from Directus")

    # Filter to those with vector_profile
    with_profile = [e for e in exhibitors if e.get("vector_profile")]
    without_profile = [e for e in exhibitors if not e.get("vector_profile")]
    print(f"  With vector_profile: {len(with_profile)}")
    print(f"  Without vector_profile: {len(without_profile)} (will be skipped)")

    if dry_run:
        print("  [DRY RUN] Would ingest:")
        print(f"    Master vectors: {len(with_profile)}")
        print(f"    Facet vectors: {len(with_profile) * 8}")
        return {"master": len(with_profile), "facets": len(with_profile) * 8}

    master_points: list[PointStruct] = []
    facet_points: list[PointStruct] = []

    # Collect all texts for batch embedding
    master_texts: list[str] = []
    facet_texts: list[str] = []
    facet_metadata: list[dict] = []  # Track which entity/facet each text belongs to

    for exh in with_profile:
        entity_id = exh.get("id", str(uuid.uuid4()))
        vp = exh["vector_profile"]
        if isinstance(vp, str):
            vp = json.loads(vp)

        name = exh.get("name") or exh.get("company_name") or "Unknown"
        description = exh.get("description") or ""

        # Master text: combine name + all facet texts
        facet_values = [vp.get(k, "") for k in PROFILE_FACET_KEYS if vp.get(k)]
        master_text = f"{name}. {description}. {' '.join(facet_values)}"[:2000]
        master_texts.append(master_text)

        base_payload = {
            "entity_id": str(entity_id),
            "conference_id": EVENT_ID,
            "name": name,
            "booth_number": exh.get("booth_number") or exh.get("stand_number") or "",
            "type": "exhibitor",
            "description": (description or "")[:500],
        }

        # Track master metadata
        facet_metadata.append({"type": "master", "payload": base_payload})

        # Facet texts
        for key in PROFILE_FACET_KEYS:
            text = vp.get(key, "")
            if text and len(text) >= 10:
                facet_texts.append(text)
                facet_metadata.append(
                    {
                        "type": "facet",
                        "payload": {
                            **base_payload,
                            "facet_key": key,
                            "facet_text": text[:500],
                        },
                    }
                )

    # Batch embed everything
    print(f"  Embedding {len(master_texts)} master + {len(facet_texts)} facet texts...")
    all_texts = master_texts + facet_texts
    all_embeddings = await batch_embed(embedding_service, all_texts)

    # Split embeddings back
    master_embeddings = all_embeddings[: len(master_texts)]
    facet_embeddings = all_embeddings[len(master_texts) :]

    # Create master points
    for i, emb in enumerate(master_embeddings):
        payload = facet_metadata[i]["payload"]
        master_points.append(
            PointStruct(id=str(uuid.uuid4()), vector=emb, payload=payload)
        )

    # Create facet points
    facet_meta_offset = len(master_texts)
    for i, emb in enumerate(facet_embeddings):
        payload = facet_metadata[facet_meta_offset + i]["payload"]
        facet_points.append(
            PointStruct(id=str(uuid.uuid4()), vector=emb, payload=payload)
        )

    # Upsert to Qdrant
    print(
        f"  Upserting {len(master_points)} master + {len(facet_points)} facet points..."
    )
    for i in range(0, len(master_points), QDRANT_UPSERT_BATCH_SIZE):
        batch = master_points[i : i + QDRANT_UPSERT_BATCH_SIZE]
        await qdrant.upsert_points("exhibitors_master", batch)
    for i in range(0, len(facet_points), QDRANT_UPSERT_BATCH_SIZE):
        batch = facet_points[i : i + QDRANT_UPSERT_BATCH_SIZE]
        await qdrant.upsert_points("exhibitors_facets", batch)

    print(f"  Done! Master: {len(master_points)}, Facets: {len(facet_points)}")
    return {"master": len(master_points), "facets": len(facet_points)}


async def ingest_attendees(
    directus: ProductionDirectusClient,
    qdrant: Any,
    embedding_service: Any,
    dry_run: bool = False,
    limit: int = 0,
) -> dict[str, int]:
    """Ingest attendees with 8 facets from vector_profile."""
    print("\n" + "=" * 50)
    print("  ATTENDEES")
    print("=" * 50)

    profiles = await directus.get_user_profiles()
    print(f"  Fetched {len(profiles)} user profiles from Directus")

    with_profile = [p for p in profiles if p.get("vector_profile")]
    without_profile = [p for p in profiles if not p.get("vector_profile")]
    print(f"  With vector_profile: {len(with_profile)}")
    print(f"  Without vector_profile: {len(without_profile)} (will be skipped)")

    if limit > 0:
        with_profile = with_profile[:limit]
        print(f"  Limited to: {len(with_profile)} profiles")

    if dry_run:
        print("  [DRY RUN] Would ingest:")
        print(f"    Master vectors: {len(with_profile)}")
        est_facets = len(with_profile) * 8  # Approximate
        print(f"    Facet vectors: ~{est_facets}")
        return {"master": len(with_profile), "facets": est_facets}

    master_points: list[PointStruct] = []
    facet_points: list[PointStruct] = []

    # Process in chunks to manage memory (3500+ records)
    chunk_size = 200
    total_master = 0
    total_facets = 0

    for chunk_start in range(0, len(with_profile), chunk_size):
        chunk = with_profile[chunk_start : chunk_start + chunk_size]
        chunk_num = chunk_start // chunk_size + 1
        total_chunks = (len(with_profile) + chunk_size - 1) // chunk_size
        print(
            f"\n  Processing chunk {chunk_num}/{total_chunks} ({len(chunk)} profiles)..."
        )

        master_texts: list[str] = []
        facet_texts: list[str] = []
        chunk_master_meta: list[dict] = []
        chunk_facet_meta: list[dict] = []

        for profile in chunk:
            entity_id = profile.get("id", str(uuid.uuid4()))
            vp = profile["vector_profile"]
            if isinstance(vp, str):
                vp = json.loads(vp)

            first_name = profile.get("first_name") or ""
            last_name = profile.get("last_name") or ""
            name = f"{first_name} {last_name}".strip() or "Unknown"
            company = profile.get("company") or ""
            job_title = profile.get("job_title") or ""

            # Master text
            facet_values = [vp.get(k, "") for k in PROFILE_FACET_KEYS if vp.get(k)]
            master_text = f"{name}, {job_title} at {company}. {' '.join(facet_values)}"[
                :2000
            ]
            master_texts.append(master_text)

            base_payload = {
                "entity_id": str(entity_id),
                "conference_id": EVENT_ID,
                "name": name,
                "company": company,
                "job_title": job_title,
                "type": "attendee",
            }
            chunk_master_meta.append({"payload": base_payload})

            # Facet texts
            for key in PROFILE_FACET_KEYS:
                text = vp.get(key, "")
                if text and len(text) >= 10:
                    facet_texts.append(text)
                    chunk_facet_meta.append(
                        {
                            "payload": {
                                **base_payload,
                                "facet_key": key,
                                "facet_text": text[:500],
                            },
                        }
                    )

        # Batch embed this chunk
        print(
            f"    Embedding {len(master_texts)} master + {len(facet_texts)} facet texts..."
        )
        all_texts = master_texts + facet_texts
        if not all_texts:
            continue
        all_embeddings = await batch_embed(embedding_service, all_texts)

        master_embeddings = all_embeddings[: len(master_texts)]
        facet_embeddings = all_embeddings[len(master_texts) :]

        # Build points
        chunk_master_points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=emb,
                payload=chunk_master_meta[i]["payload"],
            )
            for i, emb in enumerate(master_embeddings)
        ]
        chunk_facet_points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=emb,
                payload=chunk_facet_meta[i]["payload"],
            )
            for i, emb in enumerate(facet_embeddings)
        ]

        # Upsert this chunk
        print(
            f"    Upserting {len(chunk_master_points)} master + {len(chunk_facet_points)} facet points..."
        )
        for i in range(0, len(chunk_master_points), QDRANT_UPSERT_BATCH_SIZE):
            batch = chunk_master_points[i : i + QDRANT_UPSERT_BATCH_SIZE]
            await qdrant.upsert_points("attendees_master", batch)
        for i in range(0, len(chunk_facet_points), QDRANT_UPSERT_BATCH_SIZE):
            batch = chunk_facet_points[i : i + QDRANT_UPSERT_BATCH_SIZE]
            await qdrant.upsert_points("attendees_facets", batch)

        total_master += len(chunk_master_points)
        total_facets += len(chunk_facet_points)
        print(
            f"    Chunk done. Running total: {total_master} master, {total_facets} facets"
        )

    print(f"\n  Done! Master: {total_master}, Facets: {total_facets}")
    return {"master": total_master, "facets": total_facets}


async def ingest_sessions(
    directus: ProductionDirectusClient,
    qdrant: Any,
    embedding_service: Any,
    anthropic_client: AsyncAnthropic,
    dry_run: bool = False,
) -> dict[str, int]:
    """Ingest sessions with LLM-generated facets."""
    print("\n" + "=" * 50)
    print("  SESSIONS")
    print("=" * 50)

    sessions = await directus.get_sessions()
    print(f"  Fetched {len(sessions)} sessions from Directus")

    if dry_run:
        print("  [DRY RUN] Would generate facets for all sessions via LLM")
        print(f"    Master vectors: {len(sessions)}")
        print(f"    Facet vectors: {len(sessions) * len(SESSION_FACET_KEYS)}")
        print(f"    LLM calls needed: {len(sessions)}")
        return {
            "master": len(sessions),
            "facets": len(sessions) * len(SESSION_FACET_KEYS),
        }

    # Generate facets via LLM
    print(f"  Generating facets for {len(sessions)} sessions via LLM...")
    semaphore = asyncio.Semaphore(LLM_CONCURRENCY)
    facet_tasks = [
        generate_session_facets(anthropic_client, session, semaphore)
        for session in sessions
    ]
    all_facets = await asyncio.gather(*facet_tasks)
    print(f"  Generated facets for {len(all_facets)} sessions")

    # Prepare texts for embedding
    master_texts: list[str] = []
    facet_texts: list[str] = []
    master_meta: list[dict] = []
    facet_meta: list[dict] = []

    for session, facets in zip(sessions, all_facets):
        entity_id = session.get("id", str(uuid.uuid4()))
        name = session.get("name") or session.get("title") or "Unknown Session"
        description = session.get("description") or ""
        location = session.get("location") or ""
        session_type = session.get("type") or ""

        # Master text
        facet_values = [v for v in facets.values() if v]
        master_text = f"{name}. {description}. {' '.join(facet_values)}"[:2000]
        master_texts.append(master_text)

        base_payload = {
            "entity_id": str(entity_id),
            "conference_id": EVENT_ID,
            "name": name,
            "location": location,
            "session_type": session_type,
            "type": "session",
            "description": (description or "")[:500],
        }
        master_meta.append({"payload": base_payload})

        # Facet texts
        for key in SESSION_FACET_KEYS:
            text = facets.get(key, "")
            if text and len(text) >= 10:
                facet_texts.append(text)
                facet_meta.append(
                    {
                        "payload": {
                            **base_payload,
                            "facet_key": key,
                            "facet_text": text[:500],
                        },
                    }
                )

    # Embed
    print(f"  Embedding {len(master_texts)} master + {len(facet_texts)} facet texts...")
    all_texts = master_texts + facet_texts
    all_embeddings = await batch_embed(embedding_service, all_texts)

    master_embeddings = all_embeddings[: len(master_texts)]
    facet_embeddings = all_embeddings[len(master_texts) :]

    # Build points
    master_points = [
        PointStruct(id=str(uuid.uuid4()), vector=emb, payload=master_meta[i]["payload"])
        for i, emb in enumerate(master_embeddings)
    ]
    facet_points = [
        PointStruct(id=str(uuid.uuid4()), vector=emb, payload=facet_meta[i]["payload"])
        for i, emb in enumerate(facet_embeddings)
    ]

    # Upsert
    print(
        f"  Upserting {len(master_points)} master + {len(facet_points)} facet points..."
    )
    for i in range(0, len(master_points), QDRANT_UPSERT_BATCH_SIZE):
        batch = master_points[i : i + QDRANT_UPSERT_BATCH_SIZE]
        await qdrant.upsert_points("sessions_master", batch)
    for i in range(0, len(facet_points), QDRANT_UPSERT_BATCH_SIZE):
        batch = facet_points[i : i + QDRANT_UPSERT_BATCH_SIZE]
        await qdrant.upsert_points("sessions_facets", batch)

    print(f"  Done! Master: {len(master_points)}, Facets: {len(facet_points)}")
    return {"master": len(master_points), "facets": len(facet_points)}


async def ingest_speakers(
    directus: ProductionDirectusClient,
    qdrant: Any,
    embedding_service: Any,
    anthropic_client: AsyncAnthropic,
    dry_run: bool = False,
) -> dict[str, int]:
    """Ingest speakers with LLM-generated facets."""
    print("\n" + "=" * 50)
    print("  SPEAKERS")
    print("=" * 50)

    speakers = await directus.get_speakers()
    print(f"  Fetched {len(speakers)} speakers from Directus")

    if dry_run:
        print("  [DRY RUN] Would generate facets for all speakers via LLM")
        print(f"    Master vectors: {len(speakers)}")
        print(f"    Facet vectors: {len(speakers) * len(SPEAKER_FACET_KEYS)}")
        print(f"    LLM calls needed: {len(speakers)}")
        return {
            "master": len(speakers),
            "facets": len(speakers) * len(SPEAKER_FACET_KEYS),
        }

    # Generate facets via LLM
    print(f"  Generating facets for {len(speakers)} speakers via LLM...")
    semaphore = asyncio.Semaphore(LLM_CONCURRENCY)
    facet_tasks = [
        generate_speaker_facets(anthropic_client, speaker, semaphore)
        for speaker in speakers
    ]
    all_facets = await asyncio.gather(*facet_tasks)
    print(f"  Generated facets for {len(all_facets)} speakers")

    # Prepare texts
    master_texts: list[str] = []
    facet_texts: list[str] = []
    master_meta: list[dict] = []
    facet_meta: list[dict] = []

    for speaker, facets in zip(speakers, all_facets):
        entity_id = speaker.get("id", str(uuid.uuid4()))
        first_name = speaker.get("first_name") or ""
        last_name = speaker.get("last_name") or ""
        name = f"{first_name} {last_name}".strip() or speaker.get("name", "Unknown")
        job_title = speaker.get("job_title") or speaker.get("title") or ""
        company = speaker.get("company") or ""
        bio = speaker.get("description") or speaker.get("bio") or ""

        # Master text
        facet_values = [v for v in facets.values() if v]
        master_text = (
            f"{name}, {job_title} at {company}. {bio}. {' '.join(facet_values)}"[:2000]
        )
        master_texts.append(master_text)

        base_payload = {
            "entity_id": str(entity_id),
            "conference_id": EVENT_ID,
            "name": name,
            "job_title": job_title,
            "company": company,
            "type": "speaker",
            "description": (bio or "")[:500],
        }
        master_meta.append({"payload": base_payload})

        for key in SPEAKER_FACET_KEYS:
            text = facets.get(key, "")
            if text and len(text) >= 10:
                facet_texts.append(text)
                facet_meta.append(
                    {
                        "payload": {
                            **base_payload,
                            "facet_key": key,
                            "facet_text": text[:500],
                        },
                    }
                )

    # Embed
    print(f"  Embedding {len(master_texts)} master + {len(facet_texts)} facet texts...")
    all_texts = master_texts + facet_texts
    all_embeddings = await batch_embed(embedding_service, all_texts)

    master_embeddings = all_embeddings[: len(master_texts)]
    facet_embeddings = all_embeddings[len(master_texts) :]

    # Build points
    master_points = [
        PointStruct(id=str(uuid.uuid4()), vector=emb, payload=master_meta[i]["payload"])
        for i, emb in enumerate(master_embeddings)
    ]
    facet_points = [
        PointStruct(id=str(uuid.uuid4()), vector=emb, payload=facet_meta[i]["payload"])
        for i, emb in enumerate(facet_embeddings)
    ]

    # Upsert
    print(
        f"  Upserting {len(master_points)} master + {len(facet_points)} facet points..."
    )
    for i in range(0, len(master_points), QDRANT_UPSERT_BATCH_SIZE):
        batch = master_points[i : i + QDRANT_UPSERT_BATCH_SIZE]
        await qdrant.upsert_points("speakers_master", batch)
    for i in range(0, len(facet_points), QDRANT_UPSERT_BATCH_SIZE):
        batch = facet_points[i : i + QDRANT_UPSERT_BATCH_SIZE]
        await qdrant.upsert_points("speakers_facets", batch)

    print(f"  Done! Master: {len(master_points)}, Facets: {len(facet_points)}")
    return {"master": len(master_points), "facets": len(facet_points)}


# ---------------------------------------------------------------------------
# Clear v2 collections
# ---------------------------------------------------------------------------
async def clear_v2_collections(qdrant: Any):
    """Delete and recreate v2 collections. DOES NOT TOUCH v1 collections."""
    print("\n  Clearing v2 collections (creating fresh)...")
    v2_collections = list(COLLECTIONS.values())
    for name in v2_collections:
        try:
            exists = await qdrant.client.collection_exists(name)
            if exists:
                await qdrant.client.delete_collection(name)
                print(f"    Deleted: {name}")
        except Exception as e:
            print(f"    Warning: Could not delete {name}: {e}")

    # Recreate with correct dimensions
    for name in v2_collections:
        await qdrant.client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(
                size=settings.vector_size,
                distance=Distance.COSINE,
            ),
        )
        print(f"    Created: {name} (dims={settings.vector_size})")


async def create_payload_indexes(qdrant: Any):
    """Create keyword indexes on conference_id and facet_key for filtering performance."""
    print("\n  Creating payload indexes...")
    all_collections = list(COLLECTIONS.values())
    facet_collections = [c for c in all_collections if c.endswith("_facets")]

    # conference_id index on ALL collections (used in every query filter)
    for name in all_collections:
        try:
            await qdrant.client.create_payload_index(
                collection_name=name,
                field_name="conference_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            print(f"    Index: {name}.conference_id (keyword)")
        except Exception as e:
            # Index may already exist — that's fine
            if "already exists" in str(e).lower():
                print(f"    Index: {name}.conference_id (already exists)")
            else:
                print(f"    Warning: {name}.conference_id: {e}")

    # facet_key index on facet collections only (used in faceted search)
    for name in facet_collections:
        try:
            await qdrant.client.create_payload_index(
                collection_name=name,
                field_name="facet_key",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            print(f"    Index: {name}.facet_key (keyword)")
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"    Index: {name}.facet_key (already exists)")
            else:
                print(f"    Warning: {name}.facet_key: {e}")

    print("    Payload indexes ready.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main(
    dry_run: bool = False,
    clear: bool = False,
    entity: str | None = None,
    limit: int = 0,
):
    start_time = time.time()

    print("=" * 60)
    print("  ERLEAH v2 PRODUCTION DATA INGESTION")
    print("  ETL 2025 -> Qdrant v2 Collections")
    print("=" * 60)
    print(f"\n  Directus:  {settings.directus_url}")
    print(f"  Qdrant:    {settings.qdrant_url}")
    print(f"  Embedding: {settings.embedding_model} ({settings.vector_size} dims)")
    print(f"  Dry run:   {dry_run}")
    print(f"  Clear:     {clear}")
    print(f"  Entity:    {entity or 'all'}")

    # Initialize services
    directus = ProductionDirectusClient()
    qdrant = get_qdrant_service()
    embedding_service = get_embedding_service()
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        # Clear and recreate collections if requested
        if clear and not dry_run:
            await clear_v2_collections(qdrant)
        elif not dry_run:
            # Ensure collections exist with correct dimensions
            print("\n  Ensuring v2 collections exist...")
            await qdrant.ensure_collections()

        # Create payload indexes for filtering performance
        if not dry_run:
            await create_payload_indexes(qdrant)

        # Determine which entities to ingest
        entities_to_ingest = (
            [entity] if entity else ["exhibitors", "attendees", "sessions", "speakers"]
        )

        results: dict[str, dict[str, int]] = {}

        for entity_name in entities_to_ingest:
            if entity_name == "exhibitors":
                results["exhibitors"] = await ingest_exhibitors(
                    directus, qdrant, embedding_service, dry_run
                )
            elif entity_name == "attendees":
                results["attendees"] = await ingest_attendees(
                    directus, qdrant, embedding_service, dry_run, limit=limit
                )
            elif entity_name == "sessions":
                results["sessions"] = await ingest_sessions(
                    directus, qdrant, embedding_service, anthropic_client, dry_run
                )
            elif entity_name == "speakers":
                results["speakers"] = await ingest_speakers(
                    directus, qdrant, embedding_service, anthropic_client, dry_run
                )
            else:
                print(f"\n  Unknown entity type: {entity_name}")

        # Summary
        elapsed = time.time() - start_time
        total_master = sum(r.get("master", 0) for r in results.values())
        total_facets = sum(r.get("facets", 0) for r in results.values())

        print("\n" + "=" * 60)
        print("  INGESTION SUMMARY" + (" (DRY RUN)" if dry_run else ""))
        print("=" * 60)

        for entity_name, counts in results.items():
            print(
                f"  {entity_name:12s}: {counts['master']:>5d} master, {counts['facets']:>6d} facets"
            )

        print(
            f"\n  Total:         {total_master:>5d} master, {total_facets:>6d} facets"
        )
        print(f"  Grand total:   {total_master + total_facets} vectors")
        print(f"  Event ID:      {EVENT_ID}")
        print(f"  Elapsed:       {elapsed:.1f}s")

        if not dry_run:
            # Verify by counting points in collections
            print("\n  Verification — collection point counts:")
            for name in COLLECTIONS.values():
                try:
                    info = await qdrant.client.get_collection(name)
                    print(f"    {name:25s}: {info.points_count} points")
                except Exception:
                    print(f"    {name:25s}: (not found)")

        print("\n" + "=" * 60)

    finally:
        await directus.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest production ETL 2025 data into v2 Qdrant collections"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be ingested without writing",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete and recreate v2 collections before ingesting",
    )
    parser.add_argument(
        "--entity",
        choices=["exhibitors", "attendees", "sessions", "speakers"],
        help="Ingest only this entity type",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of records to ingest per entity (0 = all)",
    )
    args = parser.parse_args()

    asyncio.run(
        main(
            dry_run=args.dry_run, clear=args.clear, entity=args.entity, limit=args.limit
        )
    )
