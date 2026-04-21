"""Admin endpoints for payment verification, conversation management, and cron tasks."""

import logging
import os
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse

from main import SUPABASE_URL, SUPA_HEADERS, send_whatsapp_message
from sales_agent.state import update_conversation, load_conversation
from sales_agent.payments import send_telegram_alert

logger = logging.getLogger(__name__)

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

router = APIRouter()


def _check_admin(request: Request):
    """Verify admin API key from header."""
    key = request.headers.get("X-Admin-Key", "")
    if not ADMIN_API_KEY or key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")


# --- Conversation management ---

@router.get("/admin/conversations")
async def list_conversations(request: Request, stage: str = None):
    _check_admin(request)
    params = {"select": "*", "order": "updated_at.desc", "limit": "50"}
    if stage:
        params["stage"] = f"eq.{stage}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/whatsapp_conversations",
                headers=SUPA_HEADERS,
                params=params,
            )
            return resp.json() if resp.status_code == 200 else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/takeover/{phone_number}")
async def takeover(request: Request, phone_number: str):
    _check_admin(request)
    ok = await update_conversation(phone_number, {"human_takeover": True, "stage": "escalated"})
    if ok:
        return {"ok": True, "phone_number": phone_number, "human_takeover": True}
    raise HTTPException(status_code=500, detail="Failed to update conversation")


@router.post("/admin/release/{phone_number}")
async def release(request: Request, phone_number: str):
    _check_admin(request)
    ok = await update_conversation(phone_number, {"human_takeover": False})
    if ok:
        return {"ok": True, "phone_number": phone_number, "human_takeover": False}
    raise HTTPException(status_code=500, detail="Failed to update conversation")


# --- Payment verification ---

@router.get("/admin/pending-verifications")
async def pending_verifications(request: Request):
    _check_admin(request)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/sales_orders",
                headers=SUPA_HEADERS,
                params={
                    "select": "*",
                    "payment_status": "eq.payment_claimed",
                    "order": "payment_claimed_at.asc",
                    "limit": "50",
                },
            )
            return resp.json() if resp.status_code == 200 else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/verify-payment/{order_id}")
async def verify_payment(request: Request, order_id: int):
    _check_admin(request)
    body = await request.json()
    verified = body.get("verified", False)
    notes = body.get("notes", "")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Load order
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/sales_orders",
                headers=SUPA_HEADERS,
                params={"select": "*", "id": f"eq.{order_id}", "limit": "1"},
            )
            if resp.status_code != 200 or not resp.json():
                raise HTTPException(status_code=404, detail="Order not found")
            order = resp.json()[0]
            phone = order["phone_number"]

            if verified:
                updates = {
                    "payment_status": "paid",
                    "paid_at": datetime.utcnow().isoformat(),
                    "payment_verified_at": datetime.utcnow().isoformat(),
                    "payment_verified_by": "admin",
                    "notes": notes or order.get("notes"),
                }
                await client.patch(
                    f"{SUPABASE_URL}/rest/v1/sales_orders",
                    headers=SUPA_HEADERS,
                    params={"id": f"eq.{order_id}"},
                    json=updates,
                )
                await send_whatsapp_message(
                    phone,
                    f"¡Pago confirmado! ✅ Tu pedido #{order_id} sale hoy/mañana. "
                    f"Te avisamos con la guía de rastreo."
                )
                # Move conversation to post_sale
                await update_conversation(phone, {"stage": "post_sale"})
            else:
                await client.patch(
                    f"{SUPABASE_URL}/rest/v1/sales_orders",
                    headers=SUPA_HEADERS,
                    params={"id": f"eq.{order_id}"},
                    json={"payment_status": "pending", "notes": notes or order.get("notes")},
                )
                await send_whatsapp_message(
                    phone,
                    "Tu comprobante no pudo validarse contra el depósito real. "
                    "¿Puedes confirmar por cuál banco enviaste?"
                )

            return {"ok": True, "order_id": order_id, "verified": verified}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Admin Dashboard moved to sales_agent/dashboard/routes.py ---


# --- Cron / Periodic Tasks ---

@router.post("/tasks/expire-unpaid-orders")
async def expire_unpaid_orders(request: Request):
    """Mark orders pending > 24h as expired and notify customers."""
    _check_admin(request)
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/sales_orders",
                headers=SUPA_HEADERS,
                params={
                    "select": "id,phone_number",
                    "payment_status": "eq.pending",
                    "created_at": f"lt.{cutoff}",
                    "limit": "50",
                },
            )
            if resp.status_code != 200:
                return {"error": resp.text[:200]}

            orders = resp.json()
            expired_count = 0

            for order in orders:
                oid = order["id"]
                phone = order["phone_number"]

                await client.patch(
                    f"{SUPABASE_URL}/rest/v1/sales_orders",
                    headers=SUPA_HEADERS,
                    params={"id": f"eq.{oid}"},
                    json={"payment_status": "expired"},
                )
                await send_whatsapp_message(
                    phone,
                    f"Tu pedido #{oid} se canceló porque no recibimos el pago. "
                    f"Si aún lo quieres, escríbeme y lo generamos de nuevo."
                )
                expired_count += 1

            return {"ok": True, "expired": expired_count}

    except Exception as e:
        return {"error": str(e)}


@router.post("/tasks/escalate-stale-verifications")
async def escalate_stale_verifications(request: Request):
    """Alert admin about payment_claimed orders without verification > 4h."""
    _check_admin(request)
    cutoff = (datetime.utcnow() - timedelta(hours=4)).isoformat()

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/sales_orders",
                headers=SUPA_HEADERS,
                params={
                    "select": "id,phone_number,expected_amount,payment_claimed_at",
                    "payment_status": "eq.payment_claimed",
                    "payment_claimed_at": f"lt.{cutoff}",
                    "limit": "50",
                },
            )
            if resp.status_code != 200:
                return {"error": resp.text[:200]}

            stale = resp.json()
            for order in stale:
                await send_telegram_alert(
                    f"⏰ <b>Verificación pendiente >4h</b>\n"
                    f"Orden #{order['id']} | ${order['expected_amount']}\n"
                    f"Tel: {order['phone_number']}\n"
                    f"Reclamado: {order['payment_claimed_at']}"
                )

            return {"ok": True, "stale_count": len(stale)}

    except Exception as e:
        return {"error": str(e)}
