"""HTML email templates for registration documents.

Each template function returns a dict with:
  subject: str
  html: str
  text: str          (plain-text fallback)
  attachments: list  (dicts with url + filename, may be empty)
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Shared styles
# ---------------------------------------------------------------------------

_STYLE = """
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
  font-size: 15px;
  line-height: 1.6;
  color: #1a1a2e;
  max-width: 600px;
  margin: 0 auto;
  padding: 0;
"""

_BRAND_COLOR = "#2563eb"
_LIGHT_BG = "#f8fafc"
_BORDER = "#e2e8f0"


def _wrap(body_html: str, conference_name: str) -> str:
    """Wrap body in a branded email shell."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="background:#f1f5f9; margin:0; padding:20px 0;">
  <div style="{_STYLE}">

    <!-- Header -->
    <div style="background:{_BRAND_COLOR}; border-radius:8px 8px 0 0; padding:24px 32px;">
      <div style="color:white; font-size:20px; font-weight:700; letter-spacing:-0.3px;">
        Erleah ✦ Conference Assistant
      </div>
      <div style="color:rgba(255,255,255,0.75); font-size:13px; margin-top:4px;">
        {conference_name}
      </div>
    </div>

    <!-- Body -->
    <div style="background:white; padding:32px; border:1px solid {_BORDER}; border-top:none;">
      {body_html}
    </div>

    <!-- Footer -->
    <div style="background:{_LIGHT_BG}; border:1px solid {_BORDER}; border-top:none;
                border-radius:0 0 8px 8px; padding:16px 32px;">
      <p style="color:#94a3b8; font-size:12px; margin:0; line-height:1.5;">
        This email was sent by the {conference_name} AI Assistant at your request.<br>
        If you didn't request this, you can safely ignore it.
      </p>
    </div>

  </div>
</body>
</html>"""


def _btn(label: str, url: str) -> str:
    return (
        f'<a href="{url}" style="display:inline-block; background:{_BRAND_COLOR}; '
        f"color:white; text-decoration:none; padding:12px 24px; border-radius:6px; "
        f'font-weight:600; font-size:14px; margin:16px 0;">{label}</a>'
    )


# ---------------------------------------------------------------------------
# Badge template
# ---------------------------------------------------------------------------


def badge_email(first_name: str, conference_name: str, badge_pdf_url: str | None) -> dict:
    """Generate badge confirmation email."""
    subject = f"Your Badge Confirmation — {conference_name}"

    if badge_pdf_url:
        attachment_html = f"""
        <div style="background:{_LIGHT_BG}; border:1px solid {_BORDER}; border-radius:6px;
                    padding:16px 20px; margin:20px 0;">
          <div style="font-size:13px; color:#64748b; margin-bottom:8px;">📎 Attached</div>
          <div style="font-weight:600;">badge-{conference_name.lower().replace(' ', '-')}.pdf</div>
        </div>
        <p>Your badge is attached to this email. Print it or show it on your phone at the registration desk.</p>
        """
        download_html = _btn("Download Badge PDF", badge_pdf_url)
    else:
        attachment_html = ""
        download_html = ""

    body = f"""
    <h2 style="margin:0 0 8px; font-size:22px; font-weight:700; color:{_BRAND_COLOR};">
      🎫 Your Badge Confirmation
    </h2>
    <p style="color:#64748b; margin:0 0 24px;">Requested via the Erleah Conference Assistant</p>

    <p>Hi {first_name},</p>
    <p>
      As requested, here's your badge confirmation for <strong>{conference_name}</strong>.
    </p>

    {attachment_html}
    {download_html}

    <hr style="border:none; border-top:1px solid {_BORDER}; margin:24px 0;">
    <p style="color:#64748b; font-size:13px;">
      Need anything else? Reply to this email or ask the Erleah assistant on the conference website.
    </p>
    """

    attachments = []
    if badge_pdf_url:
        attachments.append({
            "url": badge_pdf_url,
            "filename": f"badge-{conference_name.lower().replace(' ', '-')}.pdf",
        })

    return {
        "subject": subject,
        "html": _wrap(body, conference_name),
        "text": (
            f"Hi {first_name},\n\nYour badge confirmation for {conference_name}.\n"
            + (f"\nDownload: {badge_pdf_url}\n" if badge_pdf_url else "")
            + "\nErleah Conference Assistant"
        ),
        "attachments": attachments,
    }


# ---------------------------------------------------------------------------
# Invoice template
# ---------------------------------------------------------------------------


def invoice_email(
    first_name: str, conference_name: str, invoice_pdf_url: str | None
) -> dict:
    """Generate invoice email."""
    subject = f"Your Invoice — {conference_name}"

    if invoice_pdf_url:
        attachment_html = f"""
        <div style="background:{_LIGHT_BG}; border:1px solid {_BORDER}; border-radius:6px;
                    padding:16px 20px; margin:20px 0;">
          <div style="font-size:13px; color:#64748b; margin-bottom:8px;">📎 Attached</div>
          <div style="font-weight:600;">invoice-{conference_name.lower().replace(' ', '-')}.pdf</div>
        </div>
        <p>Your invoice is attached to this email as a PDF.</p>
        """
        download_html = _btn("Download Invoice PDF", invoice_pdf_url)
    else:
        attachment_html = (
            "<p>Your invoice is being prepared and will be sent as a separate email "
            "once it's ready.</p>"
        )
        download_html = ""

    body = f"""
    <h2 style="margin:0 0 8px; font-size:22px; font-weight:700; color:{_BRAND_COLOR};">
      🧾 Your Invoice
    </h2>
    <p style="color:#64748b; margin:0 0 24px;">Requested via the Erleah Conference Assistant</p>

    <p>Hi {first_name},</p>
    <p>
      As requested, here's your invoice for <strong>{conference_name}</strong>.
    </p>

    {attachment_html}
    {download_html}

    <hr style="border:none; border-top:1px solid {_BORDER}; margin:24px 0;">
    <p style="color:#64748b; font-size:13px;">
      Questions about your invoice? Reply to this email and a member of the team will help.
    </p>
    """

    attachments = []
    if invoice_pdf_url:
        attachments.append({
            "url": invoice_pdf_url,
            "filename": f"invoice-{conference_name.lower().replace(' ', '-')}.pdf",
        })

    return {
        "subject": subject,
        "html": _wrap(body, conference_name),
        "text": (
            f"Hi {first_name},\n\nYour invoice for {conference_name}.\n"
            + (f"\nDownload: {invoice_pdf_url}\n" if invoice_pdf_url else "")
            + "\nErleah Conference Assistant"
        ),
        "attachments": attachments,
    }


# ---------------------------------------------------------------------------
# Confirmation template
# ---------------------------------------------------------------------------


def confirmation_email(
    first_name: str, conference_name: str, confirmation_pdf_url: str | None
) -> dict:
    """Generate registration confirmation email."""
    subject = f"Your Registration Confirmation — {conference_name}"

    if confirmation_pdf_url:
        attachment_html = f"""
        <div style="background:{_LIGHT_BG}; border:1px solid {_BORDER}; border-radius:6px;
                    padding:16px 20px; margin:20px 0;">
          <div style="font-size:13px; color:#64748b; margin-bottom:8px;">📎 Attached</div>
          <div style="font-weight:600;">confirmation-{conference_name.lower().replace(' ', '-')}.pdf</div>
        </div>
        <p>Your registration confirmation is attached to this email.</p>
        """
        download_html = _btn("Download Confirmation PDF", confirmation_pdf_url)
    else:
        attachment_html = "<p>This email serves as your official registration confirmation.</p>"
        download_html = ""

    body = f"""
    <h2 style="margin:0 0 8px; font-size:22px; font-weight:700; color:{_BRAND_COLOR};">
      ✅ Registration Confirmed
    </h2>
    <p style="color:#64748b; margin:0 0 24px;">Requested via the Erleah Conference Assistant</p>

    <p>Hi {first_name},</p>
    <p>
      As requested, here's your registration confirmation for <strong>{conference_name}</strong>.
    </p>

    {attachment_html}
    {download_html}

    <hr style="border:none; border-top:1px solid {_BORDER}; margin:24px 0;">
    <p style="color:#64748b; font-size:13px;">
      We look forward to seeing you at the event! If you have any questions, reply to this email.
    </p>
    """

    attachments = []
    if confirmation_pdf_url:
        attachments.append({
            "url": confirmation_pdf_url,
            "filename": f"confirmation-{conference_name.lower().replace(' ', '-')}.pdf",
        })

    return {
        "subject": subject,
        "html": _wrap(body, conference_name),
        "text": (
            f"Hi {first_name},\n\nYour registration confirmation for {conference_name}.\n"
            + (f"\nDownload: {confirmation_pdf_url}\n" if confirmation_pdf_url else "")
            + "\nErleah Conference Assistant"
        ),
        "attachments": attachments,
    }


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, object] = {
    "badge": badge_email,
    "invoice": invoice_email,
    "confirmation": confirmation_email,
}

VALID_DOCUMENT_TYPES = set(TEMPLATES.keys())
