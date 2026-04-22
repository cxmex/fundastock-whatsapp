from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse, HTMLResponse, JSONResponse
from datetime import datetime
from dotenv import load_dotenv
import os
import json
import logging
import httpx

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Fundastock WhatsApp Bot")

# Mount sales agent admin router (imported after app is created, at bottom of file)

# --- Test mode: capture outbound messages instead of sending to WhatsApp ---
_test_mode = False
_test_responses: list[dict] = []

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "maxi3")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://gbkhkbfbarsnpbdkxzii.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imdia2hrYmZiYXJzbnBiZGt4emlpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3MzQzODAzNzMsImV4cCI6MjA0OTk1NjM3M30.mcOcC2GVEu_wD3xNBzSCC3MwDck3CIdmz4D8adU-bpI")
MAIN_APP_URL = os.getenv("MAIN_APP_URL", "https://web-production-c0d6.up.railway.app")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

SUPA_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# Track processed message IDs to avoid duplicates
processed_messages = set()

# In-memory cache of modelos (refreshed every ~5 min)
_modelos_cache: list[dict] = []
_modelos_cache_ts: float = 0


async def log_message(direction: str, phone_number: str, message_type: str = None,
                       text_body: str = None, command: str = None,
                       message_id: str = None, extra: dict = None):
    """Insert a row into whatsapp_messages. Failures are non-fatal."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SUPABASE_URL}/rest/v1/whatsapp_messages",
                headers=SUPA_HEADERS,
                json={
                    "direction": direction,
                    "phone_number": phone_number,
                    "message_type": message_type,
                    "text_body": (text_body or "")[:2000],
                    "command_matched": command,
                    "message_id": message_id,
                    "extra": extra or {},
                },
            )
            if resp.status_code >= 400:
                logger.warning(f"log_message HTTP {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        logger.warning(f"log_message failed: {e}")


async def send_whatsapp_message(to_number: str, message: str):
    if _test_mode:
        _test_responses.append({"type": "text", "body": message})
        return {"status": "test"}
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logger.error("Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID")
        return None

    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message},
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            logger.info(f"Sent text to {to_number}: {message[:80]}")
            await log_message("out", to_number, message_type="text", text_body=message)
            return resp.json()
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return None


async def send_whatsapp_document(to_number: str, doc_url: str, filename: str, caption: str = "") -> bool:
    """Send a PDF via WhatsApp using a public URL. Returns True on success."""
    if _test_mode:
        _test_responses.append({"type": "document", "url": doc_url, "filename": filename, "caption": caption})
        return True
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logger.error("Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID")
        return False

    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "document",
        "document": {
            "link": doc_url,
            "filename": filename,
            "caption": caption,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
            logger.info(f"Document send → status={resp.status_code} body={resp.text[:400]}")
            ok = resp.status_code < 400
            await log_message("out", to_number, message_type="document",
                              text_body=caption, extra={"url": doc_url, "filename": filename, "ok": ok})
            return ok
    except Exception as e:
        logger.error(f"Exception sending document: {e}")
        return False


async def preflight_pdf(url: str) -> tuple[bool, str]:
    """Verify the PDF URL is publicly reachable and returns a PDF before asking WhatsApp to fetch it."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url)
            ctype = resp.headers.get("content-type", "")
            size = len(resp.content)
            logger.info(f"PDF preflight → status={resp.status_code} type={ctype} size={size}")
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}"
            if "pdf" not in ctype.lower():
                return False, f"Content-Type={ctype}"
            if size < 200:
                return False, f"Too small ({size}B)"
            return True, "OK"
    except Exception as e:
        return False, str(e)


async def handle_canjear(from_number: str, token: str):
    """Associate phone_number with qr_token, send confirmation + PDF ticket."""
    token = token.strip()
    if not token:
        await send_whatsapp_message(from_number, "Codigo QR invalido.")
        return

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Look up the token
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/qr_rewards",
                headers=SUPA_HEADERS,
                params={
                    "select": "id,order_id,reward_amount,purchase_amount,phone_number,status",
                    "qr_token": f"eq.{token}",
                    "limit": "1",
                },
            )

            if resp.status_code != 200:
                logger.error(f"Supabase lookup failed: {resp.status_code} {resp.text}")
                await send_whatsapp_message(from_number, "Error consultando tu codigo. Intenta de nuevo.")
                return

            rows = resp.json()
            if not rows:
                await send_whatsapp_message(from_number, "Este codigo QR no es valido o ya expiro.")
                return

            row = rows[0]
            existing_phone = row.get("phone_number")
            status = row.get("status", "pending")
            reward = float(row.get("reward_amount", 0) or 0)
            order_id = row.get("order_id", "")
            purchase = float(row.get("purchase_amount", 0) or 0)

            # Guard: already claimed by another number
            if existing_phone and existing_phone != from_number:
                await send_whatsapp_message(
                    from_number,
                    "Este codigo QR ya fue registrado con otro numero. No se puede transferir."
                )
                return

            if status == "redeemed":
                await send_whatsapp_message(from_number, "Este credito ya fue usado en una compra.")
                return

            # Update: set phone_number, claimed_at, status='linked'
            # ('linked' = phone associated; 'redeemed' will happen when credit is used on a purchase)
            now_iso = datetime.utcnow().isoformat()
            update_resp = await client.patch(
                f"{SUPABASE_URL}/rest/v1/qr_rewards",
                headers=SUPA_HEADERS,
                params={"qr_token": f"eq.{token}"},
                json={
                    "phone_number": from_number,
                    "claimed_at": now_iso,
                    "status": "linked",
                },
            )
            if update_resp.status_code not in (200, 204):
                logger.error(f"Failed to update qr_rewards: {update_resp.status_code} {update_resp.text}")

        # Send confirmation text
        confirmation = (
            f"¡Gracias por tu compra en Fundastock!\n\n"
            f"📄 Ticket #{order_id}\n"
            f"💰 Total: ${purchase:0.2f}\n"
            f"🎁 Tu credito: ${reward:0.2f}\n\n"
            f"Usalo en tu proxima compra mostrando este chat."
        )
        await send_whatsapp_message(from_number, confirmation)

        # Send ticket PDF
        pdf_url = f"{MAIN_APP_URL}/api/ticket-pdf/{token}"
        ok, reason = await preflight_pdf(pdf_url)
        if not ok:
            logger.error(f"PDF preflight FAILED: {reason} — url={pdf_url}")
            await send_whatsapp_message(
                from_number,
                f"No pudimos generar tu ticket ahora mismo. Intenta abrirlo aqui:\n{pdf_url}"
            )
            return

        sent = await send_whatsapp_document(
            from_number,
            pdf_url,
            filename=f"ticket_{order_id}.pdf",
            caption=f"Tu ticket #{order_id}",
        )
        if not sent:
            logger.warning("Document send failed — falling back to text link")
            await send_whatsapp_message(
                from_number,
                f"Descarga tu ticket aqui:\n{pdf_url}"
            )

    except Exception as e:
        logger.error(f"Error in handle_canjear: {e}")
        await send_whatsapp_message(from_number, "Error procesando tu codigo. Intenta de nuevo en un momento.")


async def send_whatsapp_image(to_number: str, image_url: str, caption: str = "") -> bool:
    """Send an image via WhatsApp using a public URL."""
    if _test_mode:
        _test_responses.append({"type": "image", "url": image_url, "caption": caption})
        return True
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        return False
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "image",
        "image": {"link": image_url, "caption": caption},
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
            logger.info(f"Image send → status={resp.status_code} body={resp.text[:400]}")
            ok = resp.status_code < 400
            await log_message("out", to_number, message_type="image",
                              text_body=caption, extra={"url": image_url, "ok": ok})
            return ok
    except Exception as e:
        logger.error(f"Exception sending image: {e}")
        return False


async def handle_cliente(from_number: str):
    """Send the customer a QR code with their available credit that can be scanned at the POS."""
    logger.info(f"handle_cliente called from={from_number}")

    # Look up linked rewards
    rows = []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/qr_rewards",
                headers=SUPA_HEADERS,
                params={
                    "select": "id,reward_amount,status,order_id",
                    "phone_number": f"eq.{from_number}",
                    "status": "eq.linked",
                },
            )
            logger.info(f"qr_rewards lookup → status={resp.status_code} body={resp.text[:300]}")
            if resp.status_code == 200:
                rows = resp.json()
    except Exception as e:
        logger.error(f"Error querying rewards: {e}")

    total = round(sum(float(r.get("reward_amount", 0) or 0) for r in rows), 2)
    logger.info(f"Total credit for {from_number}: ${total} ({len(rows)} rows)")

    if total <= 0:
        await send_whatsapp_message(
            from_number,
            "Aun no tienes creditos disponibles.\n\nEscanea el QR de tus tickets para acumular 1% en cada compra."
        )
        return

    # Send a Code128 BARCODE (not a QR) because POS readers only read linear barcodes.
    # Append a timestamp query param so WhatsApp's media cache doesn't serve a stale image.
    import time as _time
    img_url = f"{MAIN_APP_URL}/api/customer-barcode/{from_number}?v={int(_time.time())}"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            pre = await client.get(img_url)
            logger.info(f"Barcode preflight → status={pre.status_code} type={pre.headers.get('content-type','')}")
            img_ok = pre.status_code == 200 and "image" in pre.headers.get("content-type", "").lower()
    except Exception as e:
        logger.error(f"Barcode preflight error: {e}")
        img_ok = False

    caption = (
        f"🎟️ Tu credito disponible: ${total:0.2f}\n\n"
        f"Muestra este codigo de barras al cajero en tu proxima compra para canjearlo."
    )

    if img_ok:
        sent = await send_whatsapp_image(from_number, img_url, caption)
        if sent:
            return
        logger.warning("send_whatsapp_image returned False; falling back to text link")

    await send_whatsapp_message(
        from_number,
        f"🎟️ Tu credito disponible: ${total:0.2f}\n\nAbre tu codigo aqui (muestralo al cajero):\n{img_url}"
    )


async def handle_compras(from_number: str):
    """Send the customer a summary of all their purchases with status (pendiente/canjeado)."""
    logger.info(f"handle_compras called from={from_number}")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{MAIN_APP_URL}/api/customer-compras/{from_number}",
                timeout=15,
            )
            if resp.status_code != 200:
                logger.error(f"compras endpoint error: {resp.status_code} {resp.text}")
                await send_whatsapp_message(from_number, "No se pudo consultar tu historial. Intenta de nuevo.")
                return
            data = resp.json()
    except Exception as e:
        logger.error(f"Error fetching compras: {e}")
        await send_whatsapp_message(from_number, "Error consultando historial.")
        return

    tickets = data.get("tickets", [])
    totals = data.get("totals", {})

    if not tickets:
        await send_whatsapp_message(
            from_number,
            "Aun no tienes compras registradas.\n\nEscanea el QR de tus tickets para empezar a acumular tu 1% de credito."
        )
        return

    lines = ["📋 *Historial de compras*", ""]
    # Show up to 20 most recent
    for t in tickets[:20]:
        order_id = t.get("order_id", "")
        amount = t.get("purchase_amount", 0)
        reward = t.get("reward_amount", 0)
        estado = t.get("estado", "pendiente")
        emoji = "✅" if estado == "canjeado" else "🕒"
        lines.append(f"{emoji} Ticket #{order_id}")
        lines.append(f"   Compra: ${amount:0.2f}  |  Credito: ${reward:0.2f}")
        lines.append(f"   Estado: *{estado}*")
        lines.append("")

    if len(tickets) > 20:
        lines.append(f"...y {len(tickets) - 20} mas.")
        lines.append("")

    lines.append(f"💰 *Credito pendiente:* ${totals.get('pendiente', 0):0.2f}")
    lines.append(f"✅ *Credito canjeado:* ${totals.get('canjeado', 0):0.2f}")
    lines.append("")
    lines.append("Escribe *CLIENTE* para obtener tu codigo de canje.")

    await send_whatsapp_message(from_number, "\n".join(lines))


async def send_whatsapp_buttons(to_number: str, body_text: str, buttons: list[tuple[str, str]]) -> bool:
    """Send interactive reply-buttons (max 3). buttons = [(id, title), ...]."""
    if _test_mode:
        _test_responses.append({"type": "buttons", "body": body_text, "buttons": [{"id": bid, "title": title} for bid, title in buttons[:3]]})
        return True
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        return False
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    btns = [
        {"type": "reply", "reply": {"id": bid[:256], "title": title[:20]}}
        for bid, title in buttons[:3]
    ]
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text[:1024]},
            "action": {"buttons": btns},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=payload)
            logger.info(f"Buttons send → status={resp.status_code} body={resp.text[:300]}")
            ok = resp.status_code < 400
            await log_message("out", to_number, message_type="interactive",
                              text_body=body_text, extra={"buttons": buttons, "ok": ok})
            return ok
    except Exception as e:
        logger.error(f"Exception sending buttons: {e}")
        return False


async def send_whatsapp_list(to_number: str, body_text: str, button_label: str,
                              items: list[tuple[str, str]]) -> bool:
    """Send interactive list message (up to 10 rows). items = [(id, title), ...]."""
    if _test_mode:
        _test_responses.append({"type": "list", "body": body_text, "button_label": button_label, "items": [{"id": rid, "title": title} for rid, title in items[:10]]})
        return True
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        return False
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    rows = [{"id": rid[:200], "title": title[:24]} for rid, title in items[:10]]
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body_text[:1024]},
            "action": {
                "button": button_label[:20],
                "sections": [{"title": "Opciones", "rows": rows}],
            },
        },
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=payload)
            logger.info(f"List send → status={resp.status_code} body={resp.text[:300]}")
            ok = resp.status_code < 400
            await log_message("out", to_number, message_type="interactive",
                              text_body=body_text, extra={"list": items, "ok": ok})
            return ok
    except Exception as e:
        logger.error(f"Exception sending list: {e}")
        return False


async def fetch_modelos() -> list[dict]:
    """Fetch all modelos from inventario_modelos (cached for ~5 min)."""
    import time as _t
    global _modelos_cache, _modelos_cache_ts
    if _modelos_cache and (_t.time() - _modelos_cache_ts) < 300:
        return _modelos_cache
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/inventario_modelos",
                headers={**SUPA_HEADERS, "Range": "0-999"},
                params={"select": "id,marca,modelo,tot_terex1", "limit": "1000"},
            )
            if resp.status_code == 200:
                _modelos_cache = resp.json()
                _modelos_cache_ts = _t.time()
                logger.info(f"Loaded {len(_modelos_cache)} modelos into cache")
    except Exception as e:
        logger.error(f"fetch_modelos error: {e}")
    return _modelos_cache


async def claude_match(user_query: str, modelos: list[dict]) -> dict:
    """Ask Claude to match the user's phone query to the modelos list."""
    if not ANTHROPIC_API_KEY:
        return {"error": "ANTHROPIC_API_KEY not configured"}

    # Build compact list (only models with any stock)
    lines = []
    for m in modelos:
        marca = (m.get("marca") or "").strip()
        modelo = (m.get("modelo") or "").strip()
        if not modelo:
            continue
        lines.append(f"{marca} | {modelo}")
    catalog = "\n".join(lines)

    system = (
        "You are a helpful inventory assistant for a Mexican phone-case retail store. "
        "Users write casually in Spanish. Your job is to match their query to exact 'MARCA | MODELO' "
        "rows in our catalog. Always respond ONLY with a single JSON object, no markdown, no prose."
    )
    user_msg = f"""Catalog (MARCA | MODELO, one per line):
{catalog}

User query: "{user_query}"

Respond with one of these JSON shapes:
1. Single match: {{"action":"match","modelo":"MARCA | MODELO"}}
2. Multiple candidates (2-10, for ambiguity like "A54" → Samsung A54 and Oppo A54):
   {{"action":"ambiguous","candidates":["MARCA | MODELO", ...]}}
3. No match found:
   {{"action":"no_match","message":"friendly Spanish message suggesting they clarify"}}
4. Not a model query (greeting, random chat):
   {{"action":"chat","message":"friendly Spanish reply, mention they can ask about a phone model or use CLIENTE/COMPRAS"}}

Output JSON only."""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 600,
                    "system": system,
                    "messages": [{"role": "user", "content": user_msg}],
                },
            )
            if resp.status_code >= 400:
                logger.error(f"Claude API error: {resp.status_code} {resp.text[:400]}")
                return {"error": f"claude {resp.status_code}"}
            data = resp.json()
            text = (data.get("content", [{}])[0] or {}).get("text", "").strip()
            # Extract JSON
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                import re
                m = re.search(r"\{.*\}", text, re.DOTALL)
                if m:
                    return json.loads(m.group())
                return {"error": "invalid_json", "raw": text[:200]}
    except Exception as e:
        logger.error(f"claude_match error: {e}")
        return {"error": str(e)}


def _safe_id(modelo_key: str) -> str:
    """Encode 'MARCA | MODELO' into a WhatsApp button id (must be <= 256 chars and safe)."""
    return ("STOCK:" + modelo_key.replace(" | ", "|"))[:256]


async def _fetch_inventario(modelo: str, estilo: str | None = None) -> list[dict]:
    """Fetch live rows from inventario1 for a modelo (optionally filtered by estilo)."""
    params = {
        "select": "barcode,color_id,estilo,estilo_id,terex1,terex2,name",
        "modelo": f"eq.{modelo}",
        "limit": "1000",
    }
    if estilo:
        params["estilo"] = f"eq.{estilo}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/inventario1",
                headers={**SUPA_HEADERS, "Range": "0-999"},
                params=params,
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.error(f"_fetch_inventario error: {e}")
    return []


async def _resolve_color_names(color_ids: list[int]) -> dict[int, str]:
    if not color_ids:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            ids = ",".join(str(c) for c in color_ids)
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/inventario_colores",
                headers=SUPA_HEADERS,
                params={"select": "id,color", "id": f"in.({ids})"},
            )
            if resp.status_code == 200:
                return {c["id"]: (c.get("color") or "") for c in resp.json()}
    except Exception:
        pass
    return {}


async def _fetch_estilo_images(estilo_id: int, limit: int = 3) -> list[str]:
    """Return up to `limit` public URLs from the images_estilos bucket for this estilo."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SUPABASE_URL}/storage/v1/object/list/images_estilos",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
                json={"prefix": f"{estilo_id}/", "limit": limit},
            )
            if resp.status_code == 200:
                files = resp.json()
                return [
                    f"{SUPABASE_URL}/storage/v1/object/public/images_estilos/{estilo_id}/{f['name']}"
                    for f in files if f.get("name") and f.get("id")
                ][:limit]
    except Exception as e:
        logger.error(f"_fetch_estilo_images error: {e}")
    return []


async def _fetch_color_images_by_cid(estilo_id: int) -> dict[int, list[str]]:
    """Return { color_id: [url, ...] } for images in the images-colores bucket (via image_uploads)."""
    out: dict[int, list[str]] = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/image_uploads",
                headers=SUPA_HEADERS,
                params={
                    "select": "public_url,color_id",
                    "estilo_id": f"eq.{estilo_id}",
                    "limit": "200",
                },
            )
            if resp.status_code == 200:
                for row in resp.json():
                    cid = row.get("color_id")
                    url = row.get("public_url")
                    if cid and url:
                        out.setdefault(cid, []).append(url)
    except Exception as e:
        logger.error(f"_fetch_color_images_by_cid error: {e}")
    return out


async def send_stock_for_modelo(from_number: str, modelo_key: str):
    """Step 1 of 3: show total stock + list of estilos with positive stock (picker)."""
    parts = modelo_key.split("|", 1) if "|" in modelo_key else modelo_key.split(" ", 1)
    marca = parts[0].strip() if len(parts) >= 1 else ""
    modelo = parts[1].strip() if len(parts) == 2 else modelo_key

    inv_rows = await _fetch_inventario(modelo)
    if not inv_rows:
        await send_whatsapp_message(from_number, f"No encontramos stock de *{modelo}*.")
        return

    total_t1 = 0
    total_t2 = 0
    by_estilo: dict[str, dict] = {}
    for r in inv_rows:
        t1 = int(r.get("terex1") or 0)
        t2 = int(r.get("terex2") or 0)
        total_t1 += t1
        total_t2 += t2
        est = (r.get("estilo") or "").strip() or "Sin estilo"
        cur = by_estilo.setdefault(est, {"t1": 0, "t2": 0})
        cur["t1"] += t1
        cur["t2"] += t2

    total_all = total_t1 + total_t2

    # Overview header
    header = [
        f"📱 *{marca} {modelo}*" if marca else f"📱 *{modelo}*",
        f"Stock total: *{total_all}* piezas  (T1: {total_t1} · T2: {total_t2})",
    ]

    # Estilos with positive stock, sorted
    estilos_pos = [
        (name, v["t1"], v["t2"]) for name, v in by_estilo.items()
        if (v["t1"] + v["t2"]) > 0
    ]
    estilos_pos.sort(key=lambda x: -(x[1] + x[2]))

    if not estilos_pos:
        header.append("\n⚠️ Sin stock en este momento.")
        await send_whatsapp_message(from_number, "\n".join(header))
        return

    header.append(f"\nTenemos *{len(estilos_pos)}* estilo(s) con stock:")
    await send_whatsapp_message(from_number, "\n".join(header))

    # Interactive picker for estilo
    if len(estilos_pos) <= 3:
        buttons = [
            (f"ESTILO:{modelo}|{name}"[:256], f"{name[:14]} ({t1+t2})"[:20])
            for name, t1, t2 in estilos_pos
        ]
        await send_whatsapp_buttons(from_number, "Elige un estilo para ver los colores:", buttons)
    else:
        rows = [
            (f"ESTILO:{modelo}|{name}"[:200], f"{name[:18]} ({t1+t2})"[:24])
            for name, t1, t2 in estilos_pos[:10]
        ]
        await send_whatsapp_list(from_number, "Elige un estilo:", "Ver estilos", rows)


async def send_colors_for_estilo_modelo(from_number: str, modelo: str, estilo: str):
    """Step 2: show colors for a specific estilo+modelo with images.
    Sends: estilo image(s) + text breakdown + one image per color with stock.
    """
    inv_rows = await _fetch_inventario(modelo, estilo=estilo)
    if not inv_rows:
        await send_whatsapp_message(from_number, f"Sin datos para *{estilo}* / {modelo}.")
        return

    # Aggregate by color + find estilo_id
    estilo_id = None
    by_color_id: dict[int, dict] = {}
    total_t1 = 0
    total_t2 = 0
    for r in inv_rows:
        t1 = int(r.get("terex1") or 0)
        t2 = int(r.get("terex2") or 0)
        total_t1 += t1
        total_t2 += t2
        if estilo_id is None:
            estilo_id = r.get("estilo_id")
        cid = r.get("color_id")
        if cid is None:
            continue
        cur = by_color_id.setdefault(cid, {"t1": 0, "t2": 0})
        cur["t1"] += t1
        cur["t2"] += t2

    color_names = await _resolve_color_names(list(by_color_id.keys()))

    # 1. Send estilo bucket image (if any)
    if estilo_id:
        estilo_imgs = await _fetch_estilo_images(int(estilo_id), limit=1)
        if estilo_imgs:
            await send_whatsapp_image(
                from_number,
                estilo_imgs[0],
                caption=f"🎨 {estilo}\n📱 {modelo}",
            )

    # 2. Send text breakdown
    lines = [
        f"*{estilo}* / {modelo}",
        f"Subtotal: *{total_t1 + total_t2}* piezas  (T1: {total_t1} · T2: {total_t2})",
        "",
        "*Colores disponibles:*",
    ]
    color_lines = []
    sorted_colors = sorted(by_color_id.items(), key=lambda kv: -(kv[1]["t1"] + kv[1]["t2"]))
    for cid, v in sorted_colors:
        total = v["t1"] + v["t2"]
        if total <= 0:
            continue
        name = color_names.get(cid, f"Color {cid}")
        color_lines.append(f"• {name}: *{total}*  (T1: {v['t1']} · T2: {v['t2']})")

    if color_lines:
        lines.extend(color_lines[:20])
    else:
        lines.append("⚠️ Sin stock en este momento.")

    await send_whatsapp_message(from_number, "\n".join(lines))

    # 3. Send color images (from image_uploads / images-colores bucket)
    if estilo_id:
        color_imgs_map = await _fetch_color_images_by_cid(int(estilo_id))
        sent = 0
        max_images = 5
        for cid, v in sorted_colors:
            if sent >= max_images:
                break
            total = v["t1"] + v["t2"]
            if total <= 0:
                continue
            urls = color_imgs_map.get(cid, [])
            if not urls:
                continue
            name = color_names.get(cid, f"Color {cid}")
            caption = f"{name} — {total} piezas"
            await send_whatsapp_image(from_number, urls[0], caption=caption)
            sent += 1


async def handle_free_query(from_number: str, text: str):
    """Non-command free-text query: use Claude to match and respond."""
    modelos = await fetch_modelos()
    if not modelos:
        await send_whatsapp_message(from_number, "No pude cargar el catalogo. Intenta de nuevo en un momento.")
        return

    result = await claude_match(text, modelos)
    action = result.get("action")

    if action == "match":
        await send_stock_for_modelo(from_number, result.get("modelo", ""))
    elif action == "ambiguous":
        candidates = result.get("candidates", [])[:10]
        if not candidates:
            await send_whatsapp_message(from_number, "No encontre ese modelo. Intenta con el nombre completo (ej. 'Samsung A54').")
            return
        body = f'Encontre varios modelos para "{text}". ¿Cual buscas?'
        if len(candidates) <= 3:
            buttons = [(_safe_id(c), c.split(" | ")[-1][:20]) for c in candidates]
            await send_whatsapp_buttons(from_number, body, buttons)
        else:
            rows = [(_safe_id(c), c.replace(" | ", " ")[:24]) for c in candidates]
            await send_whatsapp_list(from_number, body, "Ver modelos", rows)
    elif action == "no_match":
        msg = result.get("message") or "No encontramos ese modelo. ¿Puedes darme el nombre completo?"
        await send_whatsapp_message(from_number, msg)
    elif action == "chat":
        msg = result.get("message") or "Hola! Pregunta por un modelo o escribe CLIENTE / COMPRAS."
        await send_whatsapp_message(from_number, msg)
    else:
        logger.warning(f"Unhandled claude result: {result}")
        await send_whatsapp_message(from_number, "Lo siento, hubo un problema. Intenta de nuevo.")


async def process_text_message(from_number: str, text: str):
    """Route incoming text to the right handler."""
    txt = text.strip()
    upper = txt.upper()

    if upper.startswith("CANJEAR:"):
        token = txt.split(":", 1)[1]
        await log_message("in", from_number, message_type="text", text_body=txt, command="CANJEAR")
        await handle_canjear(from_number, token)
        return

    if upper == "CLIENTE":
        await log_message("in", from_number, message_type="text", text_body=txt, command="CLIENTE")
        await handle_cliente(from_number)
        return

    if upper == "COMPRAS":
        await log_message("in", from_number, message_type="text", text_body=txt, command="COMPRAS")
        await handle_compras(from_number)
        return

    # Store hours / horario
    horario_keywords = ["ABRE HOY", "ABREN HOY", "HORARIO", "ESTAN ABIERTOS", "A QUE HORA ABREN", "A QUE HORA CIERRAN"]
    if any(kw in upper for kw in horario_keywords):
        horario_msg = "Estamos abiertos de Lunes a Sabado de 10:30 am a 6:00 pm"
        await log_message("in", from_number, message_type="text", text_body=txt, command="HORARIO")
        await send_whatsapp_message(from_number, horario_msg)
        return

    # Sales agent routing (check for active conversation or referral)
    from sales_agent.router import route_message as sales_route
    handled = await sales_route(from_number, txt)
    if handled:
        return

    # Otherwise: free-text query → Claude RAG
    await log_message("in", from_number, message_type="text", text_body=txt, command="QUERY")
    await handle_free_query(from_number, txt)


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode and hub_verify_token:
        if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
            logger.info("Webhook verified!")
            return PlainTextResponse(content=hub_challenge, status_code=200)
        else:
            raise HTTPException(status_code=403, detail="Token mismatch")
    raise HTTPException(status_code=400, detail="Missing parameters")


@app.post("/webhook")
async def receive_message(request: Request):
    try:
        body = await request.json()
        logger.info(f"FULL PAYLOAD: {body}")

        if body.get("object") == "whatsapp_business_account":
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})

                    # Skip status updates (delivered, read, etc.)
                    if "statuses" in value:
                        logger.info("Skipping status update")
                        continue

                    for message in value.get("messages", []):
                        msg_id = message.get("id")

                        # Skip already processed messages (Meta can send duplicates)
                        if msg_id in processed_messages:
                            logger.info(f"Skipping duplicate message {msg_id}")
                            continue
                        processed_messages.add(msg_id)

                        # Keep set from growing forever
                        if len(processed_messages) > 1000:
                            processed_messages.clear()

                        from_number = message.get("from")
                        msg_type = message.get("type")

                        # Extract referral from Click-to-WhatsApp ads
                        referral = message.get("referral")
                        referral_context = None
                        if referral:
                            referral_context = {
                                "source_id": referral.get("source_id"),
                                "source_url": referral.get("source_url"),
                                "headline": referral.get("headline"),
                                "body": referral.get("body"),
                                "source_type": referral.get("source_type"),
                                "media_type": referral.get("media_type"),
                            }
                            logger.info(f"Ad referral from {from_number}: {referral_context}")

                        if msg_type == "text":
                            text_body = message.get("text", {}).get("body", "")
                            logger.info(f"From {from_number}: {text_body}")
                            if referral_context:
                                # Ad lead — route through sales agent
                                from sales_agent.router import route_message as sales_route
                                await sales_route(from_number, text_body, referral=referral_context)
                            else:
                                await process_text_message(from_number, text_body)

                        elif msg_type == "image":
                            # Handle incoming images (comprobantes, etc.)
                            image_data = message.get("image", {})
                            image_id = image_data.get("id", "")
                            image_caption = image_data.get("caption", "")
                            logger.info(f"Image from {from_number}: id={image_id} caption={image_caption}")
                            await log_message("in", from_number, message_type="image",
                                              text_body=image_caption, message_id=msg_id,
                                              extra={"image_id": image_id})
                            from sales_agent.router import route_image as sales_route_image
                            handled = await sales_route_image(from_number, image_id, image_caption)
                            if not handled:
                                logger.info(f"Image from {from_number} not handled by sales agent")

                        elif msg_type == "interactive":
                            interactive = message.get("interactive", {})
                            itype = interactive.get("type")
                            reply_id = ""
                            reply_title = ""
                            if itype == "button_reply":
                                reply_id = interactive.get("button_reply", {}).get("id", "")
                                reply_title = interactive.get("button_reply", {}).get("title", "")
                            elif itype == "list_reply":
                                reply_id = interactive.get("list_reply", {}).get("id", "")
                                reply_title = interactive.get("list_reply", {}).get("title", "")
                            logger.info(f"Interactive reply from {from_number}: id={reply_id} title={reply_title}")
                            await log_message("in", from_number, message_type="button_reply",
                                              text_body=reply_title, command="BUTTON_REPLY",
                                              message_id=msg_id, extra={"reply_id": reply_id})

                            if reply_id.startswith("STOCK:"):
                                modelo_key = reply_id[len("STOCK:"):]
                                await send_stock_for_modelo(from_number, modelo_key)
                            elif reply_id.startswith("ESTILO:"):
                                payload = reply_id[len("ESTILO:"):]
                                if "|" in payload:
                                    modelo_name, estilo_name = payload.split("|", 1)
                                    await send_colors_for_estilo_modelo(from_number, modelo_name, estilo_name)
                                else:
                                    await send_whatsapp_message(from_number, "Formato de seleccion invalido.")
                            else:
                                await send_whatsapp_message(from_number, "Opcion no reconocida.")

                        else:
                            logger.info(f"Ignoring message type: {msg_type}")
                            await log_message("in", from_number, message_type=msg_type,
                                              message_id=msg_id, extra={"payload": message})

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "ok"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# ─── Natural Language BI ─────────────────────────────────────────────────────

NL_SYSTEM_PROMPT = """Eres un analista de datos para Fundastock, una tienda de fundas para celular en CDMX con 1000+ SKUs.
Tienes acceso a una base de datos Supabase vía REST API. Tu trabajo: recibir preguntas en lenguaje natural, generar las queries necesarias, y responder con datos reales.

## TABLAS DISPONIBLES

### inventario_modelos — Catálogo de modelos de teléfono
Columnas: id, marca (str), modelo (str), ventas_totales (int)

### inventario1 — Inventario actual por barcode (cada fila = 1 SKU)
Columnas: id, barcode, name, terex1 (stock tienda 1), terex2 (stock tienda 2), precio, marca, modelo, modelo_id, estilo, estilo_id, color, color_id

### inventario_estilos — Catálogo de estilos (tipos de funda)
Columnas: id, nombre, prioridad, precio (precio venta), cost (costo), sold30, supplier

### inventario_colores — Catálogo de colores
Columnas: id, color (str)

### image_uploads — Fotos de productos
Columnas: id, estilo_id, color_id, public_url, lessthan50url (thumbnail)

### ventas_terex1 — Registro de ventas individuales
Columnas: id, fecha (YYYY-MM-DD), hora, order_id, name, estilo, estilo_id, modelo, modelo_id, cost, price, qty, marca, color, payment_method, created_at

### whatsapp_messages — Log de mensajes WhatsApp
Columnas: id, direction (in/out), phone_number, message_type, text_body, command_matched, extra (jsonb), created_at

### whatsapp_conversations — Estado de conversaciones del sales agent
Columnas: phone_number (PK), lead_source, campaign_id, ad_headline, lead_type, stage, captured_data (jsonb), human_takeover, created_at, updated_at

### sales_orders — Órdenes del sales agent
Columnas: id, phone_number, order_type, items (jsonb), total, expected_amount, payment_method, payment_status, created_at

### qr_rewards — Programa de lealtad QR
Columnas: id, qr_token, order_id, purchase_amount, reward_amount, phone_number, status (pending/linked/redeemed), created_at

### RPC: get_order_analysis(days_back: int) — Vista pre-calculada de stock + ventas
Retorna: estilo, modelo, color, stock_t1, stock_t2, stock_total, sold_total, revenue_total, avg_daily_sales, days_of_inventory

## SUPABASE REST API SYNTAX

Queries se hacen a: /rest/v1/{table}?select={columns}&{filters}
Filtros: column=eq.value, column=gt.value, column=gte.value, column=lt.value, column=lte.value, column=like.*text*, column=ilike.*text*, column=in.(val1,val2), column=not.is.null
Ordenar: order=column.desc o order=column.asc
Limitar: limit=N
RPC: POST /rest/v1/rpc/{function_name} con body JSON de params

## FORMATO DE RESPUESTA

Responde SOLO con JSON estricto (sin markdown, sin ```):

{
  "queries": [
    {
      "id": "q1",
      "method": "GET",
      "path": "/rest/v1/inventario1?select=modelo,estilo,color,terex1,terex2&modelo=eq.IPHONE 14&limit=100",
      "description": "Stock del iPhone 14"
    }
  ],
  "answer_template": "Texto con placeholders {{q1.count}} o {{q1.results}} que se llenarán con los datos reales",
  "display": "text | table | chart",
  "chart_config": null
}

Para RPC:
{
  "id": "q1",
  "method": "POST",
  "path": "/rest/v1/rpc/get_order_analysis",
  "body": {"days_back": 30},
  "description": "Análisis de ventas 30 días"
}

## display OPCIONES

- "text" — respuesta en prosa con datos insertados
- "table" — respuesta como tabla HTML. En answer_template pon las columnas y el query id
- "chart" — gráfica. Incluye chart_config:
  {"type": "bar|line|pie|doughnut", "label_field": "campo_x", "value_field": "campo_y", "title": "Titulo"}

## REGLAS

1. Siempre usa datos reales de las queries, NUNCA inventes números
2. Para stock actual usa inventario1 (terex1 + terex2)
3. Para ventas históricas usa ventas_terex1 o get_order_analysis RPC
4. Modelos se guardan en MAYÚSCULAS (ej: "IPHONE 14", "A54", "S25 ULTRA")
5. Responde en español mexicano, informal pero profesional
6. Si la pregunta no se puede responder con los datos disponibles, dilo
7. Limita queries a máximo 500 filas para performance
8. Para preguntas de "más vendido", "top", etc. usa get_order_analysis que ya tiene sold_total"""


NL_FORMAT_PROMPT = """Tienes los resultados de las queries de Supabase. Genera la respuesta final para el usuario.

Pregunta original: {question}
Plan original: {plan}

Resultados:
{results}

Responde con JSON estricto:
{{
  "answer": "Tu respuesta en texto, con los datos reales. Usa números exactos.",
  "display": "text | table | chart",
  "table_data": null,
  "chart_config": null
}}

Si display="table", table_data debe ser: {{"headers": ["Col1","Col2"], "rows": [["val1","val2"], ...]}}
Si display="chart", chart_config debe ser: {{"type":"bar|line|pie","labels":["a","b"],"datasets":[{{"label":"X","data":[1,2]}}],"title":"Titulo"}}
Si display="text", solo pon el answer.

Responde en español mexicano. Sé directo y conciso."""


NL_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fundastock — Pregunta lo que quieras</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, sans-serif; background: #0b141a; color: #e9edef; height: 100vh; display: flex; flex-direction: column; }
.header { padding: 16px 20px; background: #1a262d; border-bottom: 1px solid #2a3942; display: flex; align-items: center; gap: 12px; }
.header h1 { font-size: 18px; flex: 1; }
.header a { color: #53bdeb; font-size: 13px; text-decoration: none; }
#chat { flex: 1; overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.msg { max-width: 85%; padding: 10px 14px; border-radius: 10px; font-size: 14px; line-height: 1.6; }
.msg.user { background: #005c4b; align-self: flex-end; white-space: pre-wrap; }
.msg.bot { background: #202c33; align-self: flex-start; }
.msg.bot .answer { white-space: pre-wrap; }
.msg.bot table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }
.msg.bot th { text-align: left; padding: 6px 8px; background: #1a262d; color: #8696a0; font-size: 11px; text-transform: uppercase; }
.msg.bot td { padding: 6px 8px; border-bottom: 1px solid #2a3942; }
.msg.bot .chart-wrap { margin-top: 8px; max-height: 300px; }
.msg.bot .chart-wrap canvas { max-height: 280px; }
.thinking { color: #8696a0; font-size: 13px; padding: 8px 14px; align-self: flex-start; display: none; }
.thinking.show { display: block; }
#bar { display: flex; padding: 12px 20px; background: #202c33; gap: 8px; }
#bar input { flex: 1; padding: 12px; border-radius: 10px; border: none; background: #2a3942; color: #e9edef; font-size: 15px; outline: none; }
#bar input::placeholder { color: #8696a0; }
#bar button { background: #00a884; border: none; color: #fff; padding: 12px 24px; border-radius: 10px; cursor: pointer; font-size: 15px; }
#bar button:hover { background: #00c49a; }
.suggestions { padding: 8px 20px; display: flex; gap: 6px; flex-wrap: wrap; }
.suggestions button { background: #2a3942; color: #8696a0; border: 1px solid #3a4a54; padding: 6px 12px; border-radius: 16px; font-size: 12px; cursor: pointer; }
.suggestions button:hover { background: #3a4a54; color: #e9edef; }
</style>
</head>
<body>
<div class="header">
  <h1>Fundastock</h1>
  <a href="/test">Bot Test</a>
  <a href="/admin/dashboard">Admin</a>
</div>
<div id="chat">
  <div class="msg bot"><div class="answer">Hola! Soy tu asistente de datos de Fundastock. Preguntame lo que quieras sobre inventario, ventas, clientes, o el bot de WhatsApp.</div></div>
</div>
<div class="thinking" id="thinking">Consultando datos...</div>
<div class="suggestions">
  <button onclick="ask(this.textContent)">Cuales son los 10 modelos mas vendidos?</button>
  <button onclick="ask(this.textContent)">Cuanto stock total tenemos?</button>
  <button onclick="ask(this.textContent)">Cuantos mensajes de WhatsApp hemos recibido?</button>
  <button onclick="ask(this.textContent)">Top 5 estilos con mas revenue</button>
  <button onclick="ask(this.textContent)">Que modelos tienen menos de 5 piezas?</button>
</div>
<div id="bar">
  <input id="inp" placeholder="Pregunta sobre tu inventario, ventas, clientes..." autocomplete="off" />
  <button onclick="send()">Enviar</button>
</div>
<script>
const chat = document.getElementById('chat');
const inp = document.getElementById('inp');
const thinking = document.getElementById('thinking');
let chartCounter = 0;
inp.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

function addMsg(html, cls) {
  const d = document.createElement('div');
  d.className = 'msg ' + cls;
  d.innerHTML = html;
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return d;
}

function ask(text) {
  inp.value = text;
  send();
}

async function send() {
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  addMsg(esc(text), 'user');
  thinking.classList.add('show');

  try {
    const res = await fetch('/ask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: text})
    });
    const data = await res.json();

    if (data.error) {
      addMsg('<div class="answer">' + esc(data.error) + '</div>', 'bot');
    } else if (data.display === 'table' && data.table_data) {
      let html = '<div class="answer">' + esc(data.answer) + '</div>';
      html += '<table><thead><tr>' + data.table_data.headers.map(h => '<th>' + esc(h) + '</th>').join('') + '</tr></thead><tbody>';
      data.table_data.rows.forEach(row => {
        html += '<tr>' + row.map(c => '<td>' + esc(String(c)) + '</td>').join('') + '</tr>';
      });
      html += '</tbody></table>';
      addMsg(html, 'bot');
    } else if (data.display === 'chart' && data.chart_config) {
      const cid = 'chart' + (++chartCounter);
      let html = '<div class="answer">' + esc(data.answer) + '</div>';
      html += '<div class="chart-wrap"><canvas id="' + cid + '"></canvas></div>';
      const el = addMsg(html, 'bot');
      setTimeout(() => {
        const cfg = data.chart_config;
        new Chart(document.getElementById(cid), {
          type: cfg.type || 'bar',
          data: { labels: cfg.labels || [], datasets: (cfg.datasets || []).map(ds => ({...ds, borderColor: ds.borderColor || '#00a884', backgroundColor: ds.backgroundColor || 'rgba(0,168,132,0.6)'})) },
          options: { responsive: true, maintainAspectRatio: false, plugins: { title: { display: !!cfg.title, text: cfg.title || '', color: '#e9edef' }, legend: { labels: { color: '#8696a0' } } }, scales: { x: { ticks: { color: '#8696a0' } }, y: { ticks: { color: '#8696a0' }, beginAtZero: true } } }
        });
      }, 50);
    } else {
      addMsg('<div class="answer">' + esc(data.answer || 'Sin respuesta') + '</div>', 'bot');
    }
  } catch(e) {
    addMsg('<div class="answer">Error: ' + esc(e.message) + '</div>', 'bot');
  }
  thinking.classList.remove('show');
}
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def root():
    return NL_HTML


@app.post("/ask")
async def ask_question(request: Request):
    """Natural language query against Fundastock data."""
    body = await request.json()
    question = (body.get("question") or "").strip()
    if not question:
        return JSONResponse({"error": "No question provided"})

    if not ANTHROPIC_API_KEY:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not configured"})

    import re as _re

    # Step 1: Ask Claude to plan the queries
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            plan_resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": os.getenv("ANTHROPIC_SALES_MODEL", "claude-sonnet-4-6"),
                    "max_tokens": 2048,
                    "system": NL_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": question}],
                },
            )
            if plan_resp.status_code >= 400:
                logger.error(f"NL plan error: {plan_resp.status_code} {plan_resp.text[:300]}")
                return JSONResponse({"error": "Error consultando Claude", "answer": "Error consultando Claude"})

            raw = (plan_resp.json().get("content", [{}])[0] or {}).get("text", "").strip()
            # Parse JSON
            raw_clean = raw
            if raw_clean.startswith("```"):
                raw_clean = _re.sub(r"^```(?:json)?\s*", "", raw_clean)
                raw_clean = _re.sub(r"\s*```$", "", raw_clean)
            plan = json.loads(raw_clean)
    except json.JSONDecodeError:
        m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if m:
            try:
                plan = json.loads(m.group())
            except json.JSONDecodeError:
                return JSONResponse({"answer": raw, "display": "text"})
        else:
            return JSONResponse({"answer": raw, "display": "text"})
    except Exception as e:
        logger.error(f"NL plan error: {e}")
        return JSONResponse({"error": f"Error: {e}", "answer": f"Error: {e}"})

    # Step 2: Execute queries
    queries_results = {}
    async with httpx.AsyncClient(timeout=20) as client:
        for q in plan.get("queries", []):
            qid = q.get("id", "q1")
            method = q.get("method", "GET").upper()
            path = q.get("path", "")
            q_body = q.get("body")

            if not path:
                continue

            url = f"{SUPABASE_URL}{path}"
            try:
                if method == "POST":
                    resp = await client.post(url, headers=SUPA_HEADERS, json=q_body or {})
                else:
                    resp = await client.get(url, headers={**SUPA_HEADERS, "Range": "0-499"})

                if resp.status_code < 400:
                    data = resp.json()
                    queries_results[qid] = {
                        "count": len(data) if isinstance(data, list) else 1,
                        "results": data[:100] if isinstance(data, list) else data,
                        "total_rows": len(data) if isinstance(data, list) else 1,
                    }
                else:
                    queries_results[qid] = {"error": f"HTTP {resp.status_code}", "count": 0, "results": []}
            except Exception as e:
                queries_results[qid] = {"error": str(e), "count": 0, "results": []}

    # Step 3: Send results to Claude for formatting
    results_text = ""
    for qid, qr in queries_results.items():
        results_text += f"\n### {qid} ({qr.get('count',0)} rows)\n"
        if qr.get("error"):
            results_text += f"Error: {qr['error']}\n"
        else:
            results_text += json.dumps(qr["results"][:50], ensure_ascii=False, default=str)[:8000] + "\n"

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            fmt_resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": os.getenv("ANTHROPIC_SALES_MODEL", "claude-sonnet-4-6"),
                    "max_tokens": 4096,
                    "system": NL_FORMAT_PROMPT.format(
                        question=question,
                        plan=json.dumps(plan, ensure_ascii=False)[:2000],
                        results=results_text[:20000],
                    ),
                    "messages": [{"role": "user", "content": "Genera la respuesta final con los datos reales."}],
                },
            )
            if fmt_resp.status_code >= 400:
                return JSONResponse({"answer": f"Datos obtenidos pero error al formatear: {results_text[:500]}", "display": "text"})

            fmt_raw = (fmt_resp.json().get("content", [{}])[0] or {}).get("text", "").strip()
            fmt_clean = fmt_raw
            if fmt_clean.startswith("```"):
                fmt_clean = _re.sub(r"^```(?:json)?\s*", "", fmt_clean)
                fmt_clean = _re.sub(r"\s*```$", "", fmt_clean)

            try:
                result = json.loads(fmt_clean)
            except json.JSONDecodeError:
                m = _re.search(r"\{.*\}", fmt_raw, _re.DOTALL)
                if m:
                    result = json.loads(m.group())
                else:
                    result = {"answer": fmt_raw, "display": "text"}

            return JSONResponse(result)

    except Exception as e:
        logger.error(f"NL format error: {e}")
        return JSONResponse({"answer": f"Datos: {results_text[:1000]}", "display": "text"})


# ─── Test Page ───────────────────────────────────────────────────────────────

TEST_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Fundastock Bot Tester</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, sans-serif; background: #0b141a; color: #e9edef; height: 100vh; display: flex; flex-direction: column; }
  #chat { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 8px; }
  .msg { max-width: 65%; padding: 8px 12px; border-radius: 8px; font-size: 14px; line-height: 1.4; white-space: pre-wrap; word-wrap: break-word; }
  .msg.user { background: #005c4b; align-self: flex-end; }
  .msg.bot { background: #202c33; align-self: flex-start; }
  .msg.bot img { max-width: 260px; border-radius: 6px; margin-top: 4px; display: block; }
  .msg.bot .btn-row { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
  .msg.bot .btn-row button { background: #00a884; color: #fff; border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }
  .msg.bot .btn-row button:hover { background: #00c49a; }
  .msg.bot .doc-link { color: #53bdeb; text-decoration: underline; }
  #controls { padding: 10px; background: #1a262d; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  #controls select, #controls button { background: #2a3942; color: #e9edef; border: 1px solid #3a4a54; padding: 6px 10px; border-radius: 6px; font-size: 13px; }
  #controls button { background: #00a884; border: none; cursor: pointer; color: #fff; }
  #controls button:hover { background: #00c49a; }
  #controls label { font-size: 12px; color: #8696a0; }
  #bar { display: flex; padding: 10px; background: #202c33; gap: 8px; }
  #bar input { flex: 1; padding: 10px; border-radius: 8px; border: none; background: #2a3942; color: #e9edef; font-size: 14px; outline: none; }
  #bar button { background: #00a884; border: none; color: #fff; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 14px; }
  .spinner { display: none; align-self: flex-start; color: #8696a0; font-size: 13px; padding: 6px 12px; }
</style>
</head>
<body>
<div id="controls">
  <label>Simulate ad referral:</label>
  <select id="sim_referral">
    <option value="">Organic message (no ad)</option>
    <option value="fb_iphone17_retail">FB ad: iPhone 17 case (retail)</option>
    <option value="fb_mayoreo_starter">FB ad: Mayoreo starter kit</option>
    <option value="tiktok_variety_pack">TikTok ad: 3-pack variety</option>
  </select>
  <button onclick="simComprobante()">Simular foto comprobante</button>
  <button onclick="resetConv()">Reset Conversation</button>
  <a href="/admin/dashboard" style="color:#53bdeb;font-size:13px;margin-left:auto">Admin Dashboard →</a>
</div>
<div id="chat"></div>
<div class="spinner" id="spin">Typing...</div>
<div id="bar">
  <input id="inp" placeholder="Type a message..." autocomplete="off" />
  <button onclick="send()">Send</button>
</div>
<script>
const chat = document.getElementById('chat');
const inp = document.getElementById('inp');
const spin = document.getElementById('spin');
let firstMessage = true;
inp.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });

const FAKE_REFERRALS = {
  fb_iphone17_retail: {
    source_id: "test_fb_001", source_url: "https://fb.com/ads/test",
    headline: "Funda estilo iPhone 17 - Envio gratis", body: "La mejor funda para tu iPhone. Desde $149.",
    source_type: "ad", media_type: "image"
  },
  fb_mayoreo_starter: {
    source_id: "test_fb_002", source_url: "https://fb.com/ads/test",
    headline: "Vende fundas - Precio de mayoreo", body: "Mas de 1000 modelos. Minimo $1,000.",
    source_type: "ad", media_type: "image"
  },
  tiktok_variety_pack: {
    source_id: "test_tt_001", source_url: "https://tiktok.com/ads/test",
    headline: "3 fundas por $399", body: "Elige tus modelos favoritos. Envio gratis CDMX.",
    source_type: "tiktok_ad", media_type: "video"
  }
};

function addMsg(html, cls) {
  const d = document.createElement('div');
  d.className = 'msg ' + cls;
  d.innerHTML = html;
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return d;
}

function renderBot(r) {
  if (r.type === 'text') {
    addMsg(esc(r.body), 'bot');
  } else if (r.type === 'image') {
    addMsg('<img src="' + esc(r.url) + '"><br>' + esc(r.caption || ''), 'bot');
  } else if (r.type === 'document') {
    addMsg('<a class="doc-link" href="' + esc(r.url) + '" target="_blank">' + esc(r.filename) + '</a><br>' + esc(r.caption || ''), 'bot');
  } else if (r.type === 'buttons') {
    let html = esc(r.body) + '<div class="btn-row">';
    r.buttons.forEach(b => { html += '<button onclick="sendBtn(\\'' + esc(b.id) + '\\',\\'' + esc(b.title) + '\\')">' + esc(b.title) + '</button>'; });
    html += '</div>';
    addMsg(html, 'bot');
  } else if (r.type === 'list') {
    let html = esc(r.body) + '<div class="btn-row">';
    r.items.forEach(b => { html += '<button onclick="sendBtn(\\'' + esc(b.id) + '\\',\\'' + esc(b.title) + '\\')">' + esc(b.title) + '</button>'; });
    html += '</div>';
    addMsg(html, 'bot');
  }
}

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

async function send() {
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  addMsg(esc(text), 'user');
  spin.style.display = 'block';

  const payload = {text};

  // Include referral on first message if selected
  const refSel = document.getElementById('sim_referral').value;
  if (firstMessage && refSel && FAKE_REFERRALS[refSel]) {
    payload.referral = FAKE_REFERRALS[refSel];
    addMsg('[Ad referral: ' + refSel + ']', 'bot');
  }
  firstMessage = false;

  try {
    const res = await fetch('/test', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
    const data = await res.json();
    data.responses.forEach(renderBot);
  } catch(e) { addMsg('Error: ' + e.message, 'bot'); }
  spin.style.display = 'none';
}

async function sendBtn(id, title) {
  addMsg(esc(title), 'user');
  spin.style.display = 'block';
  try {
    const res = await fetch('/test', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({button_id: id, button_title: title}) });
    const data = await res.json();
    data.responses.forEach(renderBot);
  } catch(e) { addMsg('Error: ' + e.message, 'bot'); }
  spin.style.display = 'none';
}

async function simComprobante() {
  addMsg('[Simulating comprobante image]', 'user');
  spin.style.display = 'block';
  try {
    const res = await fetch('/test', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({simulate_comprobante: true}) });
    const data = await res.json();
    data.responses.forEach(renderBot);
  } catch(e) { addMsg('Error: ' + e.message, 'bot'); }
  spin.style.display = 'none';
}

async function resetConv() {
  firstMessage = true;
  try {
    await fetch('/test/reset', { method: 'POST' });
  } catch(e) {}
  chat.innerHTML = '';
  addMsg('Conversation reset. Select a referral type and send your first message.', 'bot');
}
</script>
</body>
</html>
"""

@app.get("/test", response_class=HTMLResponse)
async def test_page():
    return TEST_HTML

@app.post("/test")
async def test_send(request: Request):
    global _test_mode, _test_responses
    body = await request.json()
    text = body.get("text", "")
    button_id = body.get("button_id", "")
    button_title = body.get("button_title", "")
    referral = body.get("referral")
    simulate_comprobante = body.get("simulate_comprobante", False)

    _test_mode = True
    _test_responses = []
    fake_number = "5215500000000"

    try:
        if simulate_comprobante:
            # Simulate a comprobante image being sent
            from sales_agent.router import route_message as sales_route
            handled = await sales_route(fake_number, "[El usuario envió foto de comprobante]")
            if not handled:
                _test_responses.append({"type": "text", "body": "No active sales conversation for comprobante simulation."})
        elif button_id:
            # Simulate interactive reply
            if button_id.startswith("STOCK:"):
                modelo_key = button_id[len("STOCK:"):]
                await send_stock_for_modelo(fake_number, modelo_key)
            elif button_id.startswith("ESTILO:"):
                parts = button_id[len("ESTILO:"):].split("|", 1)
                if len(parts) == 2:
                    await send_colors_for_estilo_modelo(fake_number, parts[0], parts[1])
            else:
                await send_whatsapp_message(fake_number, f"Unknown button: {button_id}")
        elif text:
            if referral:
                # Route through sales agent with ad referral
                from sales_agent.router import route_message as sales_route
                await sales_route(fake_number, text, referral=referral)
            else:
                await process_text_message(fake_number, text)
    except Exception as e:
        logger.error(f"Test error: {e}")
        _test_responses.append({"type": "text", "body": f"Error: {e}"})
    finally:
        _test_mode = False

    return JSONResponse({"responses": _test_responses})


@app.post("/test/reset")
async def test_reset():
    """Reset the test conversation state."""
    fake_number = "5215500000000"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.delete(
                f"{SUPABASE_URL}/rest/v1/whatsapp_conversations",
                headers=SUPA_HEADERS,
                params={"phone_number": f"eq.{fake_number}"},
            )
            await client.delete(
                f"{SUPABASE_URL}/rest/v1/sales_conversation_turns",
                headers=SUPA_HEADERS,
                params={"phone_number": f"eq.{fake_number}"},
            )
    except Exception as e:
        logger.warning(f"Test reset error: {e}")
    return {"ok": True}


# --- Mount sales agent admin router ---
from sales_agent.admin import router as admin_router
app.include_router(admin_router)

# --- Mount analytics dashboard router ---
from sales_agent.dashboard.routes import router as dashboard_router
app.include_router(dashboard_router)
