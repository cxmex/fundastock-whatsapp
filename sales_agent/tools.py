"""Tool implementations for the sales agent. Each tool is an async function."""

import json
import logging
import os
from datetime import datetime

import httpx

from main import (
    SUPABASE_URL, SUPABASE_KEY, SUPA_HEADERS, ANTHROPIC_API_KEY,
    send_whatsapp_message, send_whatsapp_document, send_whatsapp_image,
    claude_match, _fetch_inventario, _resolve_color_names, fetch_modelos,
)
from sales_agent.state import update_conversation, log_turn
from sales_agent.payments import (
    fingerprint_amount, send_payment_instructions as _send_payment_instructions,
    validate_comprobante as _validate_comprobante, send_telegram_alert,
)

logger = logging.getLogger(__name__)


async def tool_lookup_inventory(phone_number: str, args: dict, conversation_state: dict) -> dict:
    """Look up inventory for a model query — bypasses the 5-min cache for fresh data."""
    query = args.get("query", "")
    if not query:
        return {"error": "No query provided"}

    # Fetch fresh modelos from Supabase (bypass cache)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/inventario_modelos",
                headers={**SUPA_HEADERS, "Range": "0-999"},
                params={"select": "id,marca,modelo,tot_terex1", "limit": "1000"},
            )
            modelos = resp.json() if resp.status_code == 200 else []
    except Exception as e:
        logger.error(f"tool_lookup_inventory fresh fetch error: {e}")
        modelos = await fetch_modelos()  # fallback to cache

    if not modelos:
        return {"error": "Could not load catalog"}

    # Use Claude match
    result = await claude_match(query, modelos)
    action = result.get("action")

    if action == "match":
        modelo_key = result.get("modelo", "")
        parts = modelo_key.split(" | ", 1) if " | " in modelo_key else ["", modelo_key]
        marca = parts[0].strip()
        modelo = parts[1].strip() if len(parts) == 2 else modelo_key

        inv_rows = await _fetch_inventario(modelo)
        if not inv_rows:
            return {"match": modelo_key, "total_stock": 0, "estilos": []}

        # Aggregate by estilo
        by_estilo = {}
        total = 0
        for r in inv_rows:
            t1 = int(r.get("terex1") or 0)
            t2 = int(r.get("terex2") or 0)
            total += t1 + t2
            est = (r.get("estilo") or "").strip() or "Sin estilo"
            cur = by_estilo.setdefault(est, {"stock": 0, "colors": {}})
            cur["stock"] += t1 + t2
            cid = r.get("color_id")
            if cid:
                cur["colors"][cid] = cur["colors"].get(cid, 0) + t1 + t2

        # Resolve color names
        all_cids = set()
        for est_data in by_estilo.values():
            all_cids.update(est_data["colors"].keys())
        color_names = await _resolve_color_names(list(all_cids))

        estilos_out = []
        for est_name, est_data in sorted(by_estilo.items(), key=lambda x: -x[1]["stock"]):
            if est_data["stock"] <= 0:
                continue
            colors = [
                {"color": color_names.get(cid, f"Color {cid}"), "stock": qty}
                for cid, qty in sorted(est_data["colors"].items(), key=lambda x: -x[1])
                if qty > 0
            ]
            estilos_out.append({"estilo": est_name, "stock": est_data["stock"], "colors": colors})

        return {
            "match": modelo_key,
            "marca": marca,
            "modelo": modelo,
            "total_stock": total,
            "estilos": estilos_out[:10],
        }

    elif action == "ambiguous":
        return {"ambiguous": True, "candidates": result.get("candidates", [])}

    elif action == "no_match":
        return {"no_match": True, "message": result.get("message", "")}

    else:
        return {"chat": True, "message": result.get("message", "")}


async def tool_send_pricelist(phone_number: str, args: dict, conversation_state: dict) -> dict:
    """Send retail or wholesale price list PDF from Supabase Storage."""
    segment = args.get("segment", "retail")
    if segment not in ("retail", "wholesale"):
        segment = "retail"

    pdf_url = f"{SUPABASE_URL}/storage/v1/object/public/pricelists/{segment}.pdf"
    filename = f"lista_precios_{segment}.pdf"
    caption = "Lista de precios mayoreo" if segment == "wholesale" else "Lista de precios"

    sent = await send_whatsapp_document(phone_number, pdf_url, filename, caption)
    if sent:
        return {"ok": True, "segment": segment}
    else:
        return {"error": "Failed to send price list PDF"}


async def tool_send_payment_instructions(phone_number: str, args: dict, conversation_state: dict) -> dict:
    """Send SPEI or OXXO payment instructions."""
    order_id = args.get("order_id")
    method = args.get("method", "spei")
    if not order_id:
        return {"error": "No order_id provided"}
    return await _send_payment_instructions(phone_number, int(order_id), method)


async def tool_validate_comprobante(phone_number: str, args: dict, conversation_state: dict) -> dict:
    """Validate a payment comprobante image via Claude Vision."""
    order_id = args.get("order_id")
    image_url = args.get("image_url")
    if not order_id or not image_url:
        return {"error": "Missing order_id or image_url"}
    return await _validate_comprobante(phone_number, int(order_id), image_url)


async def tool_create_order(phone_number: str, args: dict, conversation_state: dict) -> dict:
    """Create a new sales order and compute fingerprinted expected_amount."""
    items = args.get("items", [])
    subtotal = float(args.get("subtotal", 0))
    shipping_cost = float(args.get("shipping_cost", 0))
    shipping_address = args.get("shipping_address")
    order_type = args.get("order_type", "retail")
    requires_factura = args.get("requires_factura", False)

    if not items:
        return {"error": "No items provided"}

    total = subtotal + shipping_cost
    expected_amount = await fingerprint_amount(total)

    # Get lead info from conversation state
    lead_source = conversation_state.get("lead_source")
    campaign_id = conversation_state.get("campaign_id")

    payload = {
        "phone_number": phone_number,
        "lead_source": lead_source,
        "campaign_id": campaign_id,
        "order_type": order_type,
        "items": items,
        "subtotal": subtotal,
        "shipping_cost": shipping_cost,
        "total": total,
        "expected_amount": expected_amount,
        "shipping_address": shipping_address,
        "payment_status": "pending",
    }

    # If factura data is in captured_data
    captured = conversation_state.get("captured_data") or {}
    if requires_factura or captured.get("rfc"):
        payload["rfc"] = captured.get("rfc")
        payload["razon_social"] = captured.get("razon_social")
        payload["uso_cfdi"] = captured.get("uso_cfdi")
        payload["email_factura"] = captured.get("email_factura")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SUPABASE_URL}/rest/v1/sales_orders",
                headers={**SUPA_HEADERS, "Prefer": "return=representation"},
                json=payload,
            )
            if resp.status_code in (200, 201):
                rows = resp.json()
                order_id = rows[0]["id"] if rows else None
                if order_id:
                    return {
                        "ok": True,
                        "order_id": order_id,
                        "expected_amount": expected_amount,
                        "total": total,
                    }
            logger.error(f"create_order HTTP {resp.status_code}: {resp.text[:300]}")
            return {"error": f"Supabase error {resp.status_code}"}
    except Exception as e:
        logger.error(f"create_order error: {e}")
        return {"error": str(e)}


async def tool_request_factura_info(phone_number: str, args: dict, conversation_state: dict) -> dict:
    """Ask the customer for factura (invoice) details."""
    msg = (
        "Para tu factura necesito:\n\n"
        "1. RFC\n"
        "2. Razón social\n"
        "3. Uso de CFDI (ej: G03 Gastos en general)\n"
        "4. Correo para recibir la factura\n\n"
        "Mándame los 4 datos aquí mismo."
    )
    await send_whatsapp_message(phone_number, msg)

    # Mark in conversation that we're awaiting factura info
    captured = conversation_state.get("captured_data") or {}
    captured["awaiting_factura_info"] = True
    await update_conversation(phone_number, {"captured_data": captured})

    return {"ok": True, "awaiting": "factura_info"}


async def tool_escalate_to_human(phone_number: str, args: dict, conversation_state: dict) -> dict:
    """Set human_takeover, send Telegram alert with summary."""
    reason = args.get("reason", "No reason provided")

    await update_conversation(phone_number, {
        "human_takeover": True,
        "escalated": True,
        "stage": "escalated",
    })

    # Build summary from last 5 turns
    from sales_agent.state import load_history
    history = await load_history(phone_number, limit=5)
    summary_lines = []
    for turn in history:
        role = turn.get("role", "?")
        content = (turn.get("content") or "")[:200]
        summary_lines.append(f"{role}: {content}")
    summary = "\n".join(summary_lines) or "(sin historial)"

    await send_telegram_alert(
        f"🚨 <b>Escalación</b>\n"
        f"Tel: {phone_number}\n"
        f"Razón: {reason}\n\n"
        f"Últimos mensajes:\n<pre>{summary[:2000]}</pre>"
    )

    return {"ok": True, "escalated": True, "reason": reason}


# --- Dispatcher ---

TOOL_MAP = {
    "lookup_inventory": tool_lookup_inventory,
    "send_pricelist": tool_send_pricelist,
    "send_payment_instructions": tool_send_payment_instructions,
    "validate_comprobante": tool_validate_comprobante,
    "create_order": tool_create_order,
    "request_factura_info": tool_request_factura_info,
    "escalate_to_human": tool_escalate_to_human,
}


async def dispatch_tool(tool_name: str, phone_number: str, args: dict, conversation_state: dict) -> dict:
    """Dispatch a tool call by name. Returns the tool result dict."""
    fn = TOOL_MAP.get(tool_name)
    if not fn:
        return {"error": f"Unknown tool: {tool_name}"}

    # Log tool call
    await log_turn(phone_number, "tool", tool_name=tool_name, tool_args=args,
                   stage_at_turn=conversation_state.get("stage"))

    result = await fn(phone_number, args, conversation_state)

    # Log tool result
    await log_turn(phone_number, "tool", tool_name=tool_name, tool_result=result,
                   stage_at_turn=conversation_state.get("stage"))

    return result
