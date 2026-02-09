# P3-02: Registration Lookup Tool
## Secure Registration Search via Directus

**Priority:** 🔴 Required  
**Effort:** 1-2 days  
**Dependencies:** P3-01 (tool framework), TASK-04 (Directus integration)  

---

## Goal

Build the `lookup_registration` tool that searches Directus for a registration record by email or registration ID, and returns **only the minimum data needed** for the agent to confirm identity and offer to send documents.

---

## Security Rules (Non-Negotiable)

The tool MUST follow these rules. They're not suggestions:

1. **Never return email addresses** — the user provided it, we don't echo it back
2. **Never return full names** — first name only, for a natural "Hi John!" confirmation
3. **Never return financial data** — no invoice amounts, payment methods, order totals
4. **Never return badge/QR data** — no badge numbers, QR codes, access levels
5. **Only return**: first name, registration type, which documents are available, internal registration ID
6. **Log every lookup** — trace ID, timestamp, identifier type (email vs reg ID), found/not-found

---

## Implementation

### 1. Directus Registration Queries

First, discover the actual registration schema. The registration data may be in different collections depending on the Directus setup:

```python
# src/services/registration.py

import structlog
from src.services.directus import DirectusClient

logger = structlog.get_logger()


class RegistrationService:
    """
    Query registration data from Directus.
    
    IMPORTANT: This service deliberately limits what data it returns.
    It has access to full registration records but only exposes safe fields.
    """
    
    # =====================================================
    # CONFIGURE THESE based on your Directus schema
    # =====================================================
    REGISTRATION_COLLECTION = "registrations"  # or "attendees", "orders", etc.
    
    # Field mappings — update to match your schema
    FIELDS = {
        "id": "id",
        "email": "email",
        "first_name": "first_name",
        "last_name": "last_name",           # Fetched but NEVER returned
        "registration_type": "type",         # e.g. "attendee", "exhibitor", "speaker"
        "registration_id": "registration_id", # Human-readable reg ID
        "conference_id": "conference_id",
        "badge_pdf_url": "badge_pdf",        # URL or null
        "invoice_pdf_url": "invoice_pdf",    # URL or null
        "confirmation_pdf_url": "confirmation_pdf",
        "status": "status",                  # "confirmed", "cancelled", etc.
    }
    # =====================================================
    
    def __init__(self, directus: DirectusClient):
        self.directus = directus
    
    async def lookup_by_email(self, email: str, conference_id: str | None = None) -> list[dict]:
        """
        Find registrations by email address.
        
        Returns SAFE data only — see _sanitize_record().
        May return multiple records (multi-conference).
        """
        filters = {
            f"filter[{self.FIELDS['email']}][_eq]": email.strip().lower(),
        }
        if conference_id:
            filters[f"filter[{self.FIELDS['conference_id']}][_eq]"] = conference_id
        
        # Only fetch needed fields (don't pull everything)
        fetch_fields = ",".join([
            self.FIELDS["id"],
            self.FIELDS["first_name"],
            self.FIELDS["registration_type"],
            self.FIELDS["registration_id"],
            self.FIELDS["conference_id"],
            self.FIELDS["badge_pdf_url"],
            self.FIELDS["invoice_pdf_url"],
            self.FIELDS["confirmation_pdf_url"],
            self.FIELDS["status"],
            self.FIELDS["email"],  # Needed for email service, NEVER returned to agent
        ])
        
        resp = await self.directus._client.get(
            f"/items/{self.REGISTRATION_COLLECTION}",
            params={
                **filters,
                "fields": fetch_fields,
                "limit": 5,
            },
        )
        resp.raise_for_status()
        records = resp.json().get("data", [])
        
        # Sanitize: only return safe fields
        return [self._sanitize_record(r) for r in records if r.get(self.FIELDS["status"]) != "cancelled"]
    
    async def lookup_by_reg_id(self, reg_id: str) -> dict | None:
        """
        Find a single registration by registration ID.
        
        Returns SAFE data only.
        """
        resp = await self.directus._client.get(
            f"/items/{self.REGISTRATION_COLLECTION}",
            params={
                f"filter[{self.FIELDS['registration_id']}][_eq]": reg_id.strip().upper(),
                "fields": ",".join([
                    self.FIELDS["id"],
                    self.FIELDS["first_name"],
                    self.FIELDS["registration_type"],
                    self.FIELDS["registration_id"],
                    self.FIELDS["conference_id"],
                    self.FIELDS["badge_pdf_url"],
                    self.FIELDS["invoice_pdf_url"],
                    self.FIELDS["confirmation_pdf_url"],
                    self.FIELDS["status"],
                    self.FIELDS["email"],
                ]),
                "limit": 1,
            },
        )
        resp.raise_for_status()
        records = resp.json().get("data", [])
        
        if not records:
            return None
        
        record = records[0]
        if record.get(self.FIELDS["status"]) == "cancelled":
            return None
        
        return self._sanitize_record(record)
    
    async def get_email_for_registration(self, internal_id: str) -> str | None:
        """
        Get the email address for a registration.
        
        ONLY used by the email sending service — never returned to the agent.
        """
        resp = await self.directus._client.get(
            f"/items/{self.REGISTRATION_COLLECTION}/{internal_id}",
            params={"fields": self.FIELDS["email"]},
        )
        resp.raise_for_status()
        data = resp.json().get("data")
        return data.get(self.FIELDS["email"]) if data else None
    
    async def get_document_urls(self, internal_id: str) -> dict:
        """
        Get document URLs for a registration.
        
        ONLY used by the email sending service — never returned to the agent.
        """
        resp = await self.directus._client.get(
            f"/items/{self.REGISTRATION_COLLECTION}/{internal_id}",
            params={"fields": ",".join([
                self.FIELDS["badge_pdf_url"],
                self.FIELDS["invoice_pdf_url"],
                self.FIELDS["confirmation_pdf_url"],
            ])},
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        
        return {
            "badge": data.get(self.FIELDS["badge_pdf_url"]),
            "invoice": data.get(self.FIELDS["invoice_pdf_url"]),
            "confirmation": data.get(self.FIELDS["confirmation_pdf_url"]),
        }
    
    def _sanitize_record(self, record: dict) -> dict:
        """
        Strip a registration record down to SAFE fields only.
        
        This is the security boundary. Nothing private leaves this method.
        """
        available_docs = []
        if record.get(self.FIELDS["badge_pdf_url"]):
            available_docs.append("badge")
        if record.get(self.FIELDS["invoice_pdf_url"]):
            available_docs.append("invoice")
        if record.get(self.FIELDS["confirmation_pdf_url"]):
            available_docs.append("confirmation")
        
        return {
            "internal_id": record.get(self.FIELDS["id"]),
            "first_name": record.get(self.FIELDS["first_name"], ""),
            "registration_type": record.get(self.FIELDS["registration_type"], "attendee"),
            "registration_id": record.get(self.FIELDS["registration_id"], ""),
            "conference_id": record.get(self.FIELDS["conference_id"], ""),
            "available_documents": available_docs,
            "status": record.get(self.FIELDS["status"], "unknown"),
            # NO email, NO full name, NO financial data, NO badge data
        }
```

### 2. The Lookup Tool

```python
# src/tools/registration_lookup.py

from typing import Any
from src.tools.base import BaseTool
from src.services.registration import RegistrationService
import structlog

logger = structlog.get_logger()


class RegistrationLookupTool(BaseTool):
    """Search for a conference registration by email or registration ID."""
    
    name = "lookup_registration"
    description = """
    Look up a conference registration to help with badge, invoice, or confirmation requests.
    
    Use this when a user asks about:
    - Resending their badge or badge confirmation
    - Getting a copy of their invoice or receipt
    - Checking their registration status
    - Any request that requires identifying their registration
    
    IMPORTANT: Before calling this tool, you MUST have the user's registration email 
    or registration ID. If they haven't provided it, ask them first.
    
    Input:
        identifier: The user's email address OR registration ID
    
    Returns:
        First name, registration type, and which documents are available.
        NEVER returns private data — that gets sent via email only.
    """
    
    requires_identifier = True
    returns_private_data = False  # The tool itself returns only safe data
    rate_limit_key = "registration_lookup"
    
    async def execute(self, args: dict[str, Any], context: dict) -> dict[str, Any]:
        identifier = args.get("identifier", "").strip()
        
        if not identifier:
            return {
                "success": False,
                "data": None,
                "error": "No identifier provided",
                "user_message": "Could you provide your registration email or registration ID?",
            }
        
        registration_service = get_registration_service()
        conference_id = context.get("conference_id")
        
        # Determine if it's an email or reg ID
        is_email = "@" in identifier
        
        if is_email:
            records = await registration_service.lookup_by_email(
                email=identifier,
                conference_id=conference_id,
            )
            
            if not records:
                logger.info("registration_lookup_not_found", type="email", trace_id=context.get("trace_id"))
                return {
                    "success": True,
                    "data": {"found": False},
                    "error": None,
                    "user_message": "I couldn't find a registration with that email address. Please double-check the email you used when registering, or try your registration ID instead.",
                }
            
            if len(records) > 1:
                # Multiple registrations — ask user to clarify
                options = [
                    f"{r['registration_type']} (ID: {r['registration_id']})"
                    for r in records
                ]
                return {
                    "success": True,
                    "data": {
                        "found": True,
                        "multiple": True,
                        "count": len(records),
                        "options": options,
                        "records": records,
                    },
                    "error": None,
                    "user_message": f"I found {len(records)} registrations for that email. Which one do you need help with?",
                }
            
            record = records[0]
        
        else:
            record = await registration_service.lookup_by_reg_id(identifier)
            
            if not record:
                logger.info("registration_lookup_not_found", type="reg_id", trace_id=context.get("trace_id"))
                return {
                    "success": True,
                    "data": {"found": False},
                    "error": None,
                    "user_message": "I couldn't find a registration with that ID. Please check the ID and try again, or use your registration email instead.",
                }
        
        logger.info(
            "registration_lookup_found",
            trace_id=context.get("trace_id"),
            reg_type=record["registration_type"],
            docs_available=record["available_documents"],
        )
        
        return {
            "success": True,
            "data": {
                "found": True,
                "multiple": False,
                **record,
            },
            "error": None,
            "user_message": None,  # Let the agent craft the response
        }
```

### 3. Agent Prompt Guidance

Add to the response generator prompt so the agent knows how to handle lookup results:

```
## Registration Tool Results

When you have registration lookup results:
- Greet the user by first name: "I found your registration, {first_name}!"
- List what documents you can send: "I can send you your {badge/invoice/confirmation}."
- Always explain that documents will be sent to their registered email (don't say which email)
- Ask for confirmation before sending
- If not found, be helpful: suggest checking the email they registered with, or trying their reg ID
- NEVER reveal any private data in the chat — not even the email address

Example good response:
"I found your registration, Sarah! You're registered as an Attendee. I can send your badge 
confirmation and invoice to your registered email address. Would you like me to send one or both?"

Example bad response (NEVER DO THIS):
"I found Sarah Johnson (sarah@company.com), registered for TechConf. Your badge number is B-4521."
```

---

## Testing

```python
async def test_lookup_by_email_found():
    """Successful email lookup returns sanitized data."""
    result = await tool.execute(
        {"identifier": "john@example.com"},
        {"trace_id": "test", "conference_id": "conf-1"},
    )
    assert result["success"]
    assert result["data"]["found"]
    assert "first_name" in result["data"]
    assert "email" not in result["data"]  # CRITICAL: no email in response
    assert "last_name" not in result["data"]  # No full name

async def test_lookup_by_email_not_found():
    """Missing email returns helpful suggestion."""
    result = await tool.execute(
        {"identifier": "nobody@example.com"},
        {"trace_id": "test"},
    )
    assert result["data"]["found"] is False
    assert "user_message" in result

async def test_sanitize_never_leaks_email():
    """Sanitize must strip email from every record."""
    service = RegistrationService(mock_directus)
    raw = {"email": "secret@example.com", "first_name": "John", ...}
    safe = service._sanitize_record(raw)
    assert "email" not in str(safe)

async def test_multiple_registrations():
    """Multiple matches should ask user to clarify."""
    # Mock: 2 records for same email
    result = await tool.execute({"identifier": "multi@example.com"}, ctx)
    assert result["data"]["multiple"]
    assert result["data"]["count"] == 2
```

---

## Acceptance Criteria

- [ ] `RegistrationService` queries Directus with configurable field mappings
- [ ] `_sanitize_record()` strips ALL private data — only returns safe fields
- [ ] `lookup_registration` tool registered and discoverable by planner
- [ ] Email lookup: returns safe record, handles not-found, handles multiple matches
- [ ] Reg ID lookup: returns safe record, handles not-found
- [ ] Every lookup logged with trace ID (but NOT the identifier value — PII)
- [ ] `get_email_for_registration()` exists but is ONLY callable by email service
- [ ] Agent prompt includes registration result handling guidance
- [ ] Unit tests verify no private data leakage in any code path
- [ ] Integration test against playground Directus (once schema is confirmed)
