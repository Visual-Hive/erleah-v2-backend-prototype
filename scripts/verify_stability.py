#!/usr/bin/env python3
import asyncio
import json
import random
import time
import httpx
import os
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

# --- CONFIGURATION ---
API_PORT = 8000
API_URL = f"http://localhost:{API_PORT}/api/chat/stream"
LOG_FILE = "stability_test_detailed.log"
GROUND_TRUTH_DIR = "scripts"


# --- LOAD GROUND TRUTH ---
def load_json(filename):
    path = os.path.join(GROUND_TRUTH_DIR, filename)
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return json.load(f)


GT_FAQ = load_json("ground_truth_faq.json")
GT_EXHIBITORS = load_json("ground_truth_exhibitors.json")
GT_SESSIONS = load_json("ground_truth_sessions.json")
GT_SPEAKERS = load_json("ground_truth_speakers.json")


# --- QUERY GENERATOR ---
def generate_100_queries() -> List[Dict[str, Any]]:
    queries = []

    # 1. Real FAQ questions
    for item in GT_FAQ[:20]:
        queries.append(
            {
                "message": item["question"],
                "category": "faq_exact",
                "expected": item["answer"],
            }
        )

    # 2. Rephrased FAQ questions
    faq_rephrased = [
        "Tell me about wifi",
        "When do we start?",
        "Where is the award ceremony?",
        "Who organized this?",
        "Is there a floor plan?",
        "How do I get help?",
        "What's Erleah?",
        "Opening times please",
    ]
    for msg in faq_rephrased:
        queries.append({"message": msg, "category": "faq_rephrased"})

    # 3. Exhibitor searches
    for ex in GT_EXHIBITORS[:15]:
        queries.append(
            {
                "message": f"Where is {ex['name']} located?",
                "category": "search_exhibitor",
                "target": ex["name"],
            }
        )
        queries.append(
            {
                "message": f"What does {ex['name']} do?",
                "category": "search_exhibitor",
                "target": ex["name"],
            }
        )

    # 4. Session/Speaker searches
    for sess in GT_SESSIONS[:10]:
        queries.append(
            {
                "message": f"Tell me about the session '{sess['title']}'",
                "category": "search_session",
                "target": sess["title"],
            }
        )

    for spk in GT_SPEAKERS[:10]:
        queries.append(
            {
                "message": f"When is {spk['name']} speaking?",
                "category": "search_speaker",
                "target": spk["name"],
            }
        )

    # 5. Multi-intent
    complex_msgs = [
        "I want to see AI exhibitors and know the opening times",
        "Who is speaking about marketing and is there free food?",
        "Recommend some sessions for a developer and where is the exit?",
        "Hi, what is ETL 2025 about and who are the top speakers?",
    ]
    for msg in complex_msgs:
        queries.append({"message": msg, "category": "multi_intent"})

    # 6. Fill up to 100
    while len(queries) < 100:
        base = random.choice(
            ["hello", "help me", "search for AI", "who is here?", "what's next?"]
        )
        queries.append(
            {"message": f"{base} {random.randint(1, 1000)}", "category": "random_noise"}
        )

    return queries[:100]


@dataclass
class EventLog:
    event: str
    timestamp: float
    data: Dict[str, Any]


@dataclass
class QueryResult:
    query_id: int
    message: str
    category: str
    success: bool = False
    duration: float = 0
    events: List[EventLog] = field(default_factory=list)
    full_response: str = ""
    error: Optional[str] = None
    validation_note: str = "N/A"
    nodes_timeline: List[Dict[str, Any]] = field(default_factory=list)


async def run_query(
    client: httpx.AsyncClient, query_data: Dict[str, Any], q_id: int
) -> QueryResult:
    res = QueryResult(
        query_id=q_id, message=query_data["message"], category=query_data["category"]
    )
    start_time = time.perf_counter()

    payload = {
        "message": query_data["message"],
        "user_context": {
            "user_id": "0001b55e-6437-411f-8174-2c8249795c39",
            "conference_id": "etl-2025",
            "conversation_id": f"stability-test-{q_id}",
        },
    }

    try:
        async with client.stream(
            "POST", API_URL, json=payload, timeout=130.0
        ) as response:
            if response.status_code != 200:
                res.error = f"HTTP {response.status_code}"
                return res

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    raw_event = json.loads(line[5:])
                    event_type = raw_event.get("event")
                    event_data = raw_event.get("data", {})

                    res.events.append(
                        EventLog(
                            event_type, time.perf_counter() - start_time, event_data
                        )
                    )

                    if event_type == "chunk":
                        res.full_response += event_data.get("text", "")
                    elif event_type == "node_start":
                        res.nodes_timeline.append(
                            {
                                "node": event_data["node"],
                                "start": event_data["ts"],
                                "duration_ms": None,
                                "output_summary": None,
                            }
                        )
                    elif event_type == "node_end":
                        for n in res.nodes_timeline:
                            if n["node"] == event_data["node"]:
                                n["duration_ms"] = event_data.get("duration_ms")
                                n["output_summary"] = (
                                    str(event_data.get("output", {}))[:200] + "..."
                                )
                    elif event_type == "error":
                        res.error = event_data.get("error")
                    elif event_type == "done":
                        res.success = res.error is None
                except Exception as e:
                    pass

    except Exception as e:
        res.error = str(e)

    res.duration = time.perf_counter() - start_time

    # Validation
    if res.success:
        expected = str(query_data.get("expected", "")).lower()
        target = str(query_data.get("target", "")).lower()
        resp = res.full_response.lower()

        if expected and any(word in resp for word in expected.split()[:5]):
            res.validation_note = "PASSED: Matches Ground Truth FAQ"
        elif target and target in resp:
            res.validation_note = "PASSED: Mentions target entity"
        elif res.category in ["chitchat", "random_noise"]:
            res.validation_note = "MANUAL: Conversational response"
        else:
            res.validation_note = "CHECK: No direct match to GT data"

    return res


async def main():
    queries = generate_100_queries()
    print(f"Starting STABILITY TEST: 100 queries against {API_URL}")
    print(f"Detailed logs: {LOG_FILE}")

    results = []

    with open(LOG_FILE, "w") as f:
        f.write(f"ERLEAH V2 STABILITY TEST - {time.ctime()}\n")
        f.write("=" * 100 + "\n\n")

    for i in range(0, 100, 3):
        batch = queries[i : i + 3]
        async with httpx.AsyncClient() as client:
            tasks = [run_query(client, q, i + j) for j, q in enumerate(batch)]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)

            with open(LOG_FILE, "a") as f:
                for r in batch_results:
                    f.write(f"QUERY #{r.query_id} [{r.category}]\n")
                    f.write(f"MESSAGE: {r.message}\n")
                    f.write(f"SUCCESS: {r.success} | DURATION: {r.duration:.2f}s\n")
                    f.write(f"VALIDATION: {r.validation_note}\n")
                    f.write("-" * 20 + " TIMELINE " + "-" * 20 + "\n")
                    for node in r.nodes_timeline:
                        dur = node.get("duration_ms", "running...")
                        f.write(
                            f"  * {node['node']:25} | {str(dur):>6} ms | Out: {node.get('output_summary', 'N/A')}\n"
                        )
                    f.write("-" * 20 + " RESPONSE " + "-" * 20 + "\n")
                    f.write(f"{r.full_response}\n")
                    if r.error:
                        f.write(f"ERROR: {r.error}\n")
                    f.write("=" * 100 + "\n\n")

            print(f"Completed {len(results)}/100...")
            await asyncio.sleep(0.5)

    success_rate = sum(1 for r in results if r.success)
    avg_dur = sum(r.duration for r in results) / 100

    summary = f"""
FINAL SUMMARY
=============
Total Requests: 100
Successful:    {success_rate}
Failed:        {100 - success_rate}
Avg Duration:  {avg_dur:.2f}s
Success Rate:  {success_rate}%
"""
    print(summary)
    with open(LOG_FILE, "a") as f:
        f.write(summary)


if __name__ == "__main__":
    asyncio.run(main())
