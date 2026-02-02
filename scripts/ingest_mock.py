"""
Script này tạo dữ liệu giả và nạp vào Qdrant để test Agent.
Chạy bằng lệnh: python -m scripts.ingest_mock
"""

import asyncio
import uuid
import sys
import os

# Thêm thư mục gốc vào path để import được src
sys.path.append(os.getcwd())

from qdrant_client.http.models import PointStruct
from src.services.qdrant import get_qdrant_service
from src.services.embedding import get_embedding_service

# ID giả lập cho hội nghị
MOCK_CONFERENCE_ID = "conf-2024"

# Dữ liệu mẫu: Sessions
MOCK_SESSIONS = [
    {
        "title": "Future of AI in Healthcare",
        "description": "How AI is transforming diagnosis and patient care. Keynote speech.",
        "speaker": "Dr. Sarah Smith",
        "location": "Main Hall",
        "time": "10:00 AM",
    },
    {
        "title": "Python for Data Science Workshop",
        "description": "Hands-on workshop using Pandas and Scikit-learn for beginners.",
        "speaker": "Guido van Rossum",
        "location": "Room B",
        "time": "02:00 PM",
    },
    {
        "title": "Marketing in the Metaverse",
        "description": "Strategies for branding in virtual worlds.",
        "speaker": "Mark Zucker",
        "location": "Room C",
        "time": "11:00 AM",
    },
]

# Dữ liệu mẫu: Exhibitors
MOCK_EXHIBITORS = [
    {
        "name": "Nvidia",
        "description": "AI Computing, GPUs, and hardware for deep learning.",
        "booth": "A-01",
        "category": "Hardware",
    },
    {
        "name": "OpenAI",
        "description": "Creators of ChatGPT and GPT-4. AI research and deployment company.",
        "booth": "A-02",
        "category": "Software",
    },
    {
        "name": "Coffee Lovers",
        "description": "Free coffee for all attendees. Best espresso in town.",
        "booth": "Food Court",
        "category": "Food & Beverage",
    },
]


async def ingest():
    print("🚀 Starting Mock Ingestion...")

    qdrant = get_qdrant_service()
    embedding = get_embedding_service()

    # 1. Tạo Collections
    print("📦 Ensuring collections exist...")
    await qdrant.ensure_collections()

    # 2. Ingest Sessions
    print(f"📥 Ingesting {len(MOCK_SESSIONS)} sessions...")
    session_points = []
    for sess in MOCK_SESSIONS:
        # Tạo text để vector hóa (Kết hợp title + desc)
        text_to_embed = (
            f"{sess['title']}. {sess['description']} Speaker: {sess['speaker']}"
        )
        vector = await embedding.embed_text(text_to_embed)

        payload = {
            "entity_id": str(uuid.uuid4()),
            "conference_id": MOCK_CONFERENCE_ID,
            "title": sess["title"],
            "description": sess["description"],
            "speaker_name": sess["speaker"],
            "location": sess["location"],
            "start_time": sess["time"],
            "type": "session",
        }

        session_points.append(
            PointStruct(id=str(uuid.uuid4()), vector=vector, payload=payload)
        )

    # Nạp vào cả Master và Facets (để đơn giản hóa việc test)
    await qdrant.upsert_points("sessions_master", session_points)
    await qdrant.upsert_points("sessions_facets", session_points)

    # 3. Ingest Exhibitors
    print(f"📥 Ingesting {len(MOCK_EXHIBITORS)} exhibitors...")
    exhibitor_points = []
    for exh in MOCK_EXHIBITORS:
        text_to_embed = (
            f"{exh['name']}. {exh['description']} Category: {exh['category']}"
        )
        vector = await embedding.embed_text(text_to_embed)

        payload = {
            "entity_id": str(uuid.uuid4()),
            "conference_id": MOCK_CONFERENCE_ID,
            "name": exh["name"],
            "description": exh["description"],
            "booth_number": exh["booth"],
            "type": "exhibitor",
        }

        exhibitor_points.append(
            PointStruct(id=str(uuid.uuid4()), vector=vector, payload=payload)
        )

    await qdrant.upsert_points("exhibitors_master", exhibitor_points)
    await qdrant.upsert_points("exhibitors_facets", exhibitor_points)

    print("✅ Ingestion Complete! You can now query the agent.")
    print(f"👉 Use conference_id: '{MOCK_CONFERENCE_ID}' in your API requests.")


if __name__ == "__main__":
    asyncio.run(ingest())
