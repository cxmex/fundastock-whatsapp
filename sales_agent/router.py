"""Top-level router: decides whether a message goes to the sales agent or existing flows."""

import logging

from main import send_whatsapp_message, log_message, SUPABASE_URL, SUPA_HEADERS
from sales_agent.state import load_conversation, upsert_conversation, log_turn
from sales_agent.agent import run_sales_agent

import httpx

logger = logging.getLogger(__name__)

# Stages that mean the sales agent is actively handling this conversation
ACTIVE_SALES_STAGES = {"greeting", "qualifying", "product_selection", "closing", "post_sale"}


async def route_message(from_number: str, text: str, referral: dict | None = None,
                        image_url: str | None = None) -> bool:
    """
    Decide if this message should be handled by the sales agent.
    Returns True if handled, False if the caller should fall through to existing flows.
    """
    conv = await load_conversation(from_number)

    # --- Human takeover: log only, do not respond ---
    if conv and conv.get("human_takeover"):
        await log_message("in", from_number, message_type="text", text_body=text, command="HUMAN_TAKEOVER")
        await log_turn(from_number, "user", content=text, stage_at_turn="escalated")
        logger.info(f"Human takeover active for {from_number}, not responding")
        return True  # handled (silently)

    # --- Active sales conversation ---
    if conv:
        stage = conv.get("stage", "")

        if stage in ACTIVE_SALES_STAGES:
            await log_message("in", from_number, message_type="text", text_body=text, command="SALES_AGENT")
            await run_sales_agent(from_number, text, conv, image_url=image_url)
            return True

        if stage == "escalated":
            await log_message("in", from_number, message_type="text", text_body=text, command="ESCALATED")
            await log_turn(from_number, "user", content=text, stage_at_turn="escalated")
            return True  # log only, don't respond

        if stage == "completed":
            # Check if this looks like a new purchase intent — restart conversation
            upper = text.upper()
            purchase_signals = ["QUIERO", "NECESITO", "FUNDA", "PRECIO", "MAYOREO", "COMPRAR",
                                "CUANTO", "TIENEN", "HAY", "PEDIDO"]
            if any(kw in upper for kw in purchase_signals):
                # Reset conversation for new purchase cycle
                await upsert_conversation(from_number, {
                    "stage": "greeting",
                    "lead_type": conv.get("lead_type", "unknown"),
                    "captured_data": {},
                    "escalated": False,
                    "human_takeover": False,
                })
                conv["stage"] = "greeting"
                conv["captured_data"] = {}
                await log_message("in", from_number, message_type="text", text_body=text, command="SALES_AGENT")
                await run_sales_agent(from_number, text, conv)
                return True
            else:
                # Completed conversation, no purchase intent — fall through to existing flows
                return False

    # --- New referral from ad ---
    if referral:
        source_type = (referral.get("source_type") or "").lower()
        lead_source = "fb_ad"
        if "tiktok" in source_type:
            lead_source = "tiktok_ad"

        conv_data = {
            "lead_source": lead_source,
            "campaign_id": referral.get("source_id"),
            "ad_headline": referral.get("headline"),
            "ad_body": referral.get("body"),
            "stage": "greeting",
            "lead_type": "unknown",
            "captured_data": {},
            "escalated": False,
            "human_takeover": False,
        }
        await upsert_conversation(from_number, conv_data)
        await log_message("in", from_number, message_type="text", text_body=text,
                          command="SALES_AGENT_AD", extra=referral)

        await run_sales_agent(from_number, text, conv_data)
        return True

    # --- Detect sales/purchase intent from organic users ---
    upper = text.upper()
    SALES_KEYWORDS = [
        "MAYOREO", "PRECIO MAYOREO", "PRECIOS MAYOREO", "PARA REVENDER",
        "REVENDER", "TIENDITA", "VENDO POR CATALOGO", "PROVEEDOR",
        "QUIERO COMPRAR", "COMO COMPRO", "COMO LE HAGO PARA COMPRAR",
        "HACEN ENVIOS", "ENVIAN", "PRECIO DE", "CUANTO CUESTA",
        "CUANTO SALE", "ME INTERESA", "QUIERO PEDIR", "QUIERO ORDENAR",
        "LISTA DE PRECIOS", "CATALOGO DE PRECIOS",
    ]
    if any(kw in upper for kw in SALES_KEYWORDS):
        # Detect wholesale vs retail hint
        WHOLESALE_HINTS = ["MAYOREO", "REVENDER", "TIENDITA", "CATALOGO", "PROVEEDOR"]
        lead_hint = "wholesale" if any(h in upper for h in WHOLESALE_HINTS) else "unknown"

        conv_data = {
            "lead_source": "organic",
            "stage": "greeting",
            "lead_type": lead_hint,
            "captured_data": {},
            "escalated": False,
            "human_takeover": False,
        }
        await upsert_conversation(from_number, conv_data)
        await log_message("in", from_number, message_type="text", text_body=text,
                          command="SALES_AGENT_ORGANIC")
        await run_sales_agent(from_number, text, conv_data)
        return True

    # --- No active conversation, no referral, no sales intent → fall through to existing flows ---
    return False


async def route_image(from_number: str, image_id: str, image_caption: str = "") -> bool:
    """
    Handle an incoming image message. Check if sender has a pending sales order
    and route to comprobante validation. Returns True if handled.
    """
    conv = await load_conversation(from_number)

    # Human takeover — log only
    if conv and conv.get("human_takeover"):
        await log_turn(from_number, "user", content=f"[image: {image_id}] {image_caption}",
                       stage_at_turn="escalated")
        return True

    # Check for pending order
    pending_order = None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/sales_orders",
                headers=SUPA_HEADERS,
                params={
                    "select": "id,expected_amount,payment_status",
                    "phone_number": f"eq.{from_number}",
                    "payment_status": "eq.pending",
                    "order": "created_at.desc",
                    "limit": "1",
                },
            )
            if resp.status_code == 200:
                rows = resp.json()
                if rows:
                    pending_order = rows[0]
    except Exception as e:
        logger.error(f"route_image order check error: {e}")

    if not pending_order and not (conv and conv.get("stage") in ACTIVE_SALES_STAGES):
        return False  # no sales context — let main.py handle it

    # Download image from WhatsApp
    image_url = await _download_whatsapp_media(image_id)
    if not image_url:
        if conv and conv.get("stage") in ACTIVE_SALES_STAGES:
            await send_whatsapp_message(from_number, "No pude descargar la imagen. ¿Puedes enviarla de nuevo?")
            return True
        return False

    # If pending order → validate comprobante
    if pending_order:
        from sales_agent.tools import tool_validate_comprobante
        result = await tool_validate_comprobante(
            from_number,
            {"order_id": pending_order["id"], "image_url": image_url},
            conv or {},
        )
        return True

    # Active sales conversation but no pending order — pass image context to agent
    if conv and conv.get("stage") in ACTIVE_SALES_STAGES:
        caption_text = image_caption or "[El usuario envió una imagen]"
        await run_sales_agent(from_number, caption_text, conv, image_url=image_url)
        return True

    return False


async def _download_whatsapp_media(media_id: str) -> str | None:
    """
    Download WhatsApp media: get the URL from Graph API, download the binary,
    upload to Supabase Storage, return public URL.
    """
    import os
    from datetime import datetime
    from main import WHATSAPP_TOKEN, SUPABASE_KEY

    if not WHATSAPP_TOKEN:
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1: Get media URL from WhatsApp
            resp = await client.get(
                f"https://graph.facebook.com/v21.0/{media_id}",
                headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            )
            if resp.status_code != 200:
                logger.error(f"Media URL fetch failed: {resp.status_code} {resp.text[:200]}")
                return None

            media_url = resp.json().get("url")
            if not media_url:
                return None

            # Step 2: Download the actual image
            img_resp = await client.get(
                media_url,
                headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            )
            if img_resp.status_code != 200:
                logger.error(f"Media download failed: {img_resp.status_code}")
                return None

            image_bytes = img_resp.content
            content_type = img_resp.headers.get("content-type", "image/jpeg")

            # Step 3: Upload to Supabase Storage
            ext = "jpg" if "jpeg" in content_type else content_type.split("/")[-1]
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"{media_id}_{ts}.{ext}"

            upload_resp = await client.post(
                f"{SUPABASE_URL}/storage/v1/object/comprobantes/{filename}",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": content_type,
                },
                content=image_bytes,
            )
            if upload_resp.status_code not in (200, 201):
                logger.error(f"Supabase upload failed: {upload_resp.status_code} {upload_resp.text[:200]}")
                return None

            public_url = f"{SUPABASE_URL}/storage/v1/object/public/comprobantes/{filename}"
            return public_url

    except Exception as e:
        logger.error(f"_download_whatsapp_media error: {e}")
        return None
