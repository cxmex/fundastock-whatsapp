"""Payment handling: fingerprint amounts, send instructions, validate comprobantes via Claude Vision."""

import json
import logging
import os
import random
import re
from datetime import datetime, timedelta

import httpx

from main import (
    SUPABASE_URL, SUPABASE_KEY, SUPA_HEADERS, ANTHROPIC_API_KEY,
    send_whatsapp_message, send_whatsapp_image,
)
from sales_agent.prompts import COMPROBANTE_VALIDATOR_SYSTEM
from sales_agent.state import update_conversation, log_turn

logger = logging.getLogger(__name__)

BUSINESS_CLABE = os.getenv("BUSINESS_CLABE", "")
BUSINESS_BANK_NAME = os.getenv("BUSINESS_BANK_NAME", "")
BUSINESS_BENEFICIARY_NAME = os.getenv("BUSINESS_BENEFICIARY_NAME", "")
BUSINESS_OXXO_CARD_NUMBER = os.getenv("BUSINESS_OXXO_CARD_NUMBER", "")
BUSINESS_OXXO_CARD_DISPLAY = os.getenv("BUSINESS_OXXO_CARD_DISPLAY", "")
BUSINESS_OXXO_CARD_HOLDER = os.getenv("BUSINESS_OXXO_CARD_HOLDER", "")
OXXO_MAX_AMOUNT = float(os.getenv("OXXO_MAX_AMOUNT", "8000"))

ANTHROPIC_SALES_MODEL = os.getenv("ANTHROPIC_SALES_MODEL", "claude-sonnet-4-6")

ADMIN_TELEGRAM_BOT_TOKEN = os.getenv("ADMIN_TELEGRAM_BOT_TOKEN", "")
ADMIN_TELEGRAM_CHAT_ID = os.getenv("ADMIN_TELEGRAM_CHAT_ID", "")


async def send_telegram_alert(text: str):
    """Send a Telegram message to the admin chat. Non-fatal on failure."""
    if not ADMIN_TELEGRAM_BOT_TOKEN or not ADMIN_TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured, skipping alert")
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{ADMIN_TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": ADMIN_TELEGRAM_CHAT_ID,
                    "text": text[:4000],
                    "parse_mode": "HTML",
                },
            )
    except Exception as e:
        logger.error(f"Telegram alert failed: {e}")


async def fingerprint_amount(base_total: float) -> float:
    """Add random cents 01-99, avoiding collisions with active unpaid orders in last 24h."""
    now = datetime.utcnow()
    cutoff = (now - timedelta(hours=24)).isoformat()

    # Fetch cents currently in use
    used_cents = set()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/sales_orders",
                headers=SUPA_HEADERS,
                params={
                    "select": "expected_amount",
                    "payment_status": "in.(pending,payment_claimed)",
                    "created_at": f"gte.{cutoff}",
                    "limit": "500",
                },
            )
            if resp.status_code == 200:
                for row in resp.json():
                    amt = float(row.get("expected_amount", 0))
                    cents = round((amt % 1) * 100)
                    if int(amt) == int(base_total):
                        used_cents.add(cents)
    except Exception as e:
        logger.error(f"fingerprint_amount collision check error: {e}")

    # Try to find unused cents
    for _ in range(99):
        cents = random.randint(1, 99)
        if cents not in used_cents:
            return round(int(base_total) + cents / 100, 2)

    # Fallback: bump to next 100 range
    return round(int(base_total) + 100 + random.randint(1, 99) / 100, 2)


async def _load_order(order_id: int) -> dict | None:
    """Fetch a single sales_orders row by id."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/sales_orders",
                headers=SUPA_HEADERS,
                params={"select": "*", "id": f"eq.{order_id}", "limit": "1"},
            )
            if resp.status_code == 200:
                rows = resp.json()
                return rows[0] if rows else None
    except Exception as e:
        logger.error(f"_load_order error: {e}")
    return None


async def _update_order(order_id: int, updates: dict) -> bool:
    """Patch fields on a sales_orders row."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.patch(
                f"{SUPABASE_URL}/rest/v1/sales_orders",
                headers=SUPA_HEADERS,
                params={"id": f"eq.{order_id}"},
                json=updates,
            )
            return resp.status_code < 400
    except Exception as e:
        logger.error(f"_update_order error: {e}")
        return False


async def send_payment_instructions(phone_number: str, order_id: int, method: str) -> dict:
    """Send SPEI or OXXO payment instructions with fingerprinted amount."""
    order = await _load_order(order_id)
    if not order:
        return {"error": "Order not found"}

    expected = float(order.get("expected_amount", 0))

    if method == "spei":
        msg = (
            f"✅ Pedido #{order_id} confirmado. Para pagar por SPEI:\n\n"
            f"💳 CLABE: {BUSINESS_CLABE}\n"
            f"🏦 Banco: {BUSINESS_BANK_NAME}\n"
            f"👤 A nombre de: {BUSINESS_BENEFICIARY_NAME}\n\n"
            f"📌 Monto EXACTO: ${expected:.2f}\n"
            f"(El centavaje nos ayuda a identificar tu pago más rápido)\n\n"
            f"Cuando pagues, mándame aquí mismo la foto del comprobante. "
            f"En cuanto validemos (usualmente <1hr en horario hábil), enviamos tu pedido."
        )
    elif method == "oxxo_tarjeta":
        msg = (
            f"✅ Pedido #{order_id} confirmado. Para pagar en OXXO:\n\n"
            f"💳 Número de tarjeta: {BUSINESS_OXXO_CARD_DISPLAY}\n"
            f"👤 A nombre de: {BUSINESS_OXXO_CARD_HOLDER}\n\n"
            f"📌 Monto EXACTO: ${expected:.2f}\n"
            f"(El centavaje nos ayuda a identificar tu pago más rápido)\n\n"
            f"En OXXO dile al cajero: \"Quiero hacer un depósito a tarjeta\". "
            f"Te cobran $11 extra de comisión.\n\n"
            f"Mándame aquí mismo la foto del ticket OXXO. "
            f"Enviamos tu pedido en cuanto validemos (<1hr en horario hábil)."
        )
    else:
        return {"error": f"Unknown payment method: {method}"}

    await send_whatsapp_message(phone_number, msg)

    await _update_order(order_id, {
        "payment_method": method,
        "payment_instructions_sent_at": datetime.utcnow().isoformat(),
    })

    return {"ok": True, "order_id": order_id, "method": method, "expected_amount": expected}


async def validate_comprobante(phone_number: str, order_id: int, image_url: str) -> dict:
    """Call Claude Vision to extract comprobante data and compare to expected amount."""
    order = await _load_order(order_id)
    if not order:
        return {"error": "Order not found"}

    expected = float(order.get("expected_amount", 0))

    # Call Claude Vision API
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": ANTHROPIC_SALES_MODEL,
                    "max_tokens": 1024,
                    "system": COMPROBANTE_VALIDATOR_SYSTEM,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {"type": "url", "url": image_url},
                            },
                            {
                                "type": "text",
                                "text": f"Analiza este comprobante de pago. El monto esperado es ${expected:.2f} MXN.",
                            },
                        ],
                    }],
                },
            )

            if resp.status_code >= 400:
                logger.error(f"Claude Vision error: {resp.status_code} {resp.text[:400]}")
                return {"error": "vision_api_error"}

            data = resp.json()
            raw_text = (data.get("content", [{}])[0] or {}).get("text", "").strip()

            # Parse JSON
            try:
                extracted = json.loads(raw_text)
            except json.JSONDecodeError:
                m = re.search(r"\{.*\}", raw_text, re.DOTALL)
                if m:
                    extracted = json.loads(m.group())
                else:
                    logger.error(f"Vision response not JSON: {raw_text[:300]}")
                    return {"error": "invalid_vision_json", "raw": raw_text[:300]}

    except Exception as e:
        logger.error(f"validate_comprobante error: {e}")
        return {"error": str(e)}

    # Log the vision result
    await log_turn(phone_number, "tool", tool_name="validate_comprobante",
                   tool_args={"order_id": order_id, "image_url": image_url},
                   tool_result=extracted)

    extracted_amount = extracted.get("amount")
    confidence = extracted.get("confidence", 0)
    suspicious = extracted.get("suspicious_signs", [])

    # Compare amounts
    if extracted_amount is not None and abs(float(extracted_amount) - expected) < 0.02 and confidence >= 0.7:
        # Amount matches — mark as payment_claimed (awaiting human verification)
        await _update_order(order_id, {
            "payment_status": "payment_claimed",
            "payment_claimed_at": datetime.utcnow().isoformat(),
            "payment_comprobante_url": image_url,
            "payment_comprobante_extracted": extracted,
        })
        await send_whatsapp_message(
            phone_number,
            "Recibido ✅ Tu pago se está validando, te aviso en cuanto esté confirmado "
            "(normalmente <1hr en horario hábil)."
        )
        await send_telegram_alert(
            f"🔔 <b>Orden #{order_id}</b> lista para verificar\n"
            f"Monto esperado: ${expected:.2f}\n"
            f"Monto extraído: ${extracted_amount}\n"
            f"Confianza: {confidence}\n"
            f"Tel: {phone_number}"
        )
        return {"ok": True, "status": "payment_claimed", "extracted": extracted}

    elif extracted_amount is not None and abs(float(extracted_amount) - expected) >= 0.02:
        # Amount mismatch
        await _update_order(order_id, {
            "payment_comprobante_url": image_url,
            "payment_comprobante_extracted": extracted,
        })
        await send_whatsapp_message(
            phone_number,
            f"Parece que el monto no coincide. Pagaste ${extracted_amount} pero el pedido era "
            f"${expected:.2f}. ¿Puedes revisarlo o mandar otro comprobante?"
        )
        return {"ok": False, "status": "amount_mismatch", "extracted": extracted}

    else:
        # Low confidence or suspicious — escalate
        await _update_order(order_id, {
            "payment_comprobante_url": image_url,
            "payment_comprobante_extracted": extracted,
        })
        await send_whatsapp_message(
            phone_number,
            "Recibido ✅ Te aviso en cuanto validemos contra el banco."
        )
        await send_telegram_alert(
            f"⚠️ <b>Orden #{order_id}</b> — comprobante requiere revisión manual\n"
            f"Confianza: {confidence}\n"
            f"Banderas: {suspicious}\n"
            f"Tel: {phone_number}"
        )
        return {"ok": False, "status": "needs_manual_review", "extracted": extracted}
