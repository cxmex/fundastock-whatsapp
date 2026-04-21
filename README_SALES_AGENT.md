# Sales Agent — Fundastock WhatsApp Bot

Conversational sales agent for leads from Facebook/TikTok Click-to-WhatsApp ads.

## Architecture

```
                    Meta WhatsApp Cloud API
                            |
                     POST /webhook
                            |
                      main.py (FastAPI)
                     /      |       \
              CANJEAR    HORARIO    sales_agent/router.py
              CLIENTE               /        |        \
              COMPRAS          agent.py   tools.py   payments.py
              free-text RAG     |            |          |
                            Claude API   Supabase    Claude Vision
                          (Sonnet 4.6)               (comprobante)
                                |
                        sales_agent/admin.py
                         /admin/* endpoints
```

## Files

| File | Purpose |
|------|---------|
| `main.py` | Existing bot + routing to sales agent + webhook referral extraction + image handling |
| `sales_agent/prompts.py` | System prompts (sales agent + comprobante validator) |
| `sales_agent/state.py` | Load/save `whatsapp_conversations` + `sales_conversation_turns` |
| `sales_agent/agent.py` | Claude API call, JSON parsing, retry, tool execution loop |
| `sales_agent/tools.py` | 7 tool implementations + dispatcher |
| `sales_agent/payments.py` | Fingerprint amounts, payment instructions, comprobante validation, Telegram alerts |
| `sales_agent/router.py` | Decides sales_agent vs existing flows, image routing |
| `sales_agent/admin.py` | Admin endpoints, dashboard, cron tasks |
| `migrations/001_sales_agent.sql` | DB schema for 3 new tables |

## Setup

### 1. Run DB Migration

```bash
psql "postgresql://postgres:[PASSWORD]@db.[PROJECT].supabase.co:5432/postgres" \
  -f migrations/001_sales_agent.sql
```

### 2. Create Supabase Storage Bucket

Create a `comprobantes` bucket in Supabase Storage (public access for admin review).

Optionally upload price list PDFs to a `pricelists` bucket:
- `pricelists/retail.pdf`
- `pricelists/wholesale.pdf`

### 3. Set Environment Variables

Copy `.env.example` and fill in real values. On Railway, set these as environment variables.

**Never commit real CLABE/card numbers.** Only Railway env vars hold real payment data.

### 4. Run Locally

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 5. Test with `/test` Page

Open `http://localhost:8000/test`:

1. Select a referral type from the dropdown (e.g., "FB ad: iPhone 17 case")
2. Send your first message — it will be treated as an ad lead
3. Continue the conversation naturally
4. Use "Simular foto comprobante" to test the comprobante flow
5. Use "Reset Conversation" to start fresh

### 6. Configure Meta Click-to-WhatsApp Ads

In Meta Ads Manager, set the WhatsApp number linked to your `PHONE_NUMBER_ID`. The bot automatically detects the `referral` payload in incoming messages from ads.

## Admin Endpoints

All require `X-Admin-Key` header.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/dashboard` | GET | HTML dashboard (no key needed for the page itself) |
| `/admin/conversations?stage=escalated` | GET | List conversations by stage |
| `/admin/pending-verifications` | GET | Orders awaiting payment verification |
| `/admin/verify-payment/{order_id}` | POST | Verify or reject a payment `{"verified": true/false, "notes": "..."}` |
| `/admin/takeover/{phone_number}` | POST | Human takes over conversation |
| `/admin/release/{phone_number}` | POST | Return conversation to bot |

## Cron Tasks (Railway)

Configure these as Railway cron jobs:

| Endpoint | Schedule | Description |
|----------|----------|-------------|
| `/tasks/expire-unpaid-orders` | Every 30 min | Expires orders pending > 24h, notifies customer |
| `/tasks/escalate-stale-verifications` | Every 30 min | Alerts admin for payment_claimed > 4h without verification |

Both require the `X-Admin-Key` header.

## Payment Reconciliation Workflow

Daily admin workflow:

1. Open `/admin/dashboard`, enter admin key
2. Review "Pending Payment Verifications"
3. For each order: compare extracted comprobante data against bank statement
4. Click "Verify" or "Reject" — customer is notified automatically
5. Check "Escalated Conversations" for any needing human intervention

## Human Takeover

When the bot escalates (angry customer, complex issue):

1. Admin gets Telegram alert with context
2. Admin clicks "Take Over" on dashboard (or calls `POST /admin/takeover/{phone}`)
3. Bot stops responding to that number — admin replies manually via WhatsApp Business app
4. When resolved, admin clicks "Release to Bot" on dashboard

## Known Limitations / Roadmap

- **Factura auto-generation**: Currently a stub — factura data is collected but CFDI generation requires SAT integration
- **Bank API integration**: Payment reconciliation is manual; auto-matching via bank API would eliminate admin verification
- **Shipping provider integration**: Tracking numbers are stored but not auto-fetched from carriers
- **Multi-product orders**: Agent handles them but the UX could be improved with a cart summary
- **Rate limiting**: No per-number rate limiting on the sales agent Claude calls
