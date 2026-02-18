"""Mock registration service for prototype testing.

Returns realistic dummy registration data so the tool flow can be tested
end-to-end through the real agent without a real registration endpoint.

Replace this with RegistrationService (real Directus queries) in production.
"""

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Dummy data — realistic fields with placeholder PDF URLs
# ---------------------------------------------------------------------------

_MOCK_REGISTRATIONS: dict[str, dict] = {
    "john@example.com": {
        "internal_id": "reg-mock-001",
        "first_name": "John",
        "last_name": "Smith",          # Never returned to agent
        "registration_type": "Attendee",
        "registration_id": "REG-001",
        "conference_id": "conf-mock-2026",
        "email": "john@example.com",   # Never returned to agent
        "status": "confirmed",
        "badge_pdf_url": "https://dummy.erleah.com/badges/john-smith-2026.pdf",
        "invoice_pdf_url": "https://dummy.erleah.com/invoices/inv-2026-001.pdf",
        "confirmation_pdf_url": None,
    },
    "sarah@example.com": {
        "internal_id": "reg-mock-002",
        "first_name": "Sarah",
        "last_name": "Chen",
        "registration_type": "Speaker",
        "registration_id": "REG-002",
        "conference_id": "conf-mock-2026",
        "email": "sarah@example.com",
        "status": "confirmed",
        "badge_pdf_url": "https://dummy.erleah.com/badges/sarah-chen-2026.pdf",
        "invoice_pdf_url": None,
        "confirmation_pdf_url": "https://dummy.erleah.com/confirmations/conf-2026-002.pdf",
    },
    "multi@example.com": {
        "internal_id": "reg-mock-003",
        "first_name": "Alex",
        "last_name": "Jordan",
        "registration_type": "Exhibitor",
        "registration_id": "REG-003",
        "conference_id": "conf-mock-2026",
        "email": "multi@example.com",
        "status": "confirmed",
        "badge_pdf_url": "https://dummy.erleah.com/badges/alex-jordan-2026.pdf",
        "invoice_pdf_url": "https://dummy.erleah.com/invoices/inv-2026-003.pdf",
        "confirmation_pdf_url": "https://dummy.erleah.com/confirmations/conf-2026-003.pdf",
    },
    "multi2@example.com": {
        # Second record for multi@example.com (multi-match test)
        "internal_id": "reg-mock-004",
        "first_name": "Alex",
        "last_name": "Jordan",
        "registration_type": "Workshop Attendee",
        "registration_id": "REG-004",
        "conference_id": "conf-mock-workshop-2026",
        "email": "multi@example.com",
        "status": "confirmed",
        "badge_pdf_url": "https://dummy.erleah.com/badges/alex-jordan-workshop-2026.pdf",
        "invoice_pdf_url": "https://dummy.erleah.com/invoices/inv-workshop-2026-004.pdf",
        "confirmation_pdf_url": None,
    },
}

# Map internal IDs to email (for the email send path)
_ID_TO_EMAIL: dict[str, str] = {
    rec["internal_id"]: rec["email"]
    for rec in _MOCK_REGISTRATIONS.values()
    if "internal_id" in rec
}

# Map registration IDs to internal IDs
_REG_ID_TO_INTERNAL: dict[str, str] = {
    rec["registration_id"]: rec["internal_id"]
    for rec in _MOCK_REGISTRATIONS.values()
}

# Multi-match: alex has two registrations both keyed under multi@example.com
_MULTI_MATCH_EMAIL = "multi@example.com"
_MULTI_MATCH_RECORDS = ["reg-mock-003", "reg-mock-004"]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MockRegistrationService:
    """Fake registration service for end-to-end prototype testing.

    Returns safe (sanitised) data for search results, but keeps the full
    record internally so the email service can fetch the real email address.
    """

    async def lookup_by_email(
        self, email: str, conference_id: str | None = None
    ) -> list[dict]:
        """Find registrations by email. Returns sanitised records."""
        email = email.strip().lower()

        # Multi-match case
        if email == _MULTI_MATCH_EMAIL:
            records = [
                _MOCK_REGISTRATIONS[r]
                for r in [
                    "multi@example.com",
                    "multi2@example.com",  # second record stored differently
                ]
                if r in _MOCK_REGISTRATIONS
            ]
            # Actually, for multi, we store both records under the multi key and id key
            records = [
                _MOCK_REGISTRATIONS[k]
                for k in _MOCK_REGISTRATIONS
                if _MOCK_REGISTRATIONS[k].get("email") == email
            ]
            logger.info(
                "mock_registration.lookup_email",
                found=len(records),
                multi=True,
            )
            return [self._sanitize(r) for r in records]

        # Normal single-match case
        record = _MOCK_REGISTRATIONS.get(email)
        if not record or record.get("status") == "cancelled":
            logger.info("mock_registration.lookup_email", found=0)
            return []

        logger.info("mock_registration.lookup_email", found=1)
        return [self._sanitize(record)]

    async def lookup_by_reg_id(self, reg_id: str) -> dict | None:
        """Find a registration by reg ID. Returns sanitised record."""
        reg_id = reg_id.strip().upper()
        internal_id = _REG_ID_TO_INTERNAL.get(reg_id)
        if not internal_id:
            logger.info("mock_registration.lookup_reg_id", found=False)
            return None

        # Find record by internal ID
        for rec in _MOCK_REGISTRATIONS.values():
            if rec.get("internal_id") == internal_id:
                if rec.get("status") == "cancelled":
                    return None
                logger.info("mock_registration.lookup_reg_id", found=True)
                return self._sanitize(rec)
        return None

    async def get_email_for_registration(self, internal_id: str) -> str | None:
        """Get the email on file for a registration. ONLY for the email service."""
        return _ID_TO_EMAIL.get(internal_id)

    async def get_document_urls(self, internal_id: str) -> dict:
        """Get document URLs for a registration. ONLY for the email service."""
        for rec in _MOCK_REGISTRATIONS.values():
            if rec.get("internal_id") == internal_id:
                return {
                    "badge": rec.get("badge_pdf_url"),
                    "invoice": rec.get("invoice_pdf_url"),
                    "confirmation": rec.get("confirmation_pdf_url"),
                }
        return {"badge": None, "invoice": None, "confirmation": None}

    async def get_first_name(self, internal_id: str) -> str:
        """Get first name for email personalisation."""
        for rec in _MOCK_REGISTRATIONS.values():
            if rec.get("internal_id") == internal_id:
                return rec.get("first_name", "there")
        return "there"

    def _sanitize(self, record: dict) -> dict:
        """Strip private fields. SECURITY BOUNDARY — nothing private leaves here."""
        available_docs: list[str] = []
        if record.get("badge_pdf_url"):
            available_docs.append("badge")
        if record.get("invoice_pdf_url"):
            available_docs.append("invoice")
        if record.get("confirmation_pdf_url"):
            available_docs.append("confirmation")

        return {
            "internal_id": record["internal_id"],
            "first_name": record["first_name"],
            "registration_type": record["registration_type"],
            "registration_id": record["registration_id"],
            "conference_id": record.get("conference_id", ""),
            "available_documents": available_docs,
            "status": record.get("status", "confirmed"),
            # NO email, NO last_name, NO financial data, NO badge data
        }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_mock_service: MockRegistrationService | None = None


def get_registration_service() -> MockRegistrationService:
    """Return the mock registration service singleton.

    Swap this out for a real RegistrationService(DirectusClient) instance
    once the production endpoint is confirmed.
    """
    global _mock_service
    if _mock_service is None:
        _mock_service = MockRegistrationService()
        logger.info("registration_service.initialized", mode="mock")
    return _mock_service
