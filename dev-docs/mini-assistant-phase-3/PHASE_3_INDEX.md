# Phase 3: Agent Tools — Secure Anonymous Data Access
## Design Document & Task Index

**Created:** February 2026  
**Status:** Design / Stretch Goal  
**Dependencies:** Phase 1 tasks (TASK-01 through TASK-06) completed  

---

## The Insight

Conference attendees frequently need access to their registration data — badge confirmations, invoices, schedule confirmations — but don't want to log in to get it. They just want to ask the chat widget on the conference homepage.

The anonymous mini-assistant can't show private data in the chat. But it *can* verify who someone is and send the data to their registered email. The email address on file becomes the authentication factor.

This creates a "magic wand" experience: an anonymous chat widget that can securely handle private data requests without ever exposing private data in the conversation itself.

---

## Security Model

This is what makes the whole thing work. Every design decision flows from one principle:

**Private data never appears in the chat. It only travels to the verified email on file.**

### How Verification Works

```
User: "Can you resend my badge?"
Agent: "Sure! What's your registration email or registration ID?"
User: "john@example.com"
                │
                ▼
        ┌─────────────────┐
        │ lookup_registration │
        │                     │
        │ Search Directus for │
        │ email or reg ID     │
        └────────┬────────────┘
                 │
                 ▼
        Returns ONLY:
        ✅ first_name: "John"
        ✅ registration_type: "Attendee"
        ✅ available_documents: ["badge", "invoice", "confirmation"]
        ✅ registration_id: "reg-abc123" (internal, for send tool)
        
        NEVER returns:
        ❌ full name
        ❌ email address
        ❌ badge details / QR code
        ❌ invoice amounts / payment info
        ❌ company details
        ❌ any PII beyond first name
                 │
                 ▼
Agent: "I found your registration, John! I can send your badge 
        confirmation to your registered email. Want me to go ahead?"
User: "Yes please"
                │
                ▼
        ┌──────────────────────┐
        │ send_registration_email │
        │                         │
        │ Sends to email ON FILE  │
        │ NOT to what user typed  │
        └────────┬────────────────┘
                 │
                 ▼
Agent: "Done! I've sent your badge to your registered email. 
        Check your inbox (and spam folder) shortly."
```

### Why This Is Secure

1. **No data leakage in chat**: Even if someone watches the screen, they see nothing private.
2. **Email-as-authentication**: The data goes to the email on record, not to whatever email someone types. If an attacker types someone else's email, the real owner gets the email (harmless, or even alerts them).
3. **Minimal confirmation data**: Showing "John" + "Attendee" is enough for the user to confirm "yes that's me" without revealing anything an attacker could exploit.
4. **Audit trail**: Every lookup and every email send is logged with trace ID, IP, timestamp.
5. **Rate limiting**: Can't brute-force email sends — strict limits per session and per IP.

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| User provides email not in system | "I couldn't find a registration with that email. Double-check the email you used to register, or try your registration ID." |
| User provides someone else's email | Lookup succeeds, but email goes to the owner. No harm done. |
| Multiple registrations for same email | Return options: "I found 2 registrations — one for TechConf 2026 and one for AI Summit. Which one?" |
| User asks to send to a different email | "For security, I can only send documents to the email address used during registration." |
| User asks to see the data in chat | "I can't display private registration details here, but I can send them to your registered email right away." |
| Rate limit exceeded | "I've sent several emails recently. For security, please wait a few minutes before requesting another." |

---

## Architecture

### Tool-Based Design (Not Node-Based)

These are **LangGraph tools**, not pipeline nodes. The agent decides when to use them based on conversation context. This is important because:

- Not every conversation needs registration tools
- The agent needs to gather information (email/reg ID) before calling the tool
- The agent might need to ask clarifying questions
- The agent decides which documents to send based on what the user asked for

### System Components

```
┌─────────────────────────────────────────────────────────┐
│                   LangGraph Pipeline                     │
│                                                          │
│  Existing nodes: fetch_data → plan → execute → respond   │
│                                                          │
│  NEW: Tool Registry (available to plan + execute nodes)  │
│  ┌──────────────────────┐  ┌──────────────────────────┐ │
│  │ lookup_registration  │  │ send_registration_email   │ │
│  │                      │  │                           │ │
│  │ Input: email or      │  │ Input: registration_id,  │ │
│  │        reg_id        │  │        document_types     │ │
│  │                      │  │                           │ │
│  │ Output: first_name,  │  │ Output: sent confirmation │ │
│  │   reg_type, avail    │  │   or error                │ │
│  │   docs, reg_id       │  │                           │ │
│  └──────────┬───────────┘  └──────────┬────────────────┘ │
│             │                         │                   │
└─────────────┼─────────────────────────┼───────────────────┘
              │                         │
              ▼                         ▼
      ┌──────────────┐         ┌──────────────────┐
      │   Directus   │         │   Email Service   │
      │   (lookup)   │         │   (SendGrid/SES)  │
      └──────────────┘         └──────────────────┘
```

### Email Service Integration

Options (in order of preference for this use case):

| Service | Why | Cost |
|---------|-----|------|
| **SendGrid** | Good API, templates, delivery tracking | Free tier: 100 emails/day |
| **AWS SES** | Cheapest at scale, reliable | $0.10 per 1000 emails |
| **Postmark** | Best deliverability, transactional focus | $1.25 per 1000 emails |
| **Resend** | Modern API, developer-friendly | Free tier: 100 emails/day |

The email service needs:
- HTML email templates (badge, invoice, confirmation)
- Attachment support (PDF badges, invoices)
- Delivery tracking (did the email actually send?)
- Bounce handling (email doesn't exist anymore)

### Data Flow for Document Retrieval

The badge PDF, invoice PDF, etc. need to come from somewhere:

```
Registration record in Directus
    │
    ├── badge_pdf_url: "https://storage.erleah.com/badges/reg-abc123.pdf"
    ├── invoice_pdf_url: "https://storage.erleah.com/invoices/reg-abc123.pdf"  
    ├── confirmation_pdf_url: "https://storage.erleah.com/confirmations/reg-abc123.pdf"
    │
    └── Or generate on-the-fly from registration data
```

Two approaches:
1. **Pre-generated PDFs** stored in S3/Azure Blob (most likely — the registration system probably already generates these)
2. **On-demand generation** from registration data (more complex, but no storage dependency)

The tool just needs to know where to find them. The email service attaches or links them.

---

## Future Extension: Email-Reply Assistant

Once the email tools are working, a natural next step is letting users reply to the email to ask follow-up questions:

```
Phase 3A (this task):
  User → Chat → Agent → Email with badge

Phase 3B (future):
  User replies to email → Inbound webhook → Agent → Email reply with private data
```

### How Email-Reply Would Work

```
1. User receives badge email from noreply+reg-abc123@assistant.erleah.com
2. User replies: "Can you also send my invoice?"
3. Inbound email webhook (SendGrid/SES) receives the reply
4. Webhook extracts:
   - Sender email (verification: matches email on file)
   - Registration ID (from the reply-to address encoding)
   - Message text
5. Triggers mini-assistant with:
   - Verified identity (email matches registration)
   - Registration context loaded
   - User's question
6. Agent processes and replies via email
   - Can include private data (it's going to verified email)
   - Can attach documents
```

This turns the email thread into a **secure private channel** between the user and the assistant, authenticated by the email address. The anonymous chat widget becomes the entry point, and the email becomes the authenticated continuation.

---

## Task Breakdown

| Task | File | Effort | Description |
|------|------|--------|-------------|
| P3-01 | [P3-01_TOOL_FRAMEWORK.md](./P3-01_TOOL_FRAMEWORK.md) | 1 day | Base tool class, tool registry, planner integration |
| P3-02 | [P3-02_REGISTRATION_LOOKUP.md](./P3-02_REGISTRATION_LOOKUP.md) | 1-2 days | lookup_registration tool + Directus queries |
| P3-03 | [P3-03_EMAIL_SERVICE.md](./P3-03_EMAIL_SERVICE.md) | 1-2 days | Email service, templates, send_registration_email tool |
| P3-04 | [P3-04_SECURITY_AND_AUDIT.md](./P3-04_SECURITY_AND_AUDIT.md) | 1 day | Rate limiting, audit trail, abuse prevention |

**Total estimated effort:** 4-6 days

---

## Open Questions

1. **Where are registration records in Directus?** — Need to identify the collection name and fields (email, reg ID, badge URL, invoice URL). Could be `registrations`, `attendees`, `orders`, etc.
2. **Are badge/invoice PDFs pre-generated?** — If yes, where are they stored? If no, can we generate them from registration data?
3. **Which email service?** — SendGrid is probably easiest to get started with (free tier). Can switch later.
4. **Reply-to address encoding** — For Phase 3B, how to encode the registration ID in the reply-to address for inbound routing.
5. **Multi-conference** — Does a single registration span one conference, or could a user have registrations across multiple conferences?
