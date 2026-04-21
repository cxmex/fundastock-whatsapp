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


# --- Admin Dashboard ---

ADMIN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Fundastock Admin</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, sans-serif; background: #0b141a; color: #e9edef; padding: 20px; }
  h1 { margin-bottom: 20px; }
  h2 { margin: 20px 0 10px; color: #00a884; }
  .card { background: #202c33; border-radius: 8px; padding: 16px; margin-bottom: 12px; }
  .card .label { color: #8696a0; font-size: 12px; }
  .card .value { font-size: 14px; margin-bottom: 6px; }
  .btn { background: #00a884; color: #fff; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; margin-right: 8px; font-size: 13px; }
  .btn.danger { background: #e74c3c; }
  .btn:hover { opacity: 0.9; }
  input { background: #2a3942; border: none; color: #e9edef; padding: 8px; border-radius: 4px; margin-right: 8px; }
  #key-bar { margin-bottom: 20px; }
  .status { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
  .status.pending { background: #f39c12; color: #000; }
  .status.claimed { background: #3498db; }
  .status.paid { background: #27ae60; }
  .status.escalated { background: #e74c3c; }
  #loading { color: #8696a0; }
</style>
</head>
<body>
<h1>Fundastock Admin Dashboard</h1>
<div id="key-bar">
  <input id="admin-key" type="password" placeholder="Admin API Key" style="width: 300px;" />
  <button class="btn" onclick="loadAll()">Load</button>
</div>
<div id="loading" style="display:none;">Loading...</div>

<h2>Pending Payment Verifications</h2>
<div id="verifications"></div>

<h2>Escalated Conversations</h2>
<div id="escalated"></div>

<script>
const getKey = () => document.getElementById('admin-key').value;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { 'X-Admin-Key': getKey(), 'Content-Type': 'application/json', ...(opts.headers || {}) },
  });
  return res.json();
}

async function loadAll() {
  document.getElementById('loading').style.display = 'block';
  try {
    const [verifs, convs] = await Promise.all([
      api('/admin/pending-verifications'),
      api('/admin/conversations?stage=escalated'),
    ]);
    renderVerifications(verifs);
    renderEscalated(convs);
  } catch(e) { alert('Error: ' + e.message); }
  document.getElementById('loading').style.display = 'none';
}

function renderVerifications(orders) {
  const el = document.getElementById('verifications');
  if (!orders.length) { el.innerHTML = '<div class="card">No pending verifications</div>'; return; }
  el.innerHTML = orders.map(o => `
    <div class="card">
      <div class="label">Order #${o.id} | ${o.phone_number} | ${o.order_type}</div>
      <div class="value">Expected: $${Number(o.expected_amount).toFixed(2)} | Method: ${o.payment_method || 'N/A'}</div>
      <div class="value">Claimed at: ${o.payment_claimed_at || 'N/A'}</div>
      <div class="value">Items: ${JSON.stringify(o.items)}</div>
      ${o.payment_comprobante_extracted ? '<div class="value">Extracted: ' + JSON.stringify(o.payment_comprobante_extracted) + '</div>' : ''}
      <div style="margin-top:8px;">
        <button class="btn" onclick="verifyPayment(${o.id}, true)">Verify ✅</button>
        <button class="btn danger" onclick="verifyPayment(${o.id}, false)">Reject ❌</button>
      </div>
    </div>
  `).join('');
}

function renderEscalated(convs) {
  const el = document.getElementById('escalated');
  if (!convs.length) { el.innerHTML = '<div class="card">No escalated conversations</div>'; return; }
  el.innerHTML = convs.map(c => `
    <div class="card">
      <div class="label">${c.phone_number} | ${c.lead_source || 'organic'} | ${c.lead_type}</div>
      <div class="value">Stage: <span class="status escalated">${c.stage}</span> | Takeover: ${c.human_takeover ? 'YES' : 'no'}</div>
      <div class="value">Last: ${c.last_message_at || c.updated_at}</div>
      <div class="value">Data: ${JSON.stringify(c.captured_data || {})}</div>
      <div style="margin-top:8px;">
        ${c.human_takeover ?
          '<button class="btn" onclick="releaseConv(\\'' + c.phone_number + '\\')">Release to Bot</button>' :
          '<button class="btn danger" onclick="takeoverConv(\\'' + c.phone_number + '\\')">Take Over</button>'}
      </div>
    </div>
  `).join('');
}

async function verifyPayment(orderId, verified) {
  const notes = prompt('Notes (optional):') || '';
  await api('/admin/verify-payment/' + orderId, {
    method: 'POST', body: JSON.stringify({ verified, notes }),
  });
  loadAll();
}

async function takeoverConv(phone) {
  await api('/admin/takeover/' + phone, { method: 'POST' });
  loadAll();
}

async function releaseConv(phone) {
  await api('/admin/release/' + phone, { method: 'POST' });
  loadAll();
}
</script>
</body>
</html>
"""


@router.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard():
    return ADMIN_DASHBOARD_HTML


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
