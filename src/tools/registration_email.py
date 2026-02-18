"""Send registration documents tool (P3-03).

Sends badge, invoice, or confirmation PDFs to the email address ON FILE
for the registration — never to any email provided in chat.

Depends on: lookup_registration (to get the internal_id first).
"""

from __future__ import annotations

from typing import Any

import structlog

from src.tools.action_base import ActionBaseTool
from src.services.registration_mock import get_registration_service
from src.services.email import get_email_service
from src.services.email_templates import TEMPLATES, VALID_DOCUMENT_TYPES

logger = structlog.get_logger()

CONFERENCE_NAME_DEFAULT = "the conference"


class SendRegistrationEmailTool(ActionBaseTool):
    """Send registration documents (badge, invoice, confirmation) to the registered email.

    Use this AFTER a successful lookup_registration. The user must have confirmed
    they want the documents sent.

    SECURITY: Always sends to the email address stored in the registration database,
    NEVER to any email address the user mentions in the chat.

    Args:
        internal_id: The internal registration ID from the lookup result
        documents:   List of document types: ["badge"], ["invoice"], ["confirmation"],
                     or any combination
        conference_name: Optional display name for email subject/body
    """

    name = "send_registration_email"
    description = (
        "Send registration documents (badge, invoice, confirmation) to the user's registered email. "
        "ONLY call after a successful lookup_registration. "
        "Requires: internal_id (from lookup result), documents (list of types). "
        "Security: sends to DB email only, never to user-provided email."
    )
    requires_identifier = False  # Already identified via lookup
    returns_private_data = False  # Tool sends email, doesn't return private data
    rate_limit_key = "email_send"

    async def execute(self, args: dict[str, Any], context: dict) -> dict[str, Any]:
        internal_id = (args.get("internal_id") or "").strip()
        documents: list[str] = args.get("documents") or []
        conference_name = args.get("conference_name") or CONFERENCE_NAME_DEFAULT
        trace_id = context.get("trace_id", "")

        # --- Validate inputs ---
        if not internal_id:
            return {
                "success": False,
                "data": None,
                "error": "No internal_id provided",
                "user_message": (
                    "I need to look up your registration first. "
                    "What's your registration email or registration ID?"
                ),
            }

        if not documents:
            return {
                "success": False,
                "data": None,
                "error": "No documents specified",
                "user_message": (
                    "What would you like me to send? "
                    "I can send your badge, invoice, or registration confirmation."
                ),
            }

        # Filter to only valid doc types
        valid_docs = [d for d in documents if d in VALID_DOCUMENT_TYPES]
        invalid_docs = [d for d in documents if d not in VALID_DOCUMENT_TYPES]
        if invalid_docs:
            logger.warning(
                "send_registration_email.invalid_doc_types",
                invalid=invalid_docs,
                trace_id=trace_id,
            )
        if not valid_docs:
            return {
                "success": False,
                "data": None,
                "error": f"Invalid document types requested: {documents}",
                "user_message": (
                    "I can send badge confirmations, invoices, or registration confirmations. "
                    "Which would you like?"
                ),
            }

        # --- Fetch recipient email from DB (never from user) ---
        registration_service = get_registration_service()
        recipient_email = await registration_service.get_email_for_registration(internal_id)

        if not recipient_email:
            logger.error(
                "send_registration_email.no_email_found",
                internal_id=internal_id,
                trace_id=trace_id,
            )
            return {
                "success": False,
                "data": None,
                "error": "Could not retrieve email for registration",
                "user_message": (
                    "I'm having trouble accessing your registration details. "
                    "Please try again or contact the registration desk."
                ),
            }

        # --- Fetch document URLs and personalisation data ---
        doc_urls = await registration_service.get_document_urls(internal_id)
        first_name = await registration_service.get_first_name(internal_id)

        # Build reply-to with encoded registration ID (prep for Phase 3B)
        reply_to = f"assistant+{internal_id}@assistant.erleah.com"

        email_service = get_email_service()
        sent: list[str] = []
        failed: list[str] = []

        for doc_type in valid_docs:
            template_fn = TEMPLATES[doc_type]
            doc_url = doc_urls.get(doc_type)

            # Build the email
            # Each template takes (first_name, conference_name, {doc_type}_pdf_url)
            email_data = template_fn(  # type: ignore[operator]
                first_name=first_name,
                conference_name=conference_name,
                **{f"{doc_type}_pdf_url": doc_url},
            )

            result = await email_service.send(
                to_email=recipient_email,
                subject=email_data["subject"],
                html_body=email_data["html"],
                text_body=email_data.get("text", ""),
                reply_to=reply_to,
                attachments=email_data.get("attachments"),
                trace_id=trace_id,
            )

            if result.get("success"):
                sent.append(doc_type)
                logger.info(
                    "send_registration_email.sent",
                    doc_type=doc_type,
                    message_id=result.get("message_id"),
                    trace_id=trace_id,
                    # recipient email deliberately NOT logged
                )
            else:
                failed.append(doc_type)
                logger.error(
                    "send_registration_email.failed",
                    doc_type=doc_type,
                    error=result.get("error"),
                    trace_id=trace_id,
                )

        # --- Build response ---
        if sent and not failed:
            doc_list = " and ".join(sent) if len(sent) <= 2 else ", ".join(sent[:-1]) + f", and {sent[-1]}"
            return {
                "success": True,
                "data": {"sent": sent, "failed": [], "first_name": first_name},
                "error": None,
                "user_message": (
                    f"Done! I've sent your {doc_list} to your registered email address. "
                    "Please check your inbox (and spam folder) in the next few minutes."
                ),
            }
        elif sent and failed:
            return {
                "success": True,
                "data": {"sent": sent, "failed": failed, "first_name": first_name},
                "error": None,
                "user_message": (
                    f"I sent your {', '.join(sent)}, but had trouble with {', '.join(failed)}. "
                    f"Please try requesting {'that' if len(failed) == 1 else 'those'} again in a moment."
                ),
            }
        else:
            return {
                "success": False,
                "data": {"sent": [], "failed": failed},
                "error": "All email sends failed",
                "user_message": (
                    "I'm having trouble sending emails right now. "
                    "Please try again in a few minutes, or contact the registration desk for assistance."
                ),
            }
