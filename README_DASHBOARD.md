# Analytics Dashboard — Fundastock WhatsApp Bot

Admin dashboard for reading conversations, annotating agent failures, tracking funnel metrics, and iterating the sales agent prompt.

## Setup

### 1. Run migration

Paste `migrations/002_dashboard.sql` into Supabase SQL Editor and run it. Creates 4 tables:
- `conversation_annotations` — your tags/notes on conversations
- `daily_campaign_metrics` — pre-aggregated metrics (refreshed hourly)
- `manual_ad_spend` — ad spend you enter manually
- `daily_review_reports` — Claude's daily analysis reports

### 2. Set environment variables on Railway

```
ADMIN_PASSWORD=your-login-password
ADMIN_SECRET_KEY=random-string-for-cookie-signing
```

`ADMIN_API_KEY` (already set) still works for API/cron calls via header.

### 3. Access

Go to `https://your-app.railway.app/admin/dashboard` → login with `ADMIN_PASSWORD`.

## Daily Review Workflow

1. **Login** → `/admin/dashboard`
2. **Metrics tab** → check funnel, campaign ROAS, drop-off histogram
3. **Conversations tab** → filter by date/stage, read transcripts
4. **Annotate** → click a turn, hit `1` (bad response), type a note, Save
5. **Reports tab** → read Claude's daily analysis of failed conversations
6. **Export** → CSV button for conversations, turns, annotations, orders
7. **Iterate** → use annotation notes + daily report suggestions to update `sales_agent/prompts.py`

## Keyboard Shortcuts (Conversations view)

| Key | Action |
|-----|--------|
| `j` / `k` | Next / previous conversation |
| `1` | Tag: Bad response |
| `2` | Tag: Missed upsell |
| `3` | Tag: Good close |
| `4` | Tag: Prompt gap |
| `5` | Tag: Tool failure |
| `6` | Tag: Other |
| `t` | Toggle human takeover |
| `?` | Show/hide shortcut help |

## Railway Cron Jobs

| Endpoint | Schedule | Header | Purpose |
|----------|----------|--------|---------|
| `POST /admin/tasks/refresh-metrics` | Every hour | `X-Admin-Key` | Refresh daily_campaign_metrics |
| `POST /admin/tasks/daily-review` | Daily 8am | `X-Admin-Key` | Generate Claude analysis of failed conversations |

## Architecture

```
/admin/login          → cookie-based auth (ADMIN_PASSWORD)
/admin/dashboard      → SPA: conversations + metrics + reports + ad spend
/admin/api/*          → JSON endpoints (conversations, transcript, annotations, funnel, etc.)
/admin/export/*.csv   → CSV exports
/admin/tasks/*        → cron endpoints (metrics refresh, daily review)
```

All dashboard code lives in `sales_agent/dashboard/`:
- `auth.py` — HMAC-signed session cookies
- `queries.py` — Supabase REST queries
- `metrics.py` — funnel calculations + Claude daily review
- `routes.py` — FastAPI endpoints
- `templates.py` — HTML page generators
- `static.py` — inline CSS + JS (no build step, no frameworks)

## Features

- WhatsApp-style dark theme conversation viewer
- Full transcript with tool calls (expandable), stage transitions, timestamps
- One-click annotation with severity + notes + prompt change suggestions
- 30-day funnel: Conversations → Qualified → Orders → Claimed → Paid
- Campaign performance table with ROAS
- Drop-off histogram by stage
- Time-of-day heatmap
- Daily trend chart (Chart.js)
- Human takeover + send-as-human from within dashboard
- Claude-powered daily review with pattern detection
- Mobile responsive
