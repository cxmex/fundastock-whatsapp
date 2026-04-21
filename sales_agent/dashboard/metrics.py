"""Funnel/cohort calculations and daily review report generation."""

import json
import logging
import os
import re
from datetime import datetime, timedelta

import httpx

from main import SUPABASE_URL, SUPA_HEADERS, ANTHROPIC_API_KEY
from sales_agent.payments import send_telegram_alert
from sales_agent.dashboard import queries

logger = logging.getLogger(__name__)

ANTHROPIC_SALES_MODEL = os.getenv("ANTHROPIC_SALES_MODEL", "claude-sonnet-4-6")
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "")

DAILY_REVIEW_SYSTEM = """Eres analista de ventas. Revisas conversaciones de WhatsApp del bot de Fundastock (fundas de celular, CDMX) que NO cerraron venta. Tu trabajo: identificar patrones de falla del bot y sugerir cambios específicos al prompt del sistema.

Para cada lote de conversaciones recibidas, produce un reporte en este formato:

## Resumen del día
- Total conversaciones revisadas: N
- Distribución por etapa de abandono: [breakdown]
- Nivel de severidad general: [low/medium/high]

## Top 5 patrones de falla
Para cada uno:
1. Descripción breve del patrón
2. Ejemplo textual (cita literal del usuario y la respuesta del bot)
3. Frecuencia aproximada (cuántas conversaciones muestran este patrón)
4. Sugerencia específica para el prompt del sistema

## Objeciones más frecuentes sin respuesta
Lista de 5-10 objeciones/preguntas que el bot no manejó bien.

## Observaciones generales
Notas cualitativas sobre tono, fluidez, exceso de formalidad, etc.

Sé directo, concreto, y específico. No generalices. Cita conversaciones literalmente cuando sea útil."""


async def refresh_daily_metrics(target_date: str = None):
    """Refresh daily_campaign_metrics for a given date (default: yesterday + today)."""
    dates = []
    if target_date:
        dates = [target_date]
    else:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        dates = [yesterday, today]

    for date_str in dates:
        next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

        # Fetch conversations created on this date
        convos = await queries._get("whatsapp_conversations", {
            "select": "phone_number,campaign_id,lead_source,lead_type,stage,escalated,human_takeover",
            "created_at": f"gte.{date_str}",
            "last_message_at": f"lt.{next_day}T23:59:59",
            "limit": "5000",
        })

        orders = await queries._get("sales_orders", {
            "select": "campaign_id,payment_status,total",
            "created_at": f"gte.{date_str}",
            "limit": "2000",
        })

        qualified_stages = {"product_selection", "closing", "post_sale", "completed"}

        # Group by campaign
        by_campaign = {}
        for c in convos:
            cid = c.get("campaign_id") or "_organic"
            ls = c.get("lead_source") or "organic"
            row = by_campaign.setdefault(cid, {
                "date": date_str, "campaign_id": cid, "lead_source": ls,
                "conversations_started": 0, "conversations_qualified": 0,
                "orders_created": 0, "payment_claimed": 0, "payment_paid": 0,
                "escalated": 0, "human_takeover": 0, "gross_revenue": 0,
            })
            row["conversations_started"] += 1
            if c.get("stage") in qualified_stages:
                row["conversations_qualified"] += 1
            if c.get("escalated"):
                row["escalated"] += 1
            if c.get("human_takeover"):
                row["human_takeover"] += 1

        for o in orders:
            cid = o.get("campaign_id") or "_organic"
            row = by_campaign.setdefault(cid, {
                "date": date_str, "campaign_id": cid, "lead_source": "unknown",
                "conversations_started": 0, "conversations_qualified": 0,
                "orders_created": 0, "payment_claimed": 0, "payment_paid": 0,
                "escalated": 0, "human_takeover": 0, "gross_revenue": 0,
            })
            row["orders_created"] += 1
            ps = o.get("payment_status", "")
            if ps in ("payment_claimed", "paid"):
                row["payment_claimed"] += 1
            if ps == "paid":
                row["payment_paid"] += 1
                row["gross_revenue"] += float(o.get("total") or 0)

        # Upsert each campaign row
        for cid, row in by_campaign.items():
            row["last_refreshed"] = datetime.utcnow().isoformat()
            await queries._post("daily_campaign_metrics", row,
                                {"Prefer": "resolution=merge-duplicates"})

    return {"ok": True, "dates": dates}


async def generate_daily_review(target_date: str = None) -> dict:
    """Generate a Claude-powered daily review of failed conversations."""
    if not target_date:
        target_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    next_day = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    # Get conversations from that day that didn't close
    convos = await queries._get("whatsapp_conversations", {
        "select": "phone_number,lead_type,stage,captured_data,lead_source,ad_headline",
        "created_at": f"gte.{target_date}",
        "last_message_at": f"lt.{next_day}T23:59:59",
        "stage": "not.in.(completed)",
        "limit": "100",
    })

    # Also include conversations that got messages yesterday but are stuck
    active_stuck = await queries._get("whatsapp_conversations", {
        "select": "phone_number,lead_type,stage,captured_data,lead_source,ad_headline",
        "last_message_at": f"gte.{target_date}",
        "last_message_at": f"lt.{next_day}T23:59:59",
        "stage": "not.in.(completed)",
        "limit": "100",
    })

    # Merge and deduplicate
    seen = set()
    all_convos = []
    for c in convos + active_stuck:
        if c["phone_number"] not in seen:
            seen.add(c["phone_number"])
            all_convos.append(c)

    if not all_convos:
        return {"ok": True, "conversations_reviewed": 0, "message": "No failed conversations to review"}

    # Check for existing paid orders (exclude those that actually paid)
    phones_str = ",".join(c["phone_number"] for c in all_convos)
    paid_orders = await queries._get("sales_orders", {
        "select": "phone_number",
        "phone_number": f"in.({phones_str})",
        "payment_status": "eq.paid",
        "limit": "500",
    })
    paid_phones = {o["phone_number"] for o in paid_orders}
    all_convos = [c for c in all_convos if c["phone_number"] not in paid_phones]

    if not all_convos:
        return {"ok": True, "conversations_reviewed": 0, "message": "All conversations had paid orders"}

    # Limit to 30 conversations to keep Claude input manageable
    review_convos = all_convos[:30]

    # Fetch transcripts for each
    transcript_blocks = []
    source_phones = []
    for conv in review_convos:
        phone = conv["phone_number"]
        source_phones.append(phone)
        turns = await queries.get_transcript(phone, limit=50)

        masked_phone = f"***{phone[-4:]}"
        block = f"\n### Conversación {masked_phone} (lead: {conv.get('lead_type','?')}, stage: {conv.get('stage','?')}, source: {conv.get('lead_source','?')})\n"
        if conv.get("ad_headline"):
            block += f"Ad: {conv['ad_headline']}\n"
        block += "\n"

        for t in turns:
            role = t.get("role", "?")
            content = (t.get("content") or "")[:500]
            tn = t.get("tool_name")
            if role == "tool" and tn:
                block += f"  [tool:{tn}] → {json.dumps(t.get('tool_result', {}), ensure_ascii=False)[:300]}\n"
            else:
                block += f"  {role}: {content}\n"

        transcript_blocks.append(block)

    full_input = f"Fecha: {target_date}\nTotal conversaciones sin cierre: {len(all_convos)}\n\n"
    full_input += "\n".join(transcript_blocks)

    # Call Claude
    if not ANTHROPIC_API_KEY:
        return {"error": "ANTHROPIC_API_KEY not set"}

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": ANTHROPIC_SALES_MODEL,
                    "max_tokens": 4096,
                    "system": DAILY_REVIEW_SYSTEM,
                    "messages": [{"role": "user", "content": full_input[:100000]}],
                },
            )
            if resp.status_code >= 400:
                logger.error(f"Daily review Claude error: {resp.status_code} {resp.text[:400]}")
                return {"error": f"Claude API {resp.status_code}"}

            data = resp.json()
            report_md = (data.get("content", [{}])[0] or {}).get("text", "").strip()

    except Exception as e:
        logger.error(f"Daily review error: {e}")
        return {"error": str(e)}

    # Save report
    await queries.save_report(target_date, len(review_convos), report_md, source_phones)

    # Send notification
    summary = report_md[:1000]
    await send_telegram_alert(
        f"📊 <b>Reporte diario {target_date}</b>\n"
        f"Conversaciones revisadas: {len(review_convos)}\n\n"
        f"{summary[:2000]}\n\n"
        f"Ver reporte completo: /admin/reports/{target_date}"
    )

    return {
        "ok": True,
        "date": target_date,
        "conversations_reviewed": len(review_convos),
        "report_length": len(report_md),
    }
