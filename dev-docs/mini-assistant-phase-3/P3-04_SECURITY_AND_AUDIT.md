# P3-04: Security & Audit Trail
## Rate Limiting, Logging, and Abuse Prevention

**Priority:** 🔴 Required  
**Effort:** 1 day  
**Dependencies:** P3-01 (tool framework), P3-02 (lookup), P3-03 (email)  

---

## Goal

The registration tools handle private data lookups and trigger email sends. This task adds the security layers that prevent abuse and create an audit trail for every sensitive operation.

---

## 1. Tool-Specific Rate Limiting

General API rate limiting (TASK-05) protects against request floods. Tool rate limiting is more specific — it prevents someone from:

- Probing many email addresses to see which ones are registered
- Triggering many email sends to harass someone
- Brute-forcing registration IDs

### Implementation

```python
# src/tools/rate_limiter.py

import time
from collections import defaultdict
import structlog

logger = structlog.get_logger()

# In-memory counters (per-instance; use Redis for multi-instance)
_tool_counts: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))


class ToolRateLimiter:
    """
    Rate limiter specifically for tools.
    
    Limits are per-conversation (not per-IP) to keep it simple,
    since anonymous users don't have a persistent identity.
    """
    
    LIMITS = {
        "registration_lookup": {
            "per_minute": 5,       # Max 5 lookups/min per conversation
            "per_hour": 20,        # Max 20 lookups/hr
            "cooldown": 5,         # 5 seconds between lookups
        },
        "email_send": {
            "per_minute": 2,       # Max 2 email sends/min
            "per_hour": 5,         # Max 5 emails/hr per conversation
            "cooldown": 30,        # 30 seconds between sends
            "per_registration": 3, # Max 3 emails per registration per hour
        },
    }
    
    def check(self, rate_limit_key: str, conversation_id: str, extra_key: str | None = None) -> dict:
        """
        Check if a tool call is within rate limits.
        
        Returns:
            {"allowed": True} or
            {"allowed": False, "reason": "...", "retry_after": seconds}
        """
        limits = self.LIMITS.get(rate_limit_key)
        if not limits:
            return {"allowed": True}
        
        now = time.time()
        key = f"{rate_limit_key}:{conversation_id}"
        
        # Clean old entries
        _tool_counts[key]["calls"] = [
            t for t in _tool_counts[key]["calls"] if t > now - 3600
        ]
        
        calls = _tool_counts[key]["calls"]
        
        # Check cooldown
        if calls and (now - calls[-1]) < limits.get("cooldown", 0):
            wait = limits["cooldown"] - (now - calls[-1])
            return {
                "allowed": False,
                "reason": "Please wait a moment before trying again.",
                "retry_after": int(wait) + 1,
            }
        
        # Check per-minute
        recent_minute = [t for t in calls if t > now - 60]
        if len(recent_minute) >= limits.get("per_minute", 999):
            return {
                "allowed": False,
                "reason": "You've made several requests recently. Please wait a minute.",
                "retry_after": 60,
            }
        
        # Check per-hour
        if len(calls) >= limits.get("per_hour", 999):
            return {
                "allowed": False,
                "reason": "You've reached the hourly limit for this feature. Please try again later.",
                "retry_after": 3600,
            }
        
        # Check per-registration limit (for email sends)
        if extra_key and "per_registration" in limits:
            reg_key = f"{rate_limit_key}:reg:{extra_key}"
            _tool_counts[reg_key]["calls"] = [
                t for t in _tool_counts[reg_key]["calls"] if t > now - 3600
            ]
            reg_calls = _tool_counts[reg_key]["calls"]
            if len(reg_calls) >= limits["per_registration"]:
                return {
                    "allowed": False,
                    "reason": "I've already sent several emails for this registration. For security, please wait before requesting more.",
                    "retry_after": 3600,
                }
        
        return {"allowed": True}
    
    def record(self, rate_limit_key: str, conversation_id: str, extra_key: str | None = None):
        """Record a tool call for rate limiting."""
        now = time.time()
        key = f"{rate_limit_key}:{conversation_id}"
        _tool_counts[key]["calls"].append(now)
        
        if extra_key:
            reg_key = f"{rate_limit_key}:reg:{extra_key}"
            _tool_counts[reg_key]["calls"].append(now)


tool_rate_limiter = ToolRateLimiter()
```

### Integrate Into Base Tool

```python
# Update BaseTool.safe_execute() to check rate limits

async def safe_execute(self, args: dict[str, Any], context: dict) -> dict[str, Any]:
    # Check rate limit before executing
    if self.rate_limit_key:
        conversation_id = context.get("conversation_id", "unknown")
        extra_key = args.get("internal_id")  # For per-registration limits
        
        check = tool_rate_limiter.check(
            self.rate_limit_key, conversation_id, extra_key
        )
        
        if not check["allowed"]:
            logger.warning(
                "tool_rate_limited",
                tool=self.name,
                reason=check["reason"],
                trace_id=context.get("trace_id"),
            )
            return {
                "success": False,
                "data": None,
                "error": "rate_limited",
                "user_message": check["reason"],
            }
    
    try:
        result = await self.execute(args, context)
        
        # Record successful execution for rate limiting
        if self.rate_limit_key and result.get("success"):
            tool_rate_limiter.record(
                self.rate_limit_key,
                context.get("conversation_id", "unknown"),
                args.get("internal_id"),
            )
        
        return result
    except Exception as e:
        # ... existing error handling ...
```

---

## 2. Audit Trail

Every sensitive operation gets a structured log entry that can be queried later. These logs are separate from the general application logs — they're the security audit trail.

### Implementation

```python
# src/services/audit.py

import time
import structlog
from src.services.cache import get_cache_service

logger = structlog.get_logger("audit")


class AuditService:
    """
    Structured audit logging for sensitive operations.
    
    Audit logs are:
    - Written to structured logger (queryable in log aggregation)
    - Optionally stored in Redis (for real-time dashboards)
    - Optionally written to a Directus collection (for persistence)
    """
    
    async def log_lookup(
        self,
        trace_id: str,
        conversation_id: str,
        identifier_type: str,     # "email" or "reg_id"
        found: bool,
        registration_id: str | None = None,
        conference_id: str | None = None,
    ):
        """Log a registration lookup attempt."""
        logger.info(
            "audit.registration_lookup",
            trace_id=trace_id,
            conversation_id=conversation_id,
            identifier_type=identifier_type,
            found=found,
            registration_id=registration_id,
            conference_id=conference_id,
            timestamp=time.time(),
            # NEVER log the actual identifier (email/reg ID) — it's PII
        )
    
    async def log_email_send(
        self,
        trace_id: str,
        conversation_id: str,
        registration_id: str,
        document_types: list[str],
        success: bool,
        error: str | None = None,
    ):
        """Log an email send attempt."""
        logger.info(
            "audit.email_send",
            trace_id=trace_id,
            conversation_id=conversation_id,
            registration_id=registration_id,
            document_types=document_types,
            success=success,
            error=error,
            timestamp=time.time(),
            # NEVER log the recipient email
        )
    
    async def log_rate_limit_hit(
        self,
        trace_id: str,
        conversation_id: str,
        tool: str,
        limit_type: str,          # "per_minute", "per_hour", "cooldown", "per_registration"
    ):
        """Log when a rate limit is triggered."""
        logger.warning(
            "audit.rate_limit",
            trace_id=trace_id,
            conversation_id=conversation_id,
            tool=tool,
            limit_type=limit_type,
            timestamp=time.time(),
        )
    
    async def log_suspicious_activity(
        self,
        trace_id: str,
        conversation_id: str,
        activity_type: str,
        detail: str,
    ):
        """Log suspicious patterns (e.g. many failed lookups)."""
        logger.warning(
            "audit.suspicious",
            trace_id=trace_id,
            conversation_id=conversation_id,
            activity_type=activity_type,
            detail=detail,
            timestamp=time.time(),
        )


audit = AuditService()
```

### What Gets Audited

| Event | Logged Fields | NOT Logged |
|-------|--------------|------------|
| Registration lookup | trace_id, conversation_id, identifier_type (email/reg_id), found/not-found | The actual email or reg ID |
| Email send | trace_id, conversation_id, registration_id, doc types, success/fail | Recipient email |
| Rate limit hit | trace_id, conversation_id, tool, limit type | User identifier |
| Suspicious activity | trace_id, conversation_id, activity type | PII |

---

## 3. Suspicious Pattern Detection

Detect and log patterns that suggest abuse:

```python
# src/tools/abuse_detection.py

from collections import defaultdict
import time
import structlog
from src.services.audit import audit

logger = structlog.get_logger()

# Track patterns per conversation
_failed_lookups: dict[str, list[float]] = defaultdict(list)


async def check_lookup_pattern(conversation_id: str, found: bool, trace_id: str):
    """
    Detect suspicious lookup patterns.
    
    Flags:
    - 5+ failed lookups in a conversation (probing for valid emails)
    - 10+ lookups total in a conversation (fishing)
    """
    now = time.time()
    
    if not found:
        _failed_lookups[conversation_id].append(now)
        
        # Clean old entries (last hour)
        _failed_lookups[conversation_id] = [
            t for t in _failed_lookups[conversation_id] if t > now - 3600
        ]
        
        recent_fails = len(_failed_lookups[conversation_id])
        
        if recent_fails >= 5:
            await audit.log_suspicious_activity(
                trace_id=trace_id,
                conversation_id=conversation_id,
                activity_type="multiple_failed_lookups",
                detail=f"{recent_fails} failed lookups in this conversation",
            )
            
            # Return a slightly different message to avoid confirming which emails exist
            return {
                "suspicious": True,
                "message": "I'm having trouble finding registrations. If you need help, please contact the registration desk directly.",
            }
    
    return {"suspicious": False}
```

### Integrate Into Lookup Tool

```python
# In RegistrationLookupTool.execute()

# After lookup result:
pattern = await check_lookup_pattern(
    context.get("conversation_id"),
    found=bool(record),
    trace_id=context.get("trace_id"),
)

if pattern["suspicious"]:
    return {
        "success": True,
        "data": {"found": False},
        "error": None,
        "user_message": pattern["message"],
    }
```

---

## 4. Agent Security Instructions

Add to the response generator prompt:

```
## Security Rules for Registration Tools

You have access to tools that look up registrations and send documents. Follow these rules:

1. NEVER display private data in the chat — not email addresses, not badge numbers, not invoice amounts
2. When a lookup succeeds, confirm with FIRST NAME ONLY: "I found your registration, Sarah!"
3. Always say documents will be sent to "your registered email address" — never mention which email
4. If a user asks you to send to a different email, explain: "For security, I can only send to the email used during registration."
5. If a user asks to see their data in the chat, explain: "I can't display private information here, but I can send it to your registered email."
6. If multiple failed lookups occur, suggest contacting the registration desk
7. Never confirm or deny whether a specific email exists in the system to protect privacy
```

---

## 5. Prometheus Metrics

```python
# Add to src/monitoring/metrics.py

TOOL_CALLS = Counter(
    "tool_calls_total",
    "Tool calls",
    ["tool", "success"],
)

TOOL_RATE_LIMITS = Counter(
    "tool_rate_limits_total",
    "Tool rate limit hits",
    ["tool", "limit_type"],
)

EMAIL_SENDS = Counter(
    "email_sends_total",
    "Email sends",
    ["doc_type", "success"],
)

REGISTRATION_LOOKUPS = Counter(
    "registration_lookups_total",
    "Registration lookups",
    ["identifier_type", "found"],
)

SUSPICIOUS_ACTIVITIES = Counter(
    "suspicious_activities_total",
    "Suspicious activity detections",
    ["activity_type"],
)
```

---

## Testing

```python
async def test_rate_limit_blocks_rapid_lookups():
    """5+ lookups/min should be blocked."""
    limiter = ToolRateLimiter()
    for _ in range(5):
        result = limiter.check("registration_lookup", "conv-1")
        limiter.record("registration_lookup", "conv-1")
        assert result["allowed"]
    
    result = limiter.check("registration_lookup", "conv-1")
    assert not result["allowed"]

async def test_email_cooldown():
    """30 second cooldown between email sends."""
    limiter = ToolRateLimiter()
    limiter.record("email_send", "conv-1")
    result = limiter.check("email_send", "conv-1")
    assert not result["allowed"]
    assert result["retry_after"] > 0

async def test_per_registration_limit():
    """Max 3 emails per registration per hour."""
    limiter = ToolRateLimiter()
    for _ in range(3):
        limiter.record("email_send", "conv-1", extra_key="reg-123")
    result = limiter.check("email_send", "conv-1", extra_key="reg-123")
    assert not result["allowed"]

async def test_suspicious_pattern_detection():
    """5 failed lookups should trigger suspicious activity."""
    for _ in range(5):
        pattern = await check_lookup_pattern("conv-1", found=False, trace_id="test")
    assert pattern["suspicious"]

async def test_audit_log_no_pii():
    """Audit logs must never contain PII."""
    with capture_logs() as logs:
        await audit.log_lookup(
            trace_id="t1",
            conversation_id="c1",
            identifier_type="email",
            found=True,
        )
    
    log_text = str(logs)
    assert "email" not in log_text or "identifier_type" in log_text  # Only the type, not the value
    assert "@" not in log_text
```

---

## Acceptance Criteria

- [ ] Tool-specific rate limiter: lookups (5/min, 20/hr), email sends (2/min, 5/hr, 30s cooldown)
- [ ] Per-registration email limit (max 3/hr to same registration)
- [ ] Rate limit messages are user-friendly, not technical
- [ ] Audit trail: every lookup and email send logged with trace ID
- [ ] Audit logs NEVER contain PII (no emails, no names, no identifiers)
- [ ] Suspicious pattern detection: 5+ failed lookups flags the conversation
- [ ] Suspicious conversations get a generic "contact registration desk" message
- [ ] Agent prompt includes security rules for handling registration data
- [ ] Prometheus metrics for tool calls, rate limits, email sends, lookups, suspicious activity
- [ ] Rate limiter integrated into `BaseTool.safe_execute()`
- [ ] Unit tests for all rate limit scenarios and PII-free audit logging
