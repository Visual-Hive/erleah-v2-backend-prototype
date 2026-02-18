"""Registration lookup tool (P3-02).

Searches for a conference registration by email or registration ID.
Returns ONLY safe, sanitised data — no email addresses, no full names,
no financial data. The security boundary lives in MockRegistrationService._sanitize().
"""

from __future__ import annotations

from typing import Any

import structlog

from src.tools.action_base import ActionBaseTool
from src.services.registration_mock import get_registration_service

logger = structlog.get_logger()


class RegistrationLookupTool(ActionBaseTool):
    """Look up a conference registration by email or registration ID.

    Use this when the user asks about:
    - Resending their badge, invoice, or registration confirmation
    - Checking their registration status
    - Any request that requires identifying their registration record

    IMPORTANT: You MUST have the user's registration email or registration ID
    before calling this tool. If they haven't provided one, ask them first.

    Args:
        identifier: The user's email address OR registration ID (e.g. REG-001)

    Returns safe data only: first name, registration type, available documents.
    Never returns email addresses, full names, or financial data.
    """

    name = "lookup_registration"
    description = (
        "Look up a conference registration by email or registration ID. "
        "Use when the user needs badge, invoice, or confirmation resent. "
        "Requires: identifier (email or reg ID). "
        "Returns: first_name, registration_type, available_documents, internal_id."
    )
    requires_identifier = True
    returns_private_data = False
    rate_limit_key = "registration_lookup"

    async def execute(self, args: dict[str, Any], context: dict) -> dict[str, Any]:
        identifier = (args.get("identifier") or "").strip()
        trace_id = context.get("trace_id", "")

        if not identifier:
            return {
                "success": False,
                "data": None,
                "error": "No identifier provided",
                "user_message": (
                    "Could you provide your registration email address "
                    "or registration ID? I'll look you up right away."
                ),
            }

        service = get_registration_service()
        conference_id = context.get("conference_id")
        is_email = "@" in identifier

        logger.info(
            "registration_lookup.attempt",
            type="email" if is_email else "reg_id",
            trace_id=trace_id,
            # identifier deliberately omitted — PII
        )

        if is_email:
            records = await service.lookup_by_email(
                email=identifier, conference_id=conference_id
            )

            if not records:
                logger.info("registration_lookup.not_found", type="email", trace_id=trace_id)
                return {
                    "success": True,
                    "data": {"found": False},
                    "error": None,
                    "user_message": (
                        "I couldn't find a registration with that email address. "
                        "Please double-check the email you used when registering — "
                        "it might be a different address. You can also try your registration ID if you have it."
                    ),
                }

            if len(records) > 1:
                # Multiple registrations — present options
                options = [
                    f"{r['registration_type']} at {r.get('conference_id', 'conference')} "
                    f"(ID: {r['registration_id']})"
                    for r in records
                ]
                logger.info(
                    "registration_lookup.multi_match",
                    count=len(records),
                    trace_id=trace_id,
                )
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
                    "user_message": (
                        f"I found {len(records)} registrations for that email. "
                        f"Which one do you need help with?"
                    ),
                }

            record = records[0]

        else:
            record = await service.lookup_by_reg_id(identifier)

            if not record:
                logger.info("registration_lookup.not_found", type="reg_id", trace_id=trace_id)
                return {
                    "success": True,
                    "data": {"found": False},
                    "error": None,
                    "user_message": (
                        "I couldn't find a registration with that ID. "
                        "Please check the ID and try again, or use your registration email instead."
                    ),
                }

        logger.info(
            "registration_lookup.found",
            reg_type=record["registration_type"],
            docs_available=record["available_documents"],
            trace_id=trace_id,
        )

        return {
            "success": True,
            "data": {
                "found": True,
                "multiple": False,
                **record,
            },
            "error": None,
            "user_message": None,  # Let the agent craft the natural response
        }
