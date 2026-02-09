# P3-03: Email Service & Send Registration Email Tool
## Send Private Documents to Verified Email

**Priority:** 🔴 Required  
**Effort:** 1-2 days  
**Dependencies:** P3-01 (tool framework), P3-02 (registration lookup)  

---

## Goal

Build the `send_registration_email` tool and the underlying email service. When the agent calls this tool, it fetches the document URLs from Directus, composes a professional email, and sends it to the email address **on file** for that registration — never to an address provided in the chat.

---

## Email Service

### Provider Choice

Start with **SendGrid** (or **Resend** as a modern alternative). Both have:
- Free tier sufficient for conference volumes
- Python SDK
- HTML template support
- Delivery tracking
- Easy swap later if needed

### Implementation

```python
# src/services/email.py

import structlog
from src.config import settings

logger = structlog.get_logger()


class EmailService:
    """
    Send transactional emails.
    
    This service is the ONLY component that handles recipient email addresses.
    It gets the address directly from Directus — never from user input.
    """
    
    def __init__(self):
        self.provider = settings.email_provider  # "sendgrid" | "resend" | "console"
        self._client = None
    
    async def initialize(self):
        """Initialize the email provider client."""
        if self.provider == "sendgrid":
            import sendgrid
            self._client = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
        elif self.provider == "resend":
            import resend
            resend.api_key = settings.resend_api_key
            self._client = resend
        elif self.provider == "console":
            # Dev mode: log emails instead of sending
            logger.info("email_service_console_mode")
            self._client = None
    
    async def send(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        from_email: str | None = None,
        reply_to: str | None = None,
        attachments: list[dict] | None = None,
    ) -> dict:
        """
        Send an email.
        
        Returns:
            {"success": True, "message_id": "..."} or
            {"success": False, "error": "..."}
        """
        sender = from_email or settings.email_from_address  # e.g. "assistant@erleah.com"
        
        if self.provider == "console":
            # Dev mode: just log it
            logger.info(
                "email_send_console",
                to=to_email,
                subject=subject,
                body_length=len(html_body),
                attachments=len(attachments or []),
            )
            return {"success": True, "message_id": "console-dev-mode"}
        
        try:
            if self.provider == "sendgrid":
                return await self._send_sendgrid(sender, to_email, subject, html_body, reply_to, attachments)
            elif self.provider == "resend":
                return await self._send_resend(sender, to_email, subject, html_body, reply_to, attachments)
        except Exception as e:
            logger.error("email_send_failed", error=str(e), to=to_email[:3] + "***")
            return {"success": False, "error": str(e)}
    
    async def _send_sendgrid(self, sender, to_email, subject, html_body, reply_to, attachments):
        from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType
        import base64
        import httpx
        
        message = Mail(
            from_email=sender,
            to_emails=to_email,
            subject=subject,
            html_content=html_body,
        )
        
        if reply_to:
            message.reply_to = reply_to
        
        # Attach PDFs if provided
        if attachments:
            for att in attachments:
                # Download the PDF from URL
                async with httpx.AsyncClient() as client:
                    pdf_resp = await client.get(att["url"])
                    pdf_data = base64.b64encode(pdf_resp.content).decode()
                
                message.attachment = Attachment(
                    FileContent(pdf_data),
                    FileName(att["filename"]),
                    FileType("application/pdf"),
                )
        
        response = self._client.send(message)
        
        return {
            "success": response.status_code in (200, 201, 202),
            "message_id": response.headers.get("X-Message-Id", "unknown"),
        }
    
    async def _send_resend(self, sender, to_email, subject, html_body, reply_to, attachments):
        # Resend has a simpler API
        params = {
            "from": sender,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        }
        if reply_to:
            params["reply_to"] = reply_to
        
        # Resend supports URL attachments natively in some cases,
        # or we download and attach as base64
        
        email = self._client.Emails.send(params)
        return {"success": True, "message_id": email.get("id", "unknown")}
```

### Configuration

```python
# src/config.py additions

class Settings(BaseSettings):
    # Email
    email_provider: str = "console"          # "sendgrid" | "resend" | "console"
    email_from_address: str = "assistant@erleah.com"
    email_from_name: str = "Erleah Conference Assistant"
    sendgrid_api_key: str = ""
    resend_api_key: str = ""
    
    # Email rate limits
    email_max_per_session: int = 5           # Max emails per conversation
    email_max_per_hour_per_ip: int = 10      # Prevent abuse
    email_cooldown_seconds: int = 30         # Min seconds between emails to same reg
```

---

## Email Templates

### Badge Confirmation Email

```python
# src/services/email_templates.py

def badge_email(first_name: str, conference_name: str, badge_url: str | None) -> dict:
    """Generate badge confirmation email."""
    
    subject = f"Your Badge Confirmation — {conference_name}"
    
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #2563eb;">Your Badge Confirmation</h2>
        <p>Hi {first_name},</p>
        <p>As requested, here's your badge confirmation for <strong>{conference_name}</strong>.</p>
        
        {"<p>Your badge is attached to this email as a PDF.</p>" if badge_url else 
         "<p>Your badge will be available for collection at the registration desk.</p>"}
        
        <p>If you need anything else, just reply to this email or ask the conference assistant on the website.</p>
        
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
        <p style="color: #6b7280; font-size: 12px;">
            This email was sent by the {conference_name} AI Assistant at your request.
            If you didn't request this, you can safely ignore it.
        </p>
    </div>
    """
    
    attachments = []
    if badge_url:
        attachments.append({
            "url": badge_url,
            "filename": f"badge-{conference_name.lower().replace(' ', '-')}.pdf",
        })
    
    return {"subject": subject, "html": html, "attachments": attachments}


def invoice_email(first_name: str, conference_name: str, invoice_url: str | None) -> dict:
    """Generate invoice email."""
    
    subject = f"Your Invoice — {conference_name}"
    
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #2563eb;">Your Invoice</h2>
        <p>Hi {first_name},</p>
        <p>As requested, here's your invoice for <strong>{conference_name}</strong>.</p>
        
        {"<p>Your invoice is attached to this email as a PDF.</p>" if invoice_url else 
         "<p>We're preparing your invoice. It will be sent separately once ready.</p>"}
        
        <p>If you have any questions about your invoice, reply to this email.</p>
        
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
        <p style="color: #6b7280; font-size: 12px;">
            This email was sent by the {conference_name} AI Assistant at your request.
        </p>
    </div>
    """
    
    attachments = []
    if invoice_url:
        attachments.append({
            "url": invoice_url,
            "filename": f"invoice-{conference_name.lower().replace(' ', '-')}.pdf",
        })
    
    return {"subject": subject, "html": html, "attachments": attachments}


def confirmation_email(first_name: str, conference_name: str, confirmation_url: str | None) -> dict:
    """Generate registration confirmation email."""
    
    subject = f"Your Registration Confirmation — {conference_name}"
    
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #2563eb;">Registration Confirmation</h2>
        <p>Hi {first_name},</p>
        <p>As requested, here's your registration confirmation for <strong>{conference_name}</strong>.</p>
        
        {"<p>Your confirmation is attached to this email.</p>" if confirmation_url else 
         "<p>This email serves as your registration confirmation.</p>"}
        
        <p>We look forward to seeing you at the event!</p>
        
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
        <p style="color: #6b7280; font-size: 12px;">
            This email was sent by the {conference_name} AI Assistant at your request.
        </p>
    </div>
    """
    
    attachments = []
    if confirmation_url:
        attachments.append({
            "url": confirmation_url,
            "filename": f"confirmation-{conference_name.lower().replace(' ', '-')}.pdf",
        })
    
    return {"subject": subject, "html": html, "attachments": attachments}


# Template registry
TEMPLATES = {
    "badge": badge_email,
    "invoice": invoice_email,
    "confirmation": confirmation_email,
}
```

---

## The Send Tool

```python
# src/tools/registration_email.py

from typing import Any
from src.tools.base import BaseTool
from src.services.registration import RegistrationService, get_registration_service
from src.services.email import EmailService, get_email_service
from src.services.email_templates import TEMPLATES
import structlog

logger = structlog.get_logger()


class SendRegistrationEmailTool(BaseTool):
    """Send registration documents to the registrant's email on file."""
    
    name = "send_registration_email"
    description = """
    Send registration documents (badge, invoice, confirmation) to the user's 
    registered email address.
    
    Use this AFTER a successful lookup_registration. The user must have confirmed 
    they want the documents sent.
    
    SECURITY: This tool sends to the email ON FILE in the registration database, 
    NOT to any email the user provides in the chat. This is by design.
    
    Input:
        internal_id: The internal registration ID (from lookup result)
        documents: List of document types to send: ["badge", "invoice", "confirmation"]
    
    Returns:
        Confirmation that the email was sent (or error).
    """
    
    requires_identifier = False  # Already identified via lookup
    returns_private_data = False # Tool sends email, doesn't return private data
    rate_limit_key = "email_send"
    
    async def execute(self, args: dict[str, Any], context: dict) -> dict[str, Any]:
        internal_id = args.get("internal_id")
        documents = args.get("documents", [])
        
        if not internal_id:
            return {
                "success": False,
                "data": None,
                "error": "No registration ID provided",
                "user_message": "I need to look up your registration first. What's your registration email or ID?",
            }
        
        if not documents:
            return {
                "success": False,
                "data": None,
                "error": "No documents specified",
                "user_message": "What would you like me to send? I can send your badge, invoice, or registration confirmation.",
            }
        
        # Validate document types
        valid_docs = [d for d in documents if d in TEMPLATES]
        if not valid_docs:
            return {
                "success": False,
                "data": None,
                "error": f"Invalid document types: {documents}",
                "user_message": "I can send badge confirmations, invoices, or registration confirmations. Which would you like?",
            }
        
        registration_service = get_registration_service()
        email_service = get_email_service()
        
        # Get the email ON FILE (never from user input)
        recipient_email = await registration_service.get_email_for_registration(internal_id)
        if not recipient_email:
            return {
                "success": False,
                "data": None,
                "error": "Could not retrieve email for registration",
                "user_message": "I'm having trouble accessing your registration details. Please try again.",
            }
        
        # Get document URLs
        doc_urls = await registration_service.get_document_urls(internal_id)
        
        # Get registration details for email personalization
        # (We need first name and conference name for the template)
        record = await registration_service.lookup_by_reg_id_internal(internal_id)
        first_name = record.get("first_name", "there") if record else "there"
        conference_name = await get_conference_name(context.get("conference_id"))
        
        # Build reply-to address with encoded registration ID (for future Phase 3B)
        reply_to = f"assistant+{internal_id}@erleah.com"
        
        # Send emails for each requested document
        sent = []
        failed = []
        
        for doc_type in valid_docs:
            template_fn = TEMPLATES[doc_type]
            doc_url = doc_urls.get(doc_type)
            
            email_data = template_fn(
                first_name=first_name,
                conference_name=conference_name,
                **{f"{doc_type}_url": doc_url},
            )
            
            result = await email_service.send(
                to_email=recipient_email,
                subject=email_data["subject"],
                html_body=email_data["html"],
                reply_to=reply_to,
                attachments=email_data.get("attachments"),
            )
            
            if result["success"]:
                sent.append(doc_type)
                logger.info(
                    "registration_email_sent",
                    doc_type=doc_type,
                    trace_id=context.get("trace_id"),
                    # Do NOT log recipient email
                )
            else:
                failed.append(doc_type)
                logger.error(
                    "registration_email_failed",
                    doc_type=doc_type,
                    error=result.get("error"),
                    trace_id=context.get("trace_id"),
                )
        
        if sent and not failed:
            doc_list = ", ".join(sent)
            return {
                "success": True,
                "data": {"sent": sent, "failed": []},
                "error": None,
                "user_message": f"I've sent your {doc_list} to your registered email address. Please check your inbox (and spam folder) in the next few minutes.",
            }
        elif sent and failed:
            return {
                "success": True,
                "data": {"sent": sent, "failed": failed},
                "error": None,
                "user_message": f"I sent your {', '.join(sent)}, but had trouble with {', '.join(failed)}. Please try requesting {'that' if len(failed) == 1 else 'those'} again in a moment.",
            }
        else:
            return {
                "success": False,
                "data": {"sent": [], "failed": failed},
                "error": "All email sends failed",
                "user_message": "I'm having trouble sending emails right now. Please try again in a few minutes, or contact the registration desk for help.",
            }
```

---

## Dev/Console Mode

For development, use `email_provider: "console"` which logs emails instead of sending them. The devtools GUI can show these in the node detail panel:

```
[email_send_console] to=john@***, subject="Your Badge Confirmation — TechConf", body_length=847, attachments=1
```

---

## Testing

```python
async def test_send_badge_success():
    """Successful badge send returns confirmation."""
    result = await tool.execute(
        {"internal_id": "reg-123", "documents": ["badge"]},
        {"trace_id": "test", "conference_id": "conf-1"},
    )
    assert result["success"]
    assert "badge" in result["data"]["sent"]

async def test_send_uses_email_on_file():
    """Email must go to the registered address, not user input."""
    # This test verifies the email service receives the DB email,
    # not anything from the conversation
    await tool.execute(
        {"internal_id": "reg-123", "documents": ["badge"]},
        ctx,
    )
    sent_to = mock_email_service.send.call_args[1]["to_email"]
    assert sent_to == "real-email-from-db@example.com"

async def test_send_without_lookup_fails():
    """Can't send without a valid internal_id."""
    result = await tool.execute({"documents": ["badge"]}, ctx)
    assert not result["success"]

async def test_send_invalid_document_type():
    """Invalid doc types should be rejected gracefully."""
    result = await tool.execute(
        {"internal_id": "reg-123", "documents": ["passport"]},
        ctx,
    )
    assert not result["success"]

async def test_console_mode_logs_email():
    """In console mode, email should be logged not sent."""
    # Set provider to "console" and verify logger.info is called
```

---

## Acceptance Criteria

- [ ] `EmailService` with provider abstraction (SendGrid, Resend, Console)
- [ ] Console mode for development (logs emails, doesn't send)
- [ ] HTML email templates for badge, invoice, and confirmation
- [ ] Templates include conference branding and clear messaging
- [ ] `send_registration_email` tool registered in tool registry
- [ ] Tool fetches recipient email from Directus (NEVER from chat)
- [ ] Tool fetches document URLs and attaches PDFs
- [ ] Reply-to address encodes registration ID (prep for Phase 3B)
- [ ] Partial failure handling (some docs sent, some failed)
- [ ] Every email send logged with trace ID (but NOT recipient address)
- [ ] Email from address and provider configurable via settings
- [ ] Unit tests verify email goes to DB address, not user input
- [ ] Dev mode: emails visible in logs / devtools
