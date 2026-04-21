# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WhatsApp webhook bot for **Fundastock**, a Mexican phone-case retail store. Built as a single-file FastAPI app (`main.py`) deployed on Railway. It receives WhatsApp messages via Meta's Cloud API, processes commands and free-text queries, and responds with text, images, documents, and interactive buttons/lists.

## Running Locally

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

No tests exist. No linter is configured.

## Required Environment Variables

- `WHATSAPP_TOKEN` / `PHONE_NUMBER_ID` — Meta WhatsApp Cloud API credentials
- `SUPABASE_URL` / `SUPABASE_KEY` — Supabase project for data storage
- `ANTHROPIC_API_KEY` — Powers Claude-based model matching for free-text queries
- `MAIN_APP_URL` — Base URL of the main Fundastock web app (serves PDFs, barcodes, purchase history)
- `VERIFY_TOKEN` — WhatsApp webhook verification token (default: `maxi3`)
- `CLAUDE_MODEL` — Anthropic model ID for RAG queries (default: `claude-haiku-4-5-20251001`)

## Architecture

**Single-file app** — all logic lives in `main.py`. There are no modules, routers, or separate config files.

### Message Flow

1. Meta sends webhooks to `POST /webhook`. The `receive_message` handler deduplicates by message ID (in-memory set, capped at 1000).
2. Text messages route through `process_text_message`:
   - `CANJEAR:<token>` — links a QR reward code to the sender's phone, sends confirmation + PDF ticket
   - `CLIENTE` — looks up accumulated reward credit and sends a Code128 barcode image
   - `COMPRAS` — fetches purchase history from the main app and formats a summary
   - Anything else → `handle_free_query` (Claude RAG)
3. Interactive replies (button/list selections) are routed by prefix:
   - `STOCK:<marca|modelo>` → `send_stock_for_modelo` (estilo picker)
   - `ESTILO:<modelo>|<estilo>` → `send_colors_for_estilo_modelo` (color breakdown + images)

### Stock Query Flow (3-step drill-down)

1. **Modelo** — Claude matches free-text to `inventario_modelos` catalog; shows total stock + estilo picker
2. **Estilo** — Shows per-color stock breakdown with estilo image from Supabase storage
3. **Colors** — Sends individual color images from `image_uploads` table / `images-colores` bucket

### External Dependencies

- **Supabase** (REST API via httpx): `qr_rewards`, `inventario_modelos`, `inventario1`, `inventario_colores`, `image_uploads`, `whatsapp_messages` tables; `images_estilos` storage bucket
- **Anthropic API** (direct HTTP, not SDK): Used in `claude_match` for fuzzy model name matching
- **Main Fundastock web app** (`MAIN_APP_URL`): Serves `/api/ticket-pdf/<token>`, `/api/customer-barcode/<phone>`, `/api/customer-compras/<phone>`
- **Meta WhatsApp Cloud API** (Graph API v21.0): Send text, images, documents, interactive buttons, and list messages

### Key Patterns

- All outbound messages are logged to `whatsapp_messages` via `log_message` (non-fatal on failure)
- `fetch_modelos` uses an in-memory cache refreshed every 5 minutes
- PDF sending does a preflight GET to verify the URL returns valid PDF content before asking WhatsApp to fetch it
- WhatsApp button IDs encode state as prefixed strings (e.g., `STOCK:Samsung|A54`, `ESTILO:A54|Funda Silicon`)
