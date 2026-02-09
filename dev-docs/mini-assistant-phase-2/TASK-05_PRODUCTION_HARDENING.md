# TASK-05: Production Hardening
## Rate Limits, Circuit Breakers, Health Checks, CORS

**Priority:** 🟡 Important  
**Effort:** 2 days  
**Dependencies:** TASK-01 (graceful failure), TASK-04 (real services connected)  

---

## Goal

Make the backend resilient enough for production. This covers six areas, all interconnected:

1. **Rate Limiting** — prevent abuse and protect LLM budget
2. **Circuit Breakers** — stop cascading failures when a service goes down
3. **Health Check Endpoints** — give Kubernetes (and the agent) visibility into service status
4. **CORS Configuration** — lock down origins in production
5. **Horizontal Scaling Prep** — ensure nothing breaks with multiple instances
6. **Agent-Aware Health** — feed service status into the agent so it can advise users

---

## 1. Rate Limiting

### Why
- Each request costs ~$0.01-0.02 in LLM tokens
- A single user spamming could burn through budget
- Protects the bounded worker pool from being monopolized

### Implementation

```python
# src/middleware/rate_limit.py

import time
from collections import defaultdict
from fastapi import Request, HTTPException
import structlog

logger = structlog.get_logger()

# In-memory rate limiter (works per-instance; for multi-instance, use Redis)
_request_counts: dict[str, list[float]] = defaultdict(list)


class RateLimiter:
    """Simple sliding window rate limiter."""
    
    def __init__(
        self,
        requests_per_minute: int = 20,
        requests_per_hour: int = 200,
        max_message_length: int = 2000,
    ):
        self.rpm = requests_per_minute
        self.rph = requests_per_hour
        self.max_message_length = max_message_length
    
    async def check(self, key: str, message_length: int = 0):
        """
        Check if request is within rate limits.
        Raises HTTPException(429) if exceeded.
        """
        now = time.time()
        
        # Clean old entries
        _request_counts[key] = [
            t for t in _request_counts[key] if t > now - 3600
        ]
        
        timestamps = _request_counts[key]
        
        # Check per-minute limit
        recent_minute = [t for t in timestamps if t > now - 60]
        if len(recent_minute) >= self.rpm:
            logger.warning("rate_limit_exceeded", key=key, window="minute", count=len(recent_minute))
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "message": "You're sending messages too quickly. Please wait a moment.",
                    "retry_after": 60,
                    "limit": f"{self.rpm} requests per minute",
                },
                headers={"Retry-After": "60"},
            )
        
        # Check per-hour limit
        if len(timestamps) >= self.rph:
            logger.warning("rate_limit_exceeded", key=key, window="hour", count=len(timestamps))
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Hourly limit exceeded",
                    "message": "You've reached the hourly message limit. Please try again later.",
                    "retry_after": 3600,
                    "limit": f"{self.rph} requests per hour",
                },
                headers={"Retry-After": "3600"},
            )
        
        # Check message length
        if message_length > self.max_message_length:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "Message too long",
                    "message": f"Please keep messages under {self.max_message_length} characters.",
                    "max_length": self.max_message_length,
                    "your_length": message_length,
                },
            )
        
        # Record this request
        timestamps.append(now)


# Usage in endpoint:
rate_limiter = RateLimiter()

@router.post("/api/chat")
async def chat(request: ChatRequest, req: Request):
    # Rate limit by conversation ID (or IP as fallback)
    rate_key = f"conv:{request.conversation_id}"
    await rate_limiter.check(rate_key, len(request.message or ""))
    # ... continue ...
```

### Redis-Backed Rate Limiter (Multi-Instance)

For horizontal scaling, switch to Redis:

```python
# src/middleware/rate_limit_redis.py

class RedisRateLimiter:
    """Redis-backed rate limiter for multi-instance deployments."""
    
    def __init__(self, cache: CacheService, rpm: int = 20, rph: int = 200):
        self.cache = cache
        self.rpm = rpm
        self.rph = rph
    
    async def check(self, key: str):
        redis = self.cache.redis
        
        minute_key = f"rl:min:{key}"
        hour_key = f"rl:hr:{key}"
        
        # Atomic increment + expire
        pipe = redis.pipeline()
        pipe.incr(minute_key)
        pipe.expire(minute_key, 60)
        pipe.incr(hour_key)
        pipe.expire(hour_key, 3600)
        minute_count, _, hour_count, _ = await pipe.execute()
        
        if minute_count > self.rpm:
            raise HTTPException(status_code=429, ...)
        if hour_count > self.rph:
            raise HTTPException(status_code=429, ...)
```

---

## 2. Circuit Breakers

### Why
If Qdrant goes down, every request that tries to search will timeout (10s). With 20 workers, that means all workers get stuck waiting. A circuit breaker **fails fast** after detecting repeated failures, protecting the worker pool.

### Implementation

```python
# src/services/circuit_breaker.py

import asyncio
import time
import structlog
from enum import Enum

logger = structlog.get_logger()


class CircuitState(Enum):
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failing fast, not calling service
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker for external service calls.
    
    CLOSED  → failures exceed threshold → OPEN
    OPEN    → after recovery_timeout    → HALF_OPEN
    HALF_OPEN → success                 → CLOSED
    HALF_OPEN → failure                 → OPEN
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exceptions: tuple = (Exception,),
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exceptions = expected_exceptions
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0
        self.last_state_change = time.time()
    
    async def call(self, func, *args, **kwargs):
        """Execute function through circuit breaker."""
        
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self._transition(CircuitState.HALF_OPEN)
            else:
                logger.warning("circuit_open", service=self.name, retry_in=self._retry_in())
                raise CircuitOpenError(
                    f"{self.name} circuit is open. Service unavailable. Retry in {self._retry_in():.0f}s"
                )
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exceptions as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.CLOSED)
        self.failure_count = 0
    
    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self._transition(CircuitState.OPEN)
    
    def _transition(self, new_state: CircuitState):
        old = self.state
        self.state = new_state
        self.last_state_change = time.time()
        logger.info("circuit_state_change", service=self.name, old=old.value, new=new_state.value)
    
    def _retry_in(self) -> float:
        return max(0, self.recovery_timeout - (time.time() - self.last_failure_time))
    
    @property
    def status(self) -> dict:
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "retry_in": self._retry_in() if self.state == CircuitState.OPEN else 0,
        }


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


# --- Global circuit breakers ---

qdrant_circuit = CircuitBreaker("qdrant", failure_threshold=5, recovery_timeout=60)
directus_circuit = CircuitBreaker("directus", failure_threshold=5, recovery_timeout=30)
anthropic_circuit = CircuitBreaker("anthropic", failure_threshold=3, recovery_timeout=120)
embedding_circuit = CircuitBreaker("embedding", failure_threshold=5, recovery_timeout=60)
```

### Usage in Services

```python
# In QdrantService.search()
async def search(self, ...):
    return await qdrant_circuit.call(self._do_search, ...)

# In DirectusClient methods
async def get_conversation_messages(self, ...):
    return await directus_circuit.call(self._do_get_messages, ...)
```

### Circuit Breaker + Graceful Failure Integration

`CircuitOpenError` should be caught by the `@graceful_node` decorator from TASK-01 and classified as a "connection" error type, which generates appropriate user-facing messages.

---

## 3. Health Check Endpoints

### Two Endpoints

```python
# src/api/health.py

from fastapi import APIRouter
import structlog
from src.services.circuit_breaker import qdrant_circuit, directus_circuit, anthropic_circuit

logger = structlog.get_logger()
router = APIRouter()


@router.get("/health")
async def liveness():
    """
    Liveness probe — is the process running?
    Kubernetes uses this to decide whether to restart the pod.
    Always returns 200 if the process is alive.
    """
    return {"status": "healthy", "service": "erleah-mini-assistant"}


@router.get("/health/ready")
async def readiness():
    """
    Readiness probe — can this instance handle requests?
    Kubernetes uses this to decide whether to route traffic here.
    Returns 200 only if all critical dependencies are reachable.
    Also returns circuit breaker status for each service.
    """
    checks = {}
    all_ok = True
    
    # Check Directus
    try:
        directus = get_directus_client()
        directus_ok = await directus.health_check()
        checks["directus"] = {
            "status": "ok" if directus_ok else "degraded",
            "circuit": directus_circuit.status,
        }
        if not directus_ok:
            all_ok = False
    except Exception as e:
        checks["directus"] = {"status": "down", "error": str(e), "circuit": directus_circuit.status}
        all_ok = False
    
    # Check Qdrant
    try:
        qdrant = get_qdrant_service()
        qdrant_ok = await qdrant.health_check()
        checks["qdrant"] = {
            "status": "ok" if qdrant_ok else "degraded",
            "circuit": qdrant_circuit.status,
        }
        if not qdrant_ok:
            all_ok = False
    except Exception as e:
        checks["qdrant"] = {"status": "down", "error": str(e), "circuit": qdrant_circuit.status}
        all_ok = False
    
    # Check Redis
    try:
        cache = get_cache_service()
        await cache.redis.ping()
        checks["redis"] = {"status": "ok"}
    except Exception as e:
        checks["redis"] = {"status": "down", "error": str(e)}
        # Redis down is degraded, not fatal (cache miss = fetch from source)
    
    # Check Anthropic (circuit breaker only, don't make a real API call)
    checks["anthropic"] = {
        "status": "ok" if anthropic_circuit.state.value == "closed" else "degraded",
        "circuit": anthropic_circuit.status,
    }
    if anthropic_circuit.state.value == "open":
        all_ok = False
    
    # Queue status
    queue = get_request_queue()
    checks["queue"] = {
        "size": queue.qsize(),
        "capacity": queue.maxsize,
        "utilization": f"{queue.qsize() / queue.maxsize:.1%}",
    }
    
    status_code = 200 if all_ok else 503
    
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_ok else "degraded",
            "checks": checks,
        },
    )
```

### Agent-Aware Health (The Epic Part)

Feed health status into the pipeline state so the agent knows about problems:

```python
# In the /api/chat endpoint, before entering the pipeline

async def get_service_health_for_agent() -> dict | None:
    """
    Check service health and return context for the agent.
    Returns None if everything is healthy (no need to clutter the prompt).
    """
    issues = []
    
    if qdrant_circuit.state != CircuitState.CLOSED:
        issues.append("The search database is currently experiencing issues. Search results may be limited or unavailable.")
    
    if directus_circuit.state != CircuitState.CLOSED:
        issues.append("The content database is having connection problems. Some information may be temporarily unavailable.")
    
    if anthropic_circuit.state != CircuitState.CLOSED:
        issues.append("The AI service is temporarily overloaded.")
    
    queue = get_request_queue()
    utilization = queue.qsize() / queue.maxsize
    if utilization > 0.8:
        issues.append("The system is experiencing high demand. Responses may be slower than usual.")
    
    if not issues:
        return None
    
    return {
        "service_issues": issues,
        "degraded": True,
    }
```

Inject into the response generator prompt:

```
{% if service_health %}
## Current System Status
The following issues are affecting service right now:
{% for issue in service_health.service_issues %}
- {{ issue }}
{% endfor %}
Please acknowledge any limitations when responding. Be transparent but reassuring.
{% endif %}
```

This means the agent can say things like:
> "I'd normally search for exhibitors matching your interests, but the search service is temporarily having issues. Based on what I know from our conversation, I'd suggest..."

---

## 4. CORS Configuration

```python
# src/config.py

class Settings(BaseSettings):
    # ... existing ...
    
    cors_origins: list[str] = ["*"]  # Override in production
    
    # Production example:
    # cors_origins: ["https://widget.erleah.com", "https://app.erleah.com"]


# src/main.py

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Trace-ID"],
)
```

Set via environment variable:
```bash
# Development
CORS_ORIGINS='["*"]'

# Production
CORS_ORIGINS='["https://widget.erleah.com","https://app.erleah.com"]'
```

---

## 5. Horizontal Scaling Prep

For running multiple FastAPI instances behind a load balancer:

### Checklist

| Concern | Single Instance | Multi-Instance | Fix |
|---------|-----------------|----------------|-----|
| Rate limiting | In-memory dict | Shared | Use Redis-backed rate limiter |
| Request queue | asyncio.Queue | Per-instance | Each instance has own queue (fine) |
| Circuit breakers | In-memory | Per-instance | Acceptable (each instance learns independently) |
| Cache | Redis (shared) | Redis (shared) | Already works ✅ |
| Health checks | Per-instance | Per-instance | Kubernetes routes to healthy instances ✅ |

### Key Point

The request queue is **per-instance by design**. With 3 instances × 20 workers each = 60 total workers. The load balancer distributes requests. No shared queue needed.

### Kubernetes HPA

```yaml
# k8s/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: erleah-assistant-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: erleah-assistant
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

---

## 6. Queue Full Rejection (503)

Verify this is in the chat endpoint:

```python
@router.post("/api/chat")
async def chat(request: ChatRequest):
    queue = get_request_queue()
    
    if queue.full():
        raise HTTPException(
            status_code=503,
            detail={
                "error": "System at capacity",
                "message": "We're experiencing high traffic. Please try again in a moment.",
                "retry_after": 5,
            },
            headers={"Retry-After": "5"},
        )
    
    # ... continue with normal flow ...
```

---

## Testing

```python
async def test_rate_limit_per_minute():
    """Exceed RPM limit and verify 429."""
    limiter = RateLimiter(requests_per_minute=3)
    for _ in range(3):
        await limiter.check("test-key")
    with pytest.raises(HTTPException) as exc:
        await limiter.check("test-key")
    assert exc.value.status_code == 429

async def test_circuit_breaker_opens_after_threshold():
    """Verify circuit opens after N failures."""
    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=1)
    for _ in range(3):
        try:
            await cb.call(failing_func)
        except:
            pass
    assert cb.state == CircuitState.OPEN

async def test_circuit_breaker_recovers():
    """Verify circuit recovers after timeout."""
    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
    try:
        await cb.call(failing_func)
    except:
        pass
    assert cb.state == CircuitState.OPEN
    await asyncio.sleep(0.15)
    await cb.call(succeeding_func)
    assert cb.state == CircuitState.CLOSED

async def test_health_ready_reports_degraded():
    """Verify readiness check reports degraded when circuit is open."""

async def test_agent_receives_health_context():
    """Verify degraded service info is in agent prompt."""
```

---

## Acceptance Criteria

- [ ] Rate limiting: 20 req/min per conversation, 200/hr per IP, 2000 char max
- [ ] Rate limit returns 429 with Retry-After header
- [ ] Circuit breakers on Qdrant, Directus, Anthropic, Embedding services
- [ ] Circuit breaker states: closed → open (after 5 failures) → half-open (after 60s) → closed
- [ ] `CircuitOpenError` handled by `@graceful_node` from TASK-01
- [ ] `GET /health` — liveness (always 200)
- [ ] `GET /health/ready` — readiness with dependency checks + circuit breaker states
- [ ] Health status injected into agent prompt when services are degraded
- [ ] Agent can tell users about known issues naturally
- [ ] CORS configurable via environment variable
- [ ] Production CORS locked to specific origins
- [ ] Queue full → 503 with user-friendly message
- [ ] Redis-backed rate limiter available for multi-instance deployment
- [ ] Unit tests for rate limiter, circuit breaker, and health checks
