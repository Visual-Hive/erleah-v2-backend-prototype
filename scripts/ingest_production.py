"""Script to ingest production data with AUTO-FACET generation for Session/Speaker."""

import asyncio
import json
import os
import sys
import uuid
from typing import Any

sys.path.append(os.getcwd())

import httpx
import structlog
from qdrant_client.http.models import Distance, VectorParams, PointStruct

from src.config import settings
from src.services.embedding import get_embedding_service
from src.services.qdrant import get_qdrant_service
from src.agent.llm_registry import get_llm_registry
from langchain_core.messages import HumanMessage, SystemMessage

logger = structlog.get_logger()

# --- CONFIGURATION ---
EVENT_ID = "etl-2025"
QDRANT_UPSERT_BATCH_SIZE = 100
EMBEDDING_BATCH_SIZE = 50
MAX_CONCURRENT_LLM = 5  # Giới hạn số lượng call LLM song song

PROFILE_FACET_KEYS = [
    "buying_intent",
    "challenges_facing",
    "i_am_this_person",
    "problems_i_solve",
    "seeking_to_meet",
    "selling_intent",
    "services_providing",
    "services_seeking",
]
SESSION_FACET_KEYS = [
    "session_topic",
    "learning_outcomes",
    "target_audience",
    "industry_focus",
    "practical_applications",
    "speaker_expertise",
]
SPEAKER_FACET_KEYS = [
    "speaker_expertise",
    "speaker_background",
    "speaking_topics",
    "audience_value",
    "connect_with_me",
]

FACET_PROMPTS = {
    "session": """You are an event data expert. Extract 6 semantic facets from the session description below. 
Return ONLY valid JSON with these keys: {keys}.
If information is missing, use your best professional judgment to fill it based on the title/description.
Format the values as descriptive sentences.

Session Title: {name}
Description: {description}
""",
    "speaker": """You are an event data expert. Extract 5 semantic facets from the speaker bio below.
Return ONLY valid JSON with these keys: {keys}.
If information is missing, use your best professional judgment to fill it.
Format the values as descriptive sentences.

Speaker Name: {name}
Bio: {description}
""",
}


class AutoFacetGenerator:
    def __init__(self):
        # Chuyển sang dùng Haiku để bóc tách facets cho nhanh và chuẩn
        self.llm = get_llm_registry().get_model(
            "evaluate"
        )  # 'evaluate' node thường dùng Haiku
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)

    async def generate(self, entity_type: str, name: str, description: str) -> dict:
        if not description or len(description) < 20:
            return {}

        keys = SESSION_FACET_KEYS if entity_type == "session" else SPEAKER_FACET_KEYS
        prompt = FACET_PROMPTS[entity_type].format(
            name=name, description=description, keys=keys
        )

        async with self.semaphore:
            try:
                res = await self.llm.ainvoke([HumanMessage(content=prompt)])
                content = str(res.content).strip()
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                return json.loads(content)
            except Exception as e:
                logger.warning(f"  [llm] Failed to generate facets for {name}: {e}")
                return {}


class ProductionDirectusClient:
    def __init__(self):
        self.base_url = settings.directus_url
        self.headers = {"Authorization": f"Bearer {settings.directus_api_key}"}
        self._client = httpx.AsyncClient(
            base_url=self.base_url, headers=self.headers, timeout=60.0
        )

    async def get_items(self, collection: str, fields: str = "*", limit: int = 1000):
        try:
            res = await self._client.get(
                f"/items/{collection}", params={"fields": fields, "limit": limit}
            )
            res.raise_for_status()
            return res.json()["data"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403 and "vector_profile" in fields:
                fields_no_vp = fields.replace(",vector_profile", "")
                res = await self._client.get(
                    f"/items/{collection}",
                    params={"fields": fields_no_vp, "limit": limit},
                )
                res.raise_for_status()
                return res.json()["data"]
            raise e


async def batch_embed(embedding_service: Any, texts: list[str]) -> list[list[float]]:
    all_embeddings = []
    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i : i + EMBEDDING_BATCH_SIZE]
        embeddings = await embedding_service.embed_batch(batch)
        all_embeddings.extend(embeddings)
    return all_embeddings


async def ingest_entities(
    directus,
    qdrant_service,
    embedding_service,
    facet_gen,
    collection_name,
    facet_keys,
    entity_type,
):
    print(f"\n>>> INGESTING {entity_type.upper()}...")
    raw_items = await directus.get_items(collection_name, fields="*,vector_profile")
    # Process all items that have at least a name/title/company (or is an attendee)
    items_to_process = []
    for item in raw_items:
        name = item.get("company") or item.get("name") or item.get("title")
        if not name and entity_type == "attendee":
            # Try to get name from registration_profile for attendees
            rp = item.get("registration_profile")
            if isinstance(rp, str):
                try:
                    rp = json.loads(rp)
                except:
                    rp = {}

            if rp:
                name = (
                    str(rp.get("first_name", "")) + " " + str(rp.get("last_name", ""))
                ).strip()

            if not name:
                name = f"Attendee {str(item.get('id'))[:8]}"

        if name:
            item["_extracted_name"] = name
            items_to_process.append(item)

    if not items_to_process:
        print(f"    No items found to process for {entity_type}")
        return {"master": 0, "facets": 0}

    # Step 1: Generate missing facets in parallel
    print(f"    Checking/Generating facets for {len(items_to_process)} items...")

    async def _get_vp(item):
        name = item.get("_extracted_name") or "Unknown"
        description = item.get("description") or item.get("bio") or ""
        vp = item.get("vector_profile")

        if vp:
            if isinstance(vp, str):
                try:
                    return json.loads(vp)
                except:
                    pass
            else:
                return vp

        # Nếu là session/speaker và không có vp -> Auto gen
        if entity_type in ["session", "speaker"]:
            return await facet_gen.generate(entity_type, name, description)
        return {}

    vp_tasks = [_get_vp(item) for item in items_to_process]
    all_vps = await asyncio.gather(*vp_tasks)

    master_data = []
    facet_data = []

    for i, item in enumerate(items_to_process):
        vp = all_vps[i]
        name = item.get("_extracted_name") or "Unknown"
        description = item.get("description") or item.get("bio") or ""
        entity_id = item.get("id")

        base_payload = {
            "entity_id": str(entity_id),
            "conference_id": EVENT_ID,
            "name": name,
            "type": entity_type,
            "description": description[:1000],
        }
        if entity_type == "exhibitor":
            base_payload["booth_number"] = (
                item.get("booth_number") or item.get("stand_number") or ""
            )
        elif entity_type == "session":
            base_payload.update(
                {
                    "location": item.get("location") or "",
                    "start_time": item.get("start_date") or "",
                }
            )

        # Master record
        f_vals = [vp.get(k, "") for k in facet_keys if vp.get(k)]
        master_text = f"{name}. {description}. {' '.join(f_vals)}"[:2500]
        master_data.append((master_text, base_payload))

        # Facet records
        for key in facet_keys:
            txt = vp.get(key, "")
            if txt and len(txt) >= 5:
                facet_data.append(
                    (txt, {**base_payload, "facet_key": key, "facet_text": txt[:1000]})
                )

    # Step 2: Embed & Upsert
    print(
        f"    Embedding {len(master_data)} master + {len(facet_data)} facet records..."
    )
    m_texts = [d[0] for d in master_data]
    f_texts = [d[0] for d in facet_data]

    all_embs = await batch_embed(embedding_service, m_texts + f_texts)
    m_embs = all_embs[: len(m_texts)]
    f_embs = all_embs[len(m_texts) :]

    m_points = [
        PointStruct(id=str(uuid.uuid4()), vector=m_embs[i], payload=master_data[i][1])
        for i in range(len(m_embs))
    ]
    f_points = [
        PointStruct(id=str(uuid.uuid4()), vector=f_embs[i], payload=facet_data[i][1])
        for i in range(len(f_embs))
    ]

    mapping = {
        "exhibitor": ("exhibitors_master", "exhibitors_facets"),
        "session": ("sessions_master", "sessions_facets"),
        "speaker": ("speakers_master", "speakers_facets"),
        "attendee": ("attendees_master", "attendees_facets"),
    }
    m_coll, f_coll = mapping.get(entity_type)

    for i in range(0, len(m_points), QDRANT_UPSERT_BATCH_SIZE):
        await qdrant_service.client.upsert(
            m_coll, m_points[i : i + QDRANT_UPSERT_BATCH_SIZE]
        )
    if f_points:
        for i in range(0, len(f_points), QDRANT_UPSERT_BATCH_SIZE):
            await qdrant_service.client.upsert(
                f_coll, f_points[i : i + QDRANT_UPSERT_BATCH_SIZE]
            )

    print(f"    Done: {len(m_points)} master, {len(f_points)} facets")
    return {"master": len(m_points), "facets": len(f_points)}


async def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--entity",
        choices=["exhibitors", "sessions", "speakers", "attendees", "all"],
        default="all",
    )
    parser.add_argument("--clear", action="store_true")
    args = parser.parse_args()

    directus = ProductionDirectusClient()
    qdrant_service = get_qdrant_service()
    embedding_service = get_embedding_service()
    facet_gen = AutoFacetGenerator()

    colls = [
        "sessions_master",
        "sessions_facets",
        "exhibitors_master",
        "exhibitors_facets",
        "speakers_master",
        "speakers_facets",
        "attendees_master",
        "attendees_facets",
    ]

    if args.clear:
        print("Clearing collections...")
        for c in colls:
            try:
                await qdrant_service.client.delete_collection(c)
            except:
                pass
            await qdrant_service.client.create_collection(
                c, vectors_config=VectorParams(size=3072, distance=Distance.COSINE)
            )

    stats = {}
    entities = ["exhibitor", "session", "speaker", "user_profile"]
    if args.entity != "all":
        entities = [args.entity[:-1] if args.entity.endswith("s") else args.entity]
        if args.entity == "attendees":
            entities = ["user_profile"]

    for ent in entities:
        f_keys = (
            PROFILE_FACET_KEYS
            if ent in ["exhibitor", "user_profile"]
            else (SESSION_FACET_KEYS if ent == "session" else SPEAKER_FACET_KEYS)
        )
        e_type = "attendee" if ent == "user_profile" else ent
        stats[e_type] = await ingest_entities(
            directus, qdrant_service, embedding_service, facet_gen, ent, f_keys, e_type
        )

    print(f"\nFinal Stats: {json.dumps(stats, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
