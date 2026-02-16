#!/usr/bin/env python3
import asyncio
import json
import time
import httpx
import os
import sys
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

# --- CONFIGURATION ---
API_PORT = 8000
API_URL = f"http://localhost:{API_PORT}/api/chat/stream"
HEALTH_URL = f"http://localhost:{API_PORT}/health"
LOG_FILE = "stability_test_data_only.log"

# --- REAL ENTITIES FROM DATABASE ---
VALID_EXHIBITORS = [
    "Wizard Event Technologies",
    "Bizzabo",
    "ADITUS GmbH",
    "AIVA Revolution",
    "All in The Loop",
    "BBD Boom",
    "Blackthorn",
    "Captello",
    "Choose 2 Rent",
    "Crowd Connected",
]
VALID_SESSIONS = [
    "How to Build a High-Performing Team in Event Technology",
    "Is the Event Tech Industry Parent-Friendly?",
    "From Optional to Essential: How Ottobock Transformed Their Event Experience",
    "The FFAIR Podcast: How we made 2025 the year exhibitors met deadlines",
    "Maximising the International Attendee - More than Just Words",
    "The Changing Landscape of Awards",
    "The Missing Millions: Ramp Up Your Event ROI By Turning Untapped Event Data Into Retention, Revenue And Results That Matter",
    "Associations Meet-up",
    "From Attendee to Contributor: The ROI of Real Connection",
    "Experiential Futurists",
]
VALID_SPEAKERS = [
    "Lydia Ritchie",
    "Faisa Mohamed",
    "Rodney Hart",
    "Lou Kiwanuka",
    "Christopher Velez",
    "Claudia Cafeo",
    "Daniel Mortimer",
    "Eli Amar",
    "Anup Mohan",
    "Jack Newey",
]


def generate_30_data_queries() -> List[Dict[str, Any]]:
    queries = []
    for name in VALID_EXHIBITORS:
        queries.append(
            {"message": f"Tell me about the exhibitor {name}", "category": "exhibitor"}
        )
    for name in VALID_SESSIONS:
        queries.append(
            {"message": f"What is the session '{name}' about?", "category": "session"}
        )
    for name in VALID_SPEAKERS:
        queries.append(
            {
                "message": f"Who is the speaker {name} and what is their expertise?",
                "category": "speaker",
            }
        )
    return queries


@dataclass
class QueryResult:
    query_id: int
    message: str
    category: str
    success: bool = False
    duration: float = 0
    full_response: str = ""
    error: Optional[str] = None


async def run_query(
    client: httpx.AsyncClient, query_data: Dict[str, Any], q_id: int
) -> QueryResult:
    res = QueryResult(
        query_id=q_id, message=query_data["message"], category=query_data["category"]
    )
    start_time = time.perf_counter()
    conv_id = str(uuid.uuid4())
    payload = {
        "message": query_data["message"],
        "user_context": {
            "user_id": "test-user-001",
            "conference_id": "etl-2025",
            "conversation_id": conv_id,
        },
    }
    try:
        async with client.stream(
            "POST", API_URL, json=payload, timeout=120.0
        ) as response:
            if response.status_code != 200:
                res.error = f"HTTP {response.status_code}"
                return res
            current_event = None
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    try:
                        event_data = json.loads(line[5:])
                        if current_event == "chunk":
                            res.full_response += event_data.get("text", "")
                        elif current_event == "done":
                            res.success = True
                    except:
                        pass
    except Exception as e:
        res.error = str(e)
    res.duration = time.perf_counter() - start_time
    return res


async def main():
    print(f"Starting REAL Data Retrieval Test: 30 queries against {API_URL}")
    queries = generate_30_data_queries()
    results = []
    with open(LOG_FILE, "w") as f:
        f.write(f"ERLEAH V2 DATA RETRIEVAL TEST - {time.ctime()}\n" + "=" * 80 + "\n")

    async with httpx.AsyncClient() as client:
        for i, q in enumerate(queries):
            print(f"[{i + 1}/30] Testing {q['category']}: {q['message'][:50]}...")
            res = await run_query(client, q, i + 1)
            results.append(res)
            with open(LOG_FILE, "a") as f:
                f.write(
                    f"#{res.query_id} [{res.category.upper()}] Query: {res.message}\n"
                )
                f.write(f"AI: {res.full_response[:250]}...\n")
                status = (
                    "OK"
                    if res.success
                    and "I don't see" not in res.full_response
                    and "don't have any information" not in res.full_response
                    else "FAIL"
                )
                f.write(f"Status: {status} | Time: {res.duration:.2f}s\n")
                f.write("-" * 40 + "\n")
            await asyncio.sleep(0.5)

    success_rate = sum(
        1 for r in results if r.success and "I don't see" not in r.full_response
    )
    print(f"\nTest Finished. Success: {success_rate}/30")


if __name__ == "__main__":
    asyncio.run(main())
