"""Transactional email service.

Providers:
  console  — logs the email to stdout (default for dev/prototype)
  resend   — sends via Resend API (https://resend.com)
  sendgrid — sends via SendGrid (legacy/alternative)

The recipient address is ALWAYS fetched from the registration database,
never from user input. This service is the sole component that touches
real email addresses.

Configure via .env:
  EMAIL_PROVIDER=console          # or "resend"
  EMAIL_FROM_ADDRESS=assistant@erleah.com
  EMAIL_FROM_NAME=Erleah Conference Assistant
  RESEND_API_KEY=re_...           # only needed for provider=resend
"""

from __future__ import annotations

import textwrap
import re

import structlog

from src.config import settings

logger = structlog.get_logger()


def _mask_email(email: str) -> str:
    """Mask email for safe logging: john@example.com → j***@example.com."""
    parts = email.split("@", 1)
    if len(parts) != 2:
        return "***"
    return f"{parts[0][0]}***@{parts[1]}"


def _html_to_text(html: str) -> str:
    """Rough HTML → plaintext for console display."""
    # Remove style blocks
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    # Remove script blocks
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    # Replace common block tags with newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(p|div|h[1-6]|li|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Remove remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Clean whitespace
    lines = [line.strip() for line in text.splitlines()]
    lines = [l for l in lines if l]
    return "\n".join(lines)


class EmailService:
    """Send transactional emails via the configured provider.

    All sends are logged with masked recipient addresses and trace IDs.
    Never log the full recipient email.
    """

    def __init__(self) -> None:
        self.provider = settings.email_provider
        self.from_address = settings.email_from_address
        self.from_name = settings.email_from_name
        self._resend_initialised = False

    def _ensure_resend(self) -> None:
        if self._resend_initialised:
            return
        try:
            import resend  # type: ignore[import]
            resend.api_key = settings.resend_api_key
            self._resend_initialised = True
        except ImportError:
            raise RuntimeError(
                "Resend SDK not installed. Run: uv add resend"
            )

    async def send(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str = "",
        reply_to: str | None = None,
        attachments: list[dict] | None = None,
        trace_id: str = "",
    ) -> dict:
        """Send an email.

        Args:
            to_email:    Recipient address (from DB, never from user input)
            subject:     Email subject line
            html_body:   HTML body
            text_body:   Plain-text fallback (optional)
            reply_to:    Reply-to address (for Phase 3B inbound routing)
            attachments: List of {url, filename} dicts
            trace_id:    For audit logging

        Returns:
            {"success": True, "message_id": "..."} or
            {"success": False, "error": "..."}
        """
        masked = _mask_email(to_email)
        logger.info(
            "email_service.send",
            provider=self.provider,
            to=masked,
            subject=subject,
            attachments=len(attachments or []),
            trace_id=trace_id,
        )

        if self.provider == "console":
            return self._send_console(to_email, subject, html_body, text_body, attachments)
        elif self.provider == "resend":
            return await self._send_resend(
                to_email, subject, html_body, text_body, reply_to, attachments, trace_id
            )
        elif self.provider == "sendgrid":
            return await self._send_sendgrid(
                to_email, subject, html_body, text_body, reply_to, attachments, trace_id
            )
        else:
            logger.error("email_service.unknown_provider", provider=self.provider)
            return {"success": False, "error": f"Unknown email provider: {self.provider}"}

    # ------------------------------------------------------------------
    # Console mode (dev / prototype)
    # ------------------------------------------------------------------

    def _send_console(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        attachments: list[dict] | None,
    ) -> dict:
        """Log the email to stdout instead of sending."""
        masked = _mask_email(to_email)
        body_preview = text_body or _html_to_text(html_body)
        body_preview = textwrap.shorten(body_preview, width=400, placeholder="…")
        att_names = [a.get("filename", "?") for a in (attachments or [])]

        separator = "─" * 60
        logger.info(
            "email_service.console",
            to=masked,
            subject=subject,
            attachments=att_names,
            body_preview=body_preview,
        )
        # Also print a formatted block to make it obvious in terminal
        print(f"\n{separator}")
        print("📧  EMAIL SEND [CONSOLE MODE]")
        print(f"{separator}")
        print(f"  To:          {masked}")
        print(f"  Subject:     {subject}")
        if att_names:
            print(f"  Attachments: {', '.join(att_names)}")
        print(f"  Body:        {body_preview}")
        print(f"{separator}\n")

        return {"success": True, "message_id": "console-mode"}

    # ------------------------------------------------------------------
    # Resend
    # ------------------------------------------------------------------

    async def _send_resend(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        reply_to: str | None,
        attachments: list[dict] | None,
        trace_id: str,
    ) -> dict:
        """Send via Resend API."""
        try:
            self._ensure_resend()
            import resend  # type: ignore[import]
            import httpx

            params: dict = {
                "from": f"{self.from_name} <{self.from_address}>",
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            }
            if text_body:
                params["text"] = text_body
            if reply_to:
                params["reply_to"] = reply_to

            # Download and attach PDFs if any
            if attachments:
                att_list = []
                async with httpx.AsyncClient(timeout=30.0) as client:
                    for att in attachments:
                        url = att.get("url", "")
                        filename = att.get("filename", "document.pdf")
                        if url:
                            try:
                                resp = await client.get(url)
                                if resp.status_code == 200:
                                    att_list.append({
                                        "filename": filename,
                                        "content": list(resp.content),
                                    })
                                else:
                                    logger.warning(
                                        "email_service.attachment_download_failed",
                                        url=url,
                                        status=resp.status_code,
                                    )
                            except Exception as e:
                                logger.warning(
                                    "email_service.attachment_download_error",
                                    url=url,
                                    error=str(e),
                                )
                if att_list:
                    params["attachments"] = att_list

            email = resend.Emails.send(params)
            message_id = email.get("id", "unknown") if isinstance(email, dict) else "sent"
            logger.info(
                "email_service.resend_sent",
                message_id=message_id,
                trace_id=trace_id,
            )
            return {"success": True, "message_id": message_id}

        except Exception as e:
            logger.error(
                "email_service.resend_failed",
                error=str(e),
                trace_id=trace_id,
            )
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # SendGrid (legacy / alternative)
    # ------------------------------------------------------------------

    async def _send_sendgrid(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        reply_to: str | None,
        attachments: list[dict] | None,
        trace_id: str,
    ) -> dict:
        """Send via SendGrid API."""
        try:
            import sendgrid  # type: ignore[import]
            from sendgrid.helpers.mail import (  # type: ignore[import]
                Mail,
                Attachment,
                FileContent,
                FileName,
                FileType,
            )
            import base64
            import httpx

            message = Mail(
                from_email=f"{self.from_name} <{self.from_address}>",
                to_emails=to_email,
                subject=subject,
                html_content=html_body,
            )
            if text_body:
                message.plain_text_content = text_body
            if reply_to:
                message.reply_to = reply_to

            if attachments:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    for att in attachments:
                        url = att.get("url", "")
                        filename = att.get("filename", "document.pdf")
                        if url:
                            resp = await client.get(url)
                            if resp.status_code == 200:
                                encoded = base64.b64encode(resp.content).decode()
                                message.attachment = Attachment(
                                    FileContent(encoded),
                                    FileName(filename),
                                    FileType("application/pdf"),
                                )

            sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
            response = sg.send(message)
            success = response.status_code in (200, 201, 202)
            msg_id = response.headers.get("X-Message-Id", "unknown")
            logger.info(
                "email_service.sendgrid_sent",
                message_id=msg_id,
                status=response.status_code,
                trace_id=trace_id,
            )
            return {"success": success, "message_id": msg_id}

        except Exception as e:
            logger.error(
                "email_service.sendgrid_failed",
                error=str(e),
                trace_id=trace_id,
            )
            return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_email_service: EmailService | None = None


def get_email_service() -> EmailService:
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
        logger.info(
            "email_service.initialized",
            provider=settings.email_provider,
            from_address=settings.email_from_address,
        )
    return _email_service
