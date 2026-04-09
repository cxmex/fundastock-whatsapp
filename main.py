from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse
import os
import logging
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Fundastock WhatsApp Bot")

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "maxi3")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

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
            logger.info(f"Sent to {to_number}: {message[:80]}")
            return resp.json()
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return None


async def process_text_message(from_number: str, text: str):
    """Process incoming text and reply."""
    txt = text.strip()

    reply = f"Hola! Recibimos tu mensaje: \"{txt}\"\n\nFundastock WhatsApp Bot activo."

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
