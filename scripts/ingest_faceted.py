#!/usr/bin/env python3
"""
NOTE: This script is superseded by scripts/seed_data.py which adds:
  - Attendees with paired facet matching (the "secret sauce")
  - Multi-conference isolation (conf-2024, conf-2025)
  - Edge cases (sparse facets, empty facets, non-tech domains)
  - Directus seeding (user profiles, conversations, messages)
  - 18 predefined test scenarios
  - Generic ingestion function (no per-entity-type duplication)

Use: python -m scripts.seed_data
     python -m scripts.seed_data --dry-run

This script remains functional for quick exhibitor/session/speaker-only ingestion.

Original description:
  Script ingest data với FULL FACETS cho multi-faceted search.
  Mỗi entity tạo nhiều vectors với facet_key khác nhau.

Usage:
    python -m scripts.ingest_faceted
    python -m scripts.ingest_faceted --clear  # Xóa data cũ trước khi ingest
"""

import asyncio
import argparse
import uuid
import sys
import os

sys.path.append(os.getcwd())

from qdrant_client.http.models import PointStruct
from src.services.qdrant import get_qdrant_service
from src.services.embedding import get_embedding_service

CONFERENCE_ID = "conf-2024"

# ============================================================
# EXHIBITORS - 6 facets mỗi exhibitor
# ============================================================
EXHIBITORS = [
    {
        "name": "Nvidia",
        "booth": "A-01",
        "facets": {
            "what_they_sell": "AI GPUs, CUDA computing platform, deep learning accelerators, RTX graphics cards, data center solutions, edge AI devices",
            "who_they_target": "AI researchers, machine learning engineers, data scientists, game developers, autonomous vehicle companies, cloud providers",
            "their_expertise": "GPU architecture, parallel computing, deep learning frameworks, computer vision, natural language processing, robotics",
            "industries_they_serve": "Healthcare AI, autonomous vehicles, gaming, financial services, scientific research, cloud computing",
            "company_size_focus": "Enterprise companies, research institutions, startups with AI focus, government agencies",
            "geographic_focus": "Global presence, strong in North America, Europe, and Asia Pacific",
        },
    },
    {
        "name": "OpenAI",
        "booth": "A-02",
        "facets": {
            "what_they_sell": "GPT-4 API, ChatGPT Enterprise, DALL-E image generation, Whisper speech recognition, embeddings API, fine-tuning services",
            "who_they_target": "Software developers, product managers, AI startups, enterprise companies, content creators, researchers",
            "their_expertise": "Large language models, generative AI, reinforcement learning from human feedback, AI safety, multimodal AI",
            "industries_they_serve": "Technology, media and entertainment, education, healthcare, legal, customer service, marketing",
            "company_size_focus": "Startups to Fortune 500, developers and enterprises of all sizes",
            "geographic_focus": "Primarily US and Europe, expanding globally",
        },
    },
    {
        "name": "Coffee Lovers Cafe",
        "booth": "Food Court F-01",
        "facets": {
            "what_they_sell": "Premium espresso, specialty coffee, cold brew, pastries, healthy snacks, conference catering",
            "who_they_target": "Conference attendees, networking groups, early risers, afternoon break seekers",
            "their_expertise": "Barista craftsmanship, quick service, bulk orders, custom coffee blends",
            "industries_they_serve": "Events and conferences, corporate offices, hospitality",
            "company_size_focus": "Events of all sizes, from small meetups to large conferences",
            "geographic_focus": "Local presence at major tech conferences",
        },
    },
    {
        "name": "AWS",
        "booth": "A-03",
        "facets": {
            "what_they_sell": "Cloud computing infrastructure, SageMaker ML platform, Bedrock generative AI, Lambda serverless, S3 storage, EC2 compute",
            "who_they_target": "CTOs, cloud architects, DevOps engineers, data engineers, ML teams, startups",
            "their_expertise": "Cloud infrastructure, serverless computing, managed AI/ML services, scalability, security",
            "industries_they_serve": "Financial services, healthcare, retail, media, government, startups",
            "company_size_focus": "From solo developers to largest enterprises, pay-as-you-go model",
            "geographic_focus": "Global with regions in Americas, Europe, Asia Pacific, Middle East",
        },
    },
    {
        "name": "Hugging Face",
        "booth": "B-01",
        "facets": {
            "what_they_sell": "Model hub, Transformers library, Inference API, AutoTrain, Spaces hosting, enterprise solutions",
            "who_they_target": "ML engineers, NLP researchers, open source contributors, AI startups, enterprise AI teams",
            "their_expertise": "Open source ML, transformer models, NLP, computer vision, model hosting, collaborative ML",
            "industries_they_serve": "Technology, research, education, healthcare NLP, financial text analysis",
            "company_size_focus": "Open source community, startups, research labs, enterprises",
            "geographic_focus": "Global open source community, offices in US and France",
        },
    },
    {
        "name": "Anthropic",
        "booth": "A-04",
        "facets": {
            "what_they_sell": "Claude AI assistant, Claude API, enterprise solutions, constitutional AI consulting",
            "who_they_target": "Developers building AI products, enterprises needing safe AI, researchers studying AI alignment",
            "their_expertise": "AI safety, constitutional AI, large language models, interpretability research, RLHF",
            "industries_they_serve": "Technology, legal, healthcare, education, customer support, content moderation",
            "company_size_focus": "Startups to enterprises, focus on responsible AI adoption",
            "geographic_focus": "US-based with global API availability",
        },
    },
    {
        "name": "Weights & Biases",
        "booth": "B-02",
        "facets": {
            "what_they_sell": "ML experiment tracking, model versioning, dataset management, hyperparameter sweeps, collaborative dashboards",
            "who_they_target": "ML engineers, data scientists, research teams, MLOps engineers",
            "their_expertise": "Experiment tracking, model debugging, ML workflow optimization, team collaboration",
            "industries_they_serve": "AI research, autonomous vehicles, robotics, healthcare ML, any ML-heavy organization",
            "company_size_focus": "From individual researchers to large ML teams",
            "geographic_focus": "Global SaaS platform, self-hosted options available",
        },
    },
    {
        "name": "Scale AI",
        "booth": "B-03",
        "facets": {
            "what_they_sell": "Data labeling services, RLHF data collection, synthetic data generation, model evaluation",
            "who_they_target": "ML teams needing training data, autonomous vehicle companies, computer vision teams",
            "their_expertise": "High-quality data annotation, human feedback collection, data quality assurance",
            "industries_they_serve": "Autonomous vehicles, robotics, e-commerce, government, generative AI",
            "company_size_focus": "Enterprises with large data labeling needs",
            "geographic_focus": "US-based with global labeling workforce",
        },
    },
]

# ============================================================
# SESSIONS - 6 facets mỗi session
# ============================================================
SESSIONS = [
    {
        "title": "Future of AI in Healthcare",
        "speaker": "Dr. Sarah Smith",
        "location": "Main Hall",
        "time": "10:00 AM",
        "facets": {
            "session_topic": "AI diagnostics, medical imaging analysis, drug discovery, patient care optimization, clinical decision support",
            "target_audience": "Healthcare professionals, medical AI researchers, hospital IT directors, healthtech startup founders",
            "learning_outcomes": "Understand FDA approval for AI devices, implement responsible medical AI, navigate healthcare data privacy",
            "industry_focus": "Healthcare, pharmaceuticals, medical devices, health insurance, telemedicine",
            "difficulty_level": "Intermediate to advanced, assumes basic ML knowledge",
            "session_format": "Keynote presentation with live demos and Q&A",
        },
    },
    {
        "title": "Python for Data Science Workshop",
        "speaker": "Guido van Rossum",
        "location": "Room B",
        "time": "02:00 PM",
        "facets": {
            "session_topic": "Pandas data manipulation, NumPy arrays, Scikit-learn basics, data visualization with matplotlib, Jupyter notebooks",
            "target_audience": "Beginning data scientists, Python developers moving to ML, analysts learning programming",
            "learning_outcomes": "Build end-to-end data pipelines, create ML models, visualize results, handle real datasets",
            "industry_focus": "Any industry using data analysis, technology, finance, marketing analytics",
            "difficulty_level": "Beginner friendly, no prior ML experience needed",
            "session_format": "Hands-on workshop with coding exercises, bring your laptop",
        },
    },
    {
        "title": "Marketing in the Metaverse",
        "speaker": "Mark Zucker",
        "location": "Room C",
        "time": "11:00 AM",
        "facets": {
            "session_topic": "Virtual world branding, immersive advertising, avatar marketing, virtual events, NFT campaigns",
            "target_audience": "Marketing directors, brand managers, digital marketing specialists, innovation teams",
            "learning_outcomes": "Create metaverse marketing strategy, measure virtual engagement, build immersive brand experiences",
            "industry_focus": "Retail, fashion, entertainment, gaming, luxury brands",
            "difficulty_level": "Intermediate, assumes familiarity with digital marketing",
            "session_format": "Presentation with case studies and VR demo stations",
        },
    },
    {
        "title": "Building Production LLM Applications",
        "speaker": "Harrison Chase",
        "location": "Main Hall",
        "time": "02:00 PM",
        "facets": {
            "session_topic": "LangChain framework, RAG architectures, prompt engineering, agent systems, LLM deployment patterns",
            "target_audience": "Backend developers, ML engineers, technical architects building AI products",
            "learning_outcomes": "Design robust LLM pipelines, implement RAG systems, handle hallucinations, optimize costs",
            "industry_focus": "Software development, SaaS, enterprise AI, developer tools",
            "difficulty_level": "Advanced, requires Python experience and LLM familiarity",
            "session_format": "Technical deep-dive with live coding and architecture diagrams",
        },
    },
    {
        "title": "AI Safety and Alignment",
        "speaker": "Dr. Amanda Chen",
        "location": "Room A",
        "time": "04:00 PM",
        "facets": {
            "session_topic": "AI alignment research, constitutional AI, RLHF, interpretability, AI governance, existential risk",
            "target_audience": "AI researchers, policy makers, ethics officers, ML engineers concerned with safety",
            "learning_outcomes": "Understand current alignment techniques, evaluate AI risks, implement safety measures",
            "industry_focus": "AI research, government policy, technology ethics, academia",
            "difficulty_level": "Intermediate, mix of technical and policy content",
            "session_format": "Panel discussion with leading AI safety researchers",
        },
    },
    {
        "title": "Startup Pitch Competition",
        "speaker": "Multiple Founders",
        "location": "Main Hall",
        "time": "05:00 PM",
        "facets": {
            "session_topic": "AI startup pitches, venture funding, product demos, market analysis, competitive positioning",
            "target_audience": "Investors, startup founders, aspiring entrepreneurs, corporate innovation scouts",
            "learning_outcomes": "Discover emerging AI startups, understand VC perspectives, network with founders",
            "industry_focus": "Venture capital, startups, corporate innovation, technology",
            "difficulty_level": "All levels, business focused rather than technical",
            "session_format": "5-minute pitches followed by investor Q&A and audience voting",
        },
    },
    {
        "title": "MLOps Best Practices",
        "speaker": "Chip Huyen",
        "location": "Room B",
        "time": "11:00 AM",
        "facets": {
            "session_topic": "Model deployment, CI/CD for ML, monitoring in production, feature stores, model versioning",
            "target_audience": "ML engineers, DevOps engineers, data platform teams, technical leads",
            "learning_outcomes": "Build reliable ML pipelines, implement model monitoring, reduce deployment friction",
            "industry_focus": "Technology companies, any organization deploying ML at scale",
            "difficulty_level": "Advanced, assumes production engineering experience",
            "session_format": "Technical workshop with real-world case studies",
        },
    },
    {
        "title": "Computer Vision for Autonomous Vehicles",
        "speaker": "Dr. Andrej Karpathy",
        "location": "Room A",
        "time": "10:00 AM",
        "facets": {
            "session_topic": "Perception systems, sensor fusion, 3D object detection, neural network architectures for driving",
            "target_audience": "Autonomous vehicle engineers, computer vision researchers, robotics engineers",
            "learning_outcomes": "Understand AV perception stack, implement detection models, handle edge cases",
            "industry_focus": "Autonomous vehicles, robotics, transportation, logistics",
            "difficulty_level": "Advanced, deep learning expertise required",
            "session_format": "Technical lecture with visualizations from real driving data",
        },
    },
]

# ============================================================
# SPEAKERS - 5 facets mỗi speaker
# ============================================================
SPEAKERS = [
    {
        "name": "Dr. Sarah Smith",
        "title": "Chief AI Officer, MedTech Corp",
        "facets": {
            "speaker_expertise": "Healthcare AI, FDA regulatory compliance, medical imaging, clinical decision support systems",
            "speaking_topics": "AI in healthcare, responsible medical AI, bridging research and clinical practice",
            "audience_value": "Learn from 15 years of healthcare AI implementation, avoid common regulatory pitfalls",
            "speaker_background": "MD/PhD Stanford, former Google Health, 50+ published papers on medical AI",
            "connect_with_me": "Healthcare AI partnerships, advisory roles, medical AI startups seeking mentorship",
        },
    },
    {
        "name": "Guido van Rossum",
        "title": "Creator of Python",
        "facets": {
            "speaker_expertise": "Python language design, programming language theory, developer productivity",
            "speaking_topics": "Python best practices, language evolution, building developer communities",
            "audience_value": "Insights from creating world's most popular language, coding philosophy",
            "speaker_background": "Python creator, former Google and Dropbox, Python BDFL emeritus",
            "connect_with_me": "Python core development, language design discussions, open source governance",
        },
    },
    {
        "name": "Harrison Chase",
        "title": "CEO, LangChain",
        "facets": {
            "speaker_expertise": "LLM application development, agent architectures, RAG systems, AI developer tools",
            "speaking_topics": "Building with LLMs, production AI systems, the future of AI development",
            "audience_value": "Practical patterns for LLM apps, lessons from thousands of LangChain users",
            "speaker_background": "Founded LangChain, former ML engineer at Robust Intelligence, Harvard CS",
            "connect_with_me": "AI developer tools partnerships, enterprise LLM implementations, startup advice",
        },
    },
    {
        "name": "Dr. Amanda Chen",
        "title": "AI Safety Researcher, Anthropic",
        "facets": {
            "speaker_expertise": "AI alignment, constitutional AI, interpretability, AI governance",
            "speaking_topics": "Making AI safe, alignment research progress, AI policy recommendations",
            "audience_value": "Understand cutting-edge safety research, implement responsible AI practices",
            "speaker_background": "PhD Berkeley AI safety, former OpenAI, published in Nature on AI risks",
            "connect_with_me": "AI safety research collaborations, policy consulting, responsible AI initiatives",
        },
    },
    {
        "name": "Chip Huyen",
        "title": "Author & MLOps Expert",
        "facets": {
            "speaker_expertise": "MLOps, ML systems design, production machine learning, real-time ML",
            "speaking_topics": "ML in production, designing ML systems, bridging research and deployment",
            "audience_value": "Practical MLOps patterns, avoid production pitfalls, scale ML teams effectively",
            "speaker_background": "Author of 'Designing ML Systems', Stanford CS instructor, NVIDIA, Snorkel AI",
            "connect_with_me": "ML platform consulting, book discussions, ML education partnerships",
        },
    },
    {
        "name": "Dr. Andrej Karpathy",
        "title": "AI Researcher & Educator",
        "facets": {
            "speaker_expertise": "Deep learning, computer vision, autonomous vehicles, neural network architectures",
            "speaking_topics": "Neural networks from scratch, Tesla Autopilot lessons, AI education",
            "audience_value": "Learn from Tesla AI leader, practical deep learning insights, career advice",
            "speaker_background": "Former Tesla AI Director, founding member OpenAI, Stanford PhD, YouTube educator",
            "connect_with_me": "AI education initiatives, autonomous vehicle research, deep learning mentorship",
        },
    },
]


async def clear_collections(qdrant):
    """Delete all points from collections."""
    collections = [
        "exhibitors_master",
        "exhibitors_facets",
        "sessions_master",
        "sessions_facets",
        "speakers_master",
        "speakers_facets",
    ]
    for coll in collections:
        try:
            # Delete all points
            await qdrant.client.delete(
                collection_name=coll,
                points_selector={"filter": {"must": []}},
            )
            print(f"  Cleared {coll}")
        except Exception as e:
            print(f"  Warning: Could not clear {coll}: {e}")


async def ingest_exhibitors(qdrant, embedding_service):
    """Ingest exhibitors with full facets."""
    print(f"\n📦 Ingesting {len(EXHIBITORS)} exhibitors...")

    master_points = []
    facet_points = []

    for exh in EXHIBITORS:
        entity_id = str(uuid.uuid4())
        base_payload = {
            "entity_id": entity_id,
            "conference_id": CONFERENCE_ID,
            "name": exh["name"],
            "booth_number": exh["booth"],
            "type": "exhibitor",
        }

        # Master vector (combined description)
        master_text = f"{exh['name']}. {' '.join(exh['facets'].values())}"
        master_vector = await embedding_service.embed_text(master_text)
        master_points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=master_vector,
                payload={**base_payload, "description": master_text[:500]},
            )
        )

        # Facet vectors
        for facet_key, facet_text in exh["facets"].items():
            vector = await embedding_service.embed_text(facet_text)
            facet_points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={
                        **base_payload,
                        "facet_key": facet_key,
                        "facet_text": facet_text,
                    },
                )
            )

        print(f"  ✓ {exh['name']} ({len(exh['facets'])} facets)")

    await qdrant.upsert_points("exhibitors_master", master_points)
    await qdrant.upsert_points("exhibitors_facets", facet_points)
    print(
        f"  → Master: {len(master_points)} points, Facets: {len(facet_points)} points"
    )


async def ingest_sessions(qdrant, embedding_service):
    """Ingest sessions with full facets."""
    print(f"\n📦 Ingesting {len(SESSIONS)} sessions...")

    master_points = []
    facet_points = []

    for sess in SESSIONS:
        entity_id = str(uuid.uuid4())
        base_payload = {
            "entity_id": entity_id,
            "conference_id": CONFERENCE_ID,
            "title": sess["title"],
            "speaker_name": sess["speaker"],
            "location": sess["location"],
            "start_time": sess["time"],
            "type": "session",
        }

        # Master vector
        master_text = f"{sess['title']}. Speaker: {sess['speaker']}. {' '.join(sess['facets'].values())}"
        master_vector = await embedding_service.embed_text(master_text)
        master_points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=master_vector,
                payload={**base_payload, "description": master_text[:500]},
            )
        )

        # Facet vectors
        for facet_key, facet_text in sess["facets"].items():
            vector = await embedding_service.embed_text(facet_text)
            facet_points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={
                        **base_payload,
                        "facet_key": facet_key,
                        "facet_text": facet_text,
                    },
                )
            )

        print(f"  ✓ {sess['title']} ({len(sess['facets'])} facets)")

    await qdrant.upsert_points("sessions_master", master_points)
    await qdrant.upsert_points("sessions_facets", facet_points)
    print(
        f"  → Master: {len(master_points)} points, Facets: {len(facet_points)} points"
    )


async def ingest_speakers(qdrant, embedding_service):
    """Ingest speakers with full facets."""
    print(f"\n📦 Ingesting {len(SPEAKERS)} speakers...")

    master_points = []
    facet_points = []

    for spk in SPEAKERS:
        entity_id = str(uuid.uuid4())
        base_payload = {
            "entity_id": entity_id,
            "conference_id": CONFERENCE_ID,
            "name": spk["name"],
            "title": spk["title"],
            "type": "speaker",
        }

        # Master vector
        master_text = (
            f"{spk['name']}, {spk['title']}. {' '.join(spk['facets'].values())}"
        )
        master_vector = await embedding_service.embed_text(master_text)
        master_points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=master_vector,
                payload={**base_payload, "description": master_text[:500]},
            )
        )

        # Facet vectors
        for facet_key, facet_text in spk["facets"].items():
            vector = await embedding_service.embed_text(facet_text)
            facet_points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={
                        **base_payload,
                        "facet_key": facet_key,
                        "facet_text": facet_text,
                    },
                )
            )

        print(f"  ✓ {spk['name']} ({len(spk['facets'])} facets)")

    await qdrant.upsert_points("speakers_master", master_points)
    await qdrant.upsert_points("speakers_facets", facet_points)
    print(
        f"  → Master: {len(master_points)} points, Facets: {len(facet_points)} points"
    )


async def main(clear: bool = False):
    print("=" * 60)
    print("  ERLEAH FACETED DATA INGESTION")
    print("=" * 60)

    qdrant = get_qdrant_service()
    embedding = get_embedding_service()

    # Ensure collections exist
    print("\n📦 Ensuring collections exist...")
    await qdrant.ensure_collections()

    if clear:
        print("\n🗑️  Clearing existing data...")
        await clear_collections(qdrant)

    # Ingest all data
    await ingest_exhibitors(qdrant, embedding)
    await ingest_sessions(qdrant, embedding)
    await ingest_speakers(qdrant, embedding)

    # Summary
    print("\n" + "=" * 60)
    print("  INGESTION COMPLETE")
    print("=" * 60)
    print(f"""
  Exhibitors: {len(EXHIBITORS)} entities × 6 facets = {len(EXHIBITORS) * 6} facet vectors
  Sessions:   {len(SESSIONS)} entities × 6 facets = {len(SESSIONS) * 6} facet vectors
  Speakers:   {len(SPEAKERS)} entities × 5 facets = {len(SPEAKERS) * 5} facet vectors

  Total: {len(EXHIBITORS) + len(SESSIONS) + len(SPEAKERS)} entities
         {len(EXHIBITORS) * 6 + len(SESSIONS) * 6 + len(SPEAKERS) * 5} facet vectors
         {len(EXHIBITORS) + len(SESSIONS) + len(SPEAKERS)} master vectors

  Conference ID: {CONFERENCE_ID}

  Test queries:
    - "Who sells AI hardware for startups?"
    - "Sessions about MLOps and deployment"
    - "Speakers who can help with LLM development"
    - "Where can I get coffee?"
    - "Find exhibitors for healthcare AI"
""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest faceted data to Qdrant")
    parser.add_argument(
        "--clear", action="store_true", help="Clear existing data before ingest"
    )
    args = parser.parse_args()

    asyncio.run(main(clear=args.clear))
