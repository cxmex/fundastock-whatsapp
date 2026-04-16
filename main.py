from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse
from datetime import datetime
import os
import json
import logging
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Fundastock WhatsApp Bot")

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


async def send_stock_for_modelo(from_number: str, modelo_key: str):
    """Look up stock for a 'MARCA | MODELO' key and send a text reply."""
    parts = modelo_key.split("|", 1) if "|" in modelo_key else modelo_key.split(" ", 1)
    marca = parts[0].strip() if len(parts) >= 1 else ""
    modelo = parts[1].strip() if len(parts) == 2 else modelo_key

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            params = {
                "select": "marca,modelo,black,blue,red,tot_terex1",
                "modelo": f"eq.{modelo}",
                "limit": "1",
            }
            if marca:
                params["marca"] = f"eq.{marca}"
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/inventario_modelos",
                headers=SUPA_HEADERS,
                params=params,
            )
            rows = resp.json() if resp.status_code == 200 else []
    except Exception as e:
        logger.error(f"stock lookup error: {e}")
        rows = []

    if not rows:
        await send_whatsapp_message(from_number, f"No encontramos stock de *{modelo}*.")
        return

    r = rows[0]
    total = r.get("tot_terex1", 0) or 0
    parts_msg = [f"📱 *{r.get('marca','')} {r.get('modelo','')}*",
                 f"Stock total: *{total}* piezas"]

    # Mention colors that have a barcode configured (stock exists in inventario1)
    color_hints = []
    if r.get("black"):
        color_hints.append("Negro")
    if r.get("blue"):
        color_hints.append("Azul")
    if r.get("red"):
        color_hints.append("Rojo")
    if color_hints:
        parts_msg.append("Colores: " + ", ".join(color_hints))

    await send_whatsapp_message(from_number, "\n".join(parts_msg))


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

                        if msg_type == "text":
                            text_body = message.get("text", {}).get("body", "")
                            logger.info(f"From {from_number}: {text_body}")
                            await process_text_message(from_number, text_body)

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


@app.get("/")
async def root():
    return {"status": "Fundastock WhatsApp Bot Running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
