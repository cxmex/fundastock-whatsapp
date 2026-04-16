from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse
from datetime import datetime
import os
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

SUPA_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# Track processed message IDs to avoid duplicates
processed_messages = set()


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
            if resp.status_code >= 400:
                return False
            return True
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
            return resp.status_code < 400
    except Exception as e:
        logger.error(f"Exception sending image: {e}")
        return False


async def handle_cliente(from_number: str):
    """Send the customer a QR code with their available credit that can be scanned at the POS."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/qr_rewards",
                headers=SUPA_HEADERS,
                params={
                    "select": "reward_amount,status",
                    "phone_number": f"eq.{from_number}",
                    "status": "eq.linked",
                },
            )
            rows = resp.json() if resp.status_code == 200 else []
    except Exception as e:
        logger.error(f"Error querying rewards: {e}")
        rows = []

    total = round(sum(float(r.get("reward_amount", 0) or 0) for r in rows), 2)

    if total <= 0:
        await send_whatsapp_message(
            from_number,
            "Aun no tienes creditos disponibles.\n\nEscanea el QR de tus tickets para acumular 1% en cada compra."
        )
        return

    qr_img_url = f"{MAIN_APP_URL}/api/customer-qr/{from_number}"
    caption = (
        f"🎟️ Tu credito disponible: ${total:0.2f}\n\n"
        f"Muestra este codigo al cajero en tu proxima compra para canjearlo."
    )
    sent = await send_whatsapp_image(from_number, qr_img_url, caption)
    if not sent:
        await send_whatsapp_message(
            from_number,
            f"Tu credito: ${total:0.2f}\n\nAbre tu QR aqui: {qr_img_url}"
        )


async def process_text_message(from_number: str, text: str):
    """Route incoming text to the right handler."""
    txt = text.strip()
    upper = txt.upper()

    if upper.startswith("CANJEAR:"):
        token = txt.split(":", 1)[1]
        await handle_canjear(from_number, token)
        return

    if upper == "CLIENTE":
        await handle_cliente(from_number)
        return

    # Default echo
    reply = (
        f"Hola! Escribe *CLIENTE* para ver tu credito disponible.\n\n"
        f"Mensaje recibido: \"{txt}\""
    )
    await send_whatsapp_message(from_number, reply)


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
                        else:
                            logger.info(f"Ignoring message type: {msg_type}")

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
