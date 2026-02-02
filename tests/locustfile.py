"""Locust load testing for Erleah backend.

Usage:
    locust -f tests/locustfile.py --host http://localhost:8000

Success criteria from docs:
    p95 response time: <8s (target), <12s (acceptable), >15s (failure)
    p99 response time: <12s (target), <18s (acceptable), >20s (failure)
    Error rate: <1% (target), <5% (acceptable), >10% (failure)
    Queue full rate: <0.1% (target), <1% (acceptable), >5% (failure)
"""

import json
import random

from locust import HttpUser, task, between


SAMPLE_MESSAGES = [
    "Find gaming companies",
    "Where can I get free coffee?",
    "Show me AI exhibitors",
    "What sessions are about cybersecurity?",
    "Who is speaking about machine learning?",
    "Recommend exhibitors for me",
    "Find companies that sell cloud infrastructure",
    "What talks are happening today?",
    "Who can help with data analytics?",
    "Show me networking events",
]


class ChatUser(HttpUser):
    """Simulates a conference attendee using the chat assistant."""
    wait_time = between(2, 10)

    @task(3)
    def chat_stream(self):
        """SSE streaming endpoint (most common)."""
        message = random.choice(SAMPLE_MESSAGES)
        with self.client.post(
            "/api/chat/stream",
            json={
                "message": message,
                "user_context": {
                    "conference_id": "conf-2024",
                    "user_id": f"user-{random.randint(1, 100)}",
                },
            },
            headers={"Content-Type": "application/json"},
            catch_response=True,
            stream=True,
        ) as response:
            if response.status_code == 200:
                # Read SSE events
                events_received = 0
                for line in response.iter_lines():
                    if line:
                        events_received += 1
                if events_received > 0:
                    response.success()
                else:
                    response.failure("No SSE events received")
            elif response.status_code == 503:
                response.failure("Server at capacity (503)")
            elif response.status_code == 429:
                response.failure("Rate limited (429)")
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    @task(1)
    def chat_non_streaming(self):
        """Non-streaming endpoint (for testing)."""
        message = random.choice(SAMPLE_MESSAGES)
        self.client.post(
            "/api/chat",
            json={
                "message": message,
                "user_context": {
                    "conference_id": "conf-2024",
                    "user_id": f"user-{random.randint(1, 100)}",
                },
            },
            headers={"Content-Type": "application/json"},
        )

    @task(1)
    def health_check(self):
        """Health check endpoint."""
        self.client.get("/health")

    @task(1)
    def metrics_check(self):
        """Metrics endpoint."""
        self.client.get("/metrics")
