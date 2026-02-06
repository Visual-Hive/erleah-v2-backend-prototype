#!/usr/bin/env python3
"""
Load test script for Erleah API.
Simulates concurrent users hitting the SSE endpoint.

Usage:
    python scripts/load_test.py --users 100 --duration 60
    python scripts/load_test.py --users 1000 --duration 30 --ramp-up 10
"""

import argparse
import asyncio
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

API_URL = "http://localhost:8000/api/chat/stream"

# Sample queries to randomize
QUERIES = [
    "Where can I get free coffee?",
    "Recommend AI sessions for me",
    "Who sells GPU hardware?",
    "What Python workshops are available?",
    "Find exhibitors for machine learning",
    "Show me sessions about data science",
    "Which speakers talk about AI?",
    "What's happening at 2pm?",
    "Find networking opportunities",
    "Recommend exhibitors for startups",
]


@dataclass
class RequestResult:
    success: bool
    status_code: int
    response_time: float  # seconds
    time_to_first_chunk: Optional[float] = None
    chunk_count: int = 0
    error: Optional[str] = None


@dataclass
class LoadTestStats:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    response_times: list = field(default_factory=list)
    ttfc_times: list = field(default_factory=list)  # Time to first chunk
    errors: dict = field(default_factory=dict)
    status_codes: dict = field(default_factory=dict)

    def add_result(self, result: RequestResult):
        self.total_requests += 1
        self.status_codes[result.status_code] = self.status_codes.get(result.status_code, 0) + 1

        if result.success:
            self.successful_requests += 1
            self.response_times.append(result.response_time)
            if result.time_to_first_chunk:
                self.ttfc_times.append(result.time_to_first_chunk)
        else:
            self.failed_requests += 1
            if result.error:
                self.errors[result.error] = self.errors.get(result.error, 0) + 1

    def summary(self) -> dict:
        if not self.response_times:
            return {"error": "No successful requests"}

        return {
            "total_requests": self.total_requests,
            "successful": self.successful_requests,
            "failed": self.failed_requests,
            "success_rate": f"{(self.successful_requests / self.total_requests * 100):.1f}%",
            "response_time": {
                "min": f"{min(self.response_times):.2f}s",
                "max": f"{max(self.response_times):.2f}s",
                "avg": f"{statistics.mean(self.response_times):.2f}s",
                "median": f"{statistics.median(self.response_times):.2f}s",
                "p95": f"{sorted(self.response_times)[int(len(self.response_times) * 0.95)]:.2f}s" if len(self.response_times) > 20 else "N/A",
                "p99": f"{sorted(self.response_times)[int(len(self.response_times) * 0.99)]:.2f}s" if len(self.response_times) > 100 else "N/A",
            },
            "time_to_first_chunk": {
                "min": f"{min(self.ttfc_times):.2f}s" if self.ttfc_times else "N/A",
                "max": f"{max(self.ttfc_times):.2f}s" if self.ttfc_times else "N/A",
                "avg": f"{statistics.mean(self.ttfc_times):.2f}s" if self.ttfc_times else "N/A",
            },
            "status_codes": self.status_codes,
            "errors": self.errors if self.errors else None,
        }


async def make_request(client: httpx.AsyncClient, user_id: int) -> RequestResult:
    """Make a single SSE request and collect metrics."""
    query = random.choice(QUERIES)
    start_time = time.perf_counter()
    first_chunk_time = None
    chunk_count = 0

    try:
        async with client.stream(
            "POST",
            API_URL,
            json={
                "message": query,
                "user_context": {
                    "conference_id": "conf-2024",
                    "user_id": f"loadtest-user-{user_id}",
                }
            },
            timeout=60.0,
        ) as response:
            if response.status_code != 200:
                return RequestResult(
                    success=False,
                    status_code=response.status_code,
                    response_time=time.perf_counter() - start_time,
                    error=f"HTTP {response.status_code}",
                )

            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    chunk_count += 1
                    if first_chunk_time is None:
                        first_chunk_time = time.perf_counter() - start_time

                    # Check for done event
                    if '"trace_id"' in line:
                        break

            return RequestResult(
                success=True,
                status_code=response.status_code,
                response_time=time.perf_counter() - start_time,
                time_to_first_chunk=first_chunk_time,
                chunk_count=chunk_count,
            )

    except httpx.TimeoutException:
        return RequestResult(
            success=False,
            status_code=0,
            response_time=time.perf_counter() - start_time,
            error="Timeout",
        )
    except httpx.ConnectError:
        return RequestResult(
            success=False,
            status_code=0,
            response_time=time.perf_counter() - start_time,
            error="Connection refused",
        )
    except Exception as e:
        return RequestResult(
            success=False,
            status_code=0,
            response_time=time.perf_counter() - start_time,
            error=str(type(e).__name__),
        )


async def run_user(
    user_id: int,
    client: httpx.AsyncClient,
    stats: LoadTestStats,
    duration: float,
    start_event: asyncio.Event,
):
    """Simulate a single user making requests for the duration."""
    await start_event.wait()  # Wait for ramp-up

    end_time = time.perf_counter() + duration
    request_count = 0

    while time.perf_counter() < end_time:
        result = await make_request(client, user_id)
        stats.add_result(result)
        request_count += 1

        # Small delay between requests (simulate thinking time)
        await asyncio.sleep(random.uniform(0.5, 2.0))

    return request_count


async def run_load_test(
    num_users: int,
    duration: float,
    ramp_up: float = 0,
):
    """Run the load test with specified parameters."""
    print(f"\n{'='*60}")
    print(f"  ERLEAH LOAD TEST")
    print(f"{'='*60}")
    print(f"  Users: {num_users}")
    print(f"  Duration: {duration}s")
    print(f"  Ramp-up: {ramp_up}s")
    print(f"  API URL: {API_URL}")
    print(f"{'='*60}\n")

    stats = LoadTestStats()
    start_events = [asyncio.Event() for _ in range(num_users)]

    # Configure client with connection pooling
    limits = httpx.Limits(
        max_keepalive_connections=min(num_users, 100),
        max_connections=min(num_users + 10, 500),
    )

    async with httpx.AsyncClient(limits=limits) as client:
        # Check if server is up
        try:
            health = await client.get("http://localhost:8000/health", timeout=5.0)
            if health.status_code != 200:
                print("ERROR: Server health check failed!")
                return
            print("Server is healthy. Starting load test...\n")
        except Exception as e:
            print(f"ERROR: Cannot connect to server: {e}")
            print("Make sure the server is running: uvicorn src.main:app --port 8000")
            return

        # Create user tasks
        tasks = [
            asyncio.create_task(
                run_user(i, client, stats, duration, start_events[i])
            )
            for i in range(num_users)
        ]

        # Ramp up users gradually
        test_start = time.perf_counter()
        if ramp_up > 0:
            delay_per_user = ramp_up / num_users
            for i, event in enumerate(start_events):
                event.set()
                if i < num_users - 1:
                    await asyncio.sleep(delay_per_user)

                # Progress indicator
                if (i + 1) % max(1, num_users // 10) == 0:
                    print(f"  Ramping up: {i + 1}/{num_users} users started...")
        else:
            for event in start_events:
                event.set()

        print(f"\n  All {num_users} users active. Running for {duration}s...\n")

        # Wait with progress updates
        update_interval = 5.0
        while True:
            await asyncio.sleep(update_interval)
            elapsed = time.perf_counter() - test_start - ramp_up
            if elapsed >= duration:
                break

            current_rps = stats.total_requests / max(elapsed, 1)
            print(f"  Progress: {elapsed:.0f}s/{duration}s | "
                  f"Requests: {stats.total_requests} | "
                  f"RPS: {current_rps:.1f} | "
                  f"Success: {stats.successful_requests} | "
                  f"Failed: {stats.failed_requests}")

        # Wait for all tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)

    # Print results
    total_time = time.perf_counter() - test_start
    summary = stats.summary()

    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Total Test Time: {total_time:.1f}s")
    print(f"  Total Requests: {summary['total_requests']}")
    print(f"  Successful: {summary['successful']} ({summary['success_rate']})")
    print(f"  Failed: {summary['failed']}")
    print(f"  Requests/sec: {summary['total_requests'] / total_time:.1f}")
    print(f"\n  Response Time:")
    for key, val in summary['response_time'].items():
        print(f"    {key}: {val}")
    print(f"\n  Time to First Chunk:")
    for key, val in summary['time_to_first_chunk'].items():
        print(f"    {key}: {val}")
    print(f"\n  Status Codes: {summary['status_codes']}")
    if summary['errors']:
        print(f"  Errors: {summary['errors']}")
    print(f"{'='*60}\n")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Load test Erleah API")
    parser.add_argument("--users", type=int, default=10, help="Number of concurrent users")
    parser.add_argument("--duration", type=float, default=30, help="Test duration in seconds")
    parser.add_argument("--ramp-up", type=float, default=5, help="Ramp-up time in seconds")
    args = parser.parse_args()

    asyncio.run(run_load_test(args.users, args.duration, args.ramp_up))


if __name__ == "__main__":
    main()
