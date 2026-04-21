"""Supabase query helpers for the dashboard."""

import json
import logging
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

from main import SUPABASE_URL, SUPA_HEADERS

logger = logging.getLogger(__name__)


async def _get(path: str, params: dict) -> list:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=SUPA_HEADERS, params=params)
            if resp.status_code == 200:
                return resp.json()
            logger.error(f"query {path} HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"query {path} error: {e}")
    return []


async def _get_count(path: str, params: dict) -> int:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/{path}",
                headers={**SUPA_HEADERS, "Prefer": "count=exact"},
                params={**params, "select": "phone_number", "limit": "0"},
            )
            cr = resp.headers.get("content-range", "")
            if "/" in cr:
                return int(cr.split("/")[1])
    except Exception as e:
        logger.error(f"count {path} error: {e}")
    return 0


async def _post(path: str, payload: dict, headers_extra: dict = None) -> dict | list | None:
    try:
        h = {**SUPA_HEADERS}
        if headers_extra:
            h.update(headers_extra)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{SUPABASE_URL}/rest/v1/{path}", headers=h, json=payload)
            if resp.status_code < 400:
                return resp.json() if resp.text else {}
            logger.error(f"post {path} HTTP {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        logger.error(f"post {path} error: {e}")
    return None


async def _patch(path: str, params: dict, payload: dict) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.patch(
                f"{SUPABASE_URL}/rest/v1/{path}", headers=SUPA_HEADERS, params=params, json=payload
            )
            return resp.status_code < 400
    except Exception as e:
        logger.error(f"patch {path} error: {e}")
        return False


async def _delete(path: str, params: dict) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(
                f"{SUPABASE_URL}/rest/v1/{path}", headers=SUPA_HEADERS, params=params
            )
            return resp.status_code < 400
    except Exception as e:
        logger.error(f"delete {path} error: {e}")
        return False


# ── Conversations ──

async def list_conversations(
    date_from: str = None, date_to: str = None,
    lead_type: str = None, stage: str = None,
    campaign_id: str = None, payment_status: str = None,
    escalated_only: bool = False, takeover_only: bool = False,
    annotated_only: bool = False, search: str = None,
    offset: int = 0, limit: int = 50,
) -> tuple[list[dict], int]:
    """List conversations with filters. Returns (rows, total_count)."""
    params = {
        "select": "*",
        "order": "last_message_at.desc",
        "offset": str(offset),
        "limit": str(limit),
    }
    if date_from:
        params["created_at"] = f"gte.{date_from}"
    if date_to:
        params["created_at"] = params.get("created_at", "") and f"gte.{date_from}"
        params["last_message_at"] = f"lte.{date_to}T23:59:59"
    if lead_type and lead_type != "all":
        params["lead_type"] = f"eq.{lead_type}"
    if stage and stage != "all":
        params["stage"] = f"eq.{stage}"
    if campaign_id and campaign_id != "all":
        params["campaign_id"] = f"eq.{campaign_id}"
    if escalated_only:
        params["escalated"] = "eq.true"
    if takeover_only:
        params["human_takeover"] = "eq.true"
    if search:
        params["or"] = f"(captured_data.cs.{json.dumps({'_search': search})},phone_number.ilike.%{search}%)"

    rows = await _get("whatsapp_conversations", params)

    # Get total count
    count_params = {k: v for k, v in params.items() if k not in ("select", "order", "offset", "limit")}
    total = await _get_count("whatsapp_conversations", count_params)

    # If annotated_only filter, get annotated phones and filter
    if annotated_only:
        ann_phones = await _get("conversation_annotations", {"select": "phone_number", "limit": "1000"})
        annotated_set = {a["phone_number"] for a in ann_phones}
        rows = [r for r in rows if r["phone_number"] in annotated_set]

    # Attach order summary to each conversation
    if rows:
        phones = ",".join(r["phone_number"] for r in rows)
        orders = await _get("sales_orders", {
            "select": "id,phone_number,payment_status,total,order_type",
            "phone_number": f"in.({phones})",
            "limit": "200",
        })
        orders_by_phone = {}
        for o in orders:
            orders_by_phone.setdefault(o["phone_number"], []).append(o)
        for r in rows:
            r["_orders"] = orders_by_phone.get(r["phone_number"], [])

    return rows, total


async def get_distinct_campaigns() -> list[str]:
    rows = await _get("whatsapp_conversations", {
        "select": "campaign_id",
        "campaign_id": "not.is.null",
        "limit": "200",
    })
    return sorted(set(r["campaign_id"] for r in rows if r.get("campaign_id")))


# ── Transcript ──

async def get_transcript(phone_number: str, offset: int = 0, limit: int = 200) -> list[dict]:
    return await _get("sales_conversation_turns", {
        "select": "*",
        "phone_number": f"eq.{phone_number}",
        "order": "created_at.asc",
        "offset": str(offset),
        "limit": str(limit),
    })


async def get_conversation(phone_number: str) -> dict | None:
    rows = await _get("whatsapp_conversations", {
        "select": "*",
        "phone_number": f"eq.{phone_number}",
        "limit": "1",
    })
    return rows[0] if rows else None


async def get_orders_for_phone(phone_number: str) -> list[dict]:
    return await _get("sales_orders", {
        "select": "*",
        "phone_number": f"eq.{phone_number}",
        "order": "created_at.desc",
        "limit": "20",
    })


# ── Annotations ──

async def get_annotations(phone_number: str) -> list[dict]:
    return await _get("conversation_annotations", {
        "select": "*",
        "phone_number": f"eq.{phone_number}",
        "order": "created_at.desc",
        "limit": "50",
    })


async def create_annotation(data: dict) -> dict | None:
    return await _post("conversation_annotations", data, {"Prefer": "return=representation"})


async def get_recent_annotations(limit: int = 10) -> list[dict]:
    return await _get("conversation_annotations", {
        "select": "*",
        "order": "created_at.desc",
        "limit": str(limit),
    })


async def get_annotation_counts(days: int = 30) -> list[dict]:
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    rows = await _get("conversation_annotations", {
        "select": "category",
        "created_at": f"gte.{cutoff}",
        "limit": "5000",
    })
    counts = {}
    for r in rows:
        cat = r.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1
    return [{"category": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]


# ── Metrics ──

async def get_daily_metrics(days: int = 30) -> list[dict]:
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    return await _get("daily_campaign_metrics", {
        "select": "*",
        "date": f"gte.{cutoff}",
        "order": "date.desc",
        "limit": "1000",
    })


async def get_funnel_totals(days: int = 30) -> dict:
    """Calculate funnel totals directly from source tables for the last N days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    convos = await _get("whatsapp_conversations", {
        "select": "phone_number,lead_type,stage,escalated,human_takeover,created_at",
        "created_at": f"gte.{cutoff}",
        "limit": "5000",
    })

    orders = await _get("sales_orders", {
        "select": "id,phone_number,payment_status,total,order_type,created_at",
        "created_at": f"gte.{cutoff}",
        "limit": "2000",
    })

    qualified_stages = {"product_selection", "closing", "post_sale", "completed"}

    total_convos = len(convos)
    qualified = sum(1 for c in convos if c.get("stage") in qualified_stages)
    total_orders = len(orders)
    claimed = sum(1 for o in orders if o.get("payment_status") in ("payment_claimed", "paid"))
    paid = sum(1 for o in orders if o.get("payment_status") == "paid")
    revenue = sum(float(o.get("total") or 0) for o in orders if o.get("payment_status") == "paid")
    escalated = sum(1 for c in convos if c.get("escalated"))
    takeover = sum(1 for c in convos if c.get("human_takeover"))

    # Segment breakdown
    retail_convos = [c for c in convos if c.get("lead_type") == "retail"]
    wholesale_convos = [c for c in convos if c.get("lead_type") == "wholesale"]
    retail_orders = [o for o in orders if o.get("order_type") == "retail"]
    wholesale_orders = [o for o in orders if o.get("order_type") == "wholesale"]

    return {
        "total": {
            "conversations": total_convos,
            "qualified": qualified,
            "orders": total_orders,
            "claimed": claimed,
            "paid": paid,
            "revenue": revenue,
            "escalated": escalated,
            "takeover": takeover,
        },
        "retail": {
            "conversations": len(retail_convos),
            "qualified": sum(1 for c in retail_convos if c.get("stage") in qualified_stages),
            "orders": len(retail_orders),
            "paid": sum(1 for o in retail_orders if o.get("payment_status") == "paid"),
            "revenue": sum(float(o.get("total") or 0) for o in retail_orders if o.get("payment_status") == "paid"),
        },
        "wholesale": {
            "conversations": len(wholesale_convos),
            "qualified": sum(1 for c in wholesale_convos if c.get("stage") in qualified_stages),
            "orders": len(wholesale_orders),
            "paid": sum(1 for o in wholesale_orders if o.get("payment_status") == "paid"),
            "revenue": sum(float(o.get("total") or 0) for o in wholesale_orders if o.get("payment_status") == "paid"),
        },
    }


async def get_campaign_table(days: int = 30) -> list[dict]:
    """Campaign performance table with ROAS."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    cutoff_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    convos = await _get("whatsapp_conversations", {
        "select": "phone_number,campaign_id,ad_headline,lead_type,stage",
        "created_at": f"gte.{cutoff}",
        "campaign_id": "not.is.null",
        "limit": "5000",
    })

    orders = await _get("sales_orders", {
        "select": "campaign_id,payment_status,total",
        "created_at": f"gte.{cutoff}",
        "campaign_id": "not.is.null",
        "limit": "2000",
    })

    spend_rows = await _get("manual_ad_spend", {
        "select": "campaign_id,spend_mxn",
        "date": f"gte.{cutoff_date}",
        "limit": "1000",
    })

    qualified_stages = {"product_selection", "closing", "post_sale", "completed"}

    # Group by campaign
    campaigns = {}
    for c in convos:
        cid = c.get("campaign_id") or "unknown"
        row = campaigns.setdefault(cid, {
            "campaign_id": cid, "ad_headline": c.get("ad_headline", ""),
            "convos": 0, "qualified": 0, "orders": 0, "paid": 0,
            "revenue": 0, "spend": 0, "avg_order": 0, "roas": 0,
        })
        row["convos"] += 1
        if c.get("stage") in qualified_stages:
            row["qualified"] += 1
        if not row["ad_headline"] and c.get("ad_headline"):
            row["ad_headline"] = c["ad_headline"]

    for o in orders:
        cid = o.get("campaign_id") or "unknown"
        row = campaigns.setdefault(cid, {
            "campaign_id": cid, "ad_headline": "", "convos": 0, "qualified": 0,
            "orders": 0, "paid": 0, "revenue": 0, "spend": 0, "avg_order": 0, "roas": 0,
        })
        row["orders"] += 1
        if o.get("payment_status") == "paid":
            row["paid"] += 1
            row["revenue"] += float(o.get("total") or 0)

    spend_by_camp = {}
    for s in spend_rows:
        cid = s.get("campaign_id", "")
        spend_by_camp[cid] = spend_by_camp.get(cid, 0) + float(s.get("spend_mxn") or 0)

    result = []
    for cid, row in campaigns.items():
        row["spend"] = spend_by_camp.get(cid, 0)
        if row["paid"] > 0:
            row["avg_order"] = round(row["revenue"] / row["paid"], 2)
        if row["spend"] > 0:
            row["roas"] = round(row["revenue"] / row["spend"], 2)
        result.append(row)

    result.sort(key=lambda x: -x["convos"])
    return result


async def get_dropoff_histogram(days: int = 30) -> dict:
    """Count conversations that went silent at each stage (no message >24h)."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    stale_cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()

    convos = await _get("whatsapp_conversations", {
        "select": "stage,last_message_at",
        "created_at": f"gte.{cutoff}",
        "last_message_at": f"lt.{stale_cutoff}",
        "stage": "not.in.(completed,escalated)",
        "limit": "5000",
    })

    histogram = {}
    for c in convos:
        s = c.get("stage", "unknown")
        histogram[s] = histogram.get(s, 0) + 1

    return histogram


async def get_runaway_conversations(days: int = 30, limit: int = 20) -> list[dict]:
    """Conversations with most turns that didn't close."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    convos = await _get("whatsapp_conversations", {
        "select": "phone_number,lead_type,stage,last_message_at",
        "created_at": f"gte.{cutoff}",
        "stage": "not.in.(completed)",
        "order": "last_message_at.desc",
        "limit": "200",
    })

    if not convos:
        return []

    # Get turn counts for these phones
    phones = ",".join(c["phone_number"] for c in convos[:100])
    turns = await _get("sales_conversation_turns", {
        "select": "phone_number",
        "phone_number": f"in.({phones})",
        "limit": "10000",
    })
    turn_counts = {}
    for t in turns:
        p = t["phone_number"]
        turn_counts[p] = turn_counts.get(p, 0) + 1

    for c in convos:
        c["_turn_count"] = turn_counts.get(c["phone_number"], 0)

    convos.sort(key=lambda x: -x["_turn_count"])
    return convos[:limit]


async def get_daily_trend(days: int = 30) -> list[dict]:
    """Per-day counts of conversations, orders, paid for chart."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    cutoff_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    convos = await _get("whatsapp_conversations", {
        "select": "created_at",
        "created_at": f"gte.{cutoff}",
        "limit": "10000",
    })
    orders = await _get("sales_orders", {
        "select": "created_at,payment_status",
        "created_at": f"gte.{cutoff}",
        "limit": "5000",
    })

    by_day = {}
    for c in convos:
        d = (c.get("created_at") or "")[:10]
        if d:
            by_day.setdefault(d, {"date": d, "conversations": 0, "orders": 0, "paid": 0})
            by_day[d]["conversations"] += 1
    for o in orders:
        d = (o.get("created_at") or "")[:10]
        if d:
            by_day.setdefault(d, {"date": d, "conversations": 0, "orders": 0, "paid": 0})
            by_day[d]["orders"] += 1
            if o.get("payment_status") == "paid":
                by_day[d]["paid"] += 1

    return sorted(by_day.values(), key=lambda x: x["date"])


async def get_hourly_heatmap(days: int = 30) -> list[dict]:
    """Hour x day-of-week conversation start counts."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    convos = await _get("whatsapp_conversations", {
        "select": "created_at",
        "created_at": f"gte.{cutoff}",
        "limit": "10000",
    })

    grid = {}  # (dow, hour) -> count
    for c in convos:
        ts = c.get("created_at", "")
        if len(ts) >= 16:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                # Adjust to Mexico City (UTC-6 rough)
                dt = dt - timedelta(hours=6)
                key = (dt.weekday(), dt.hour)
                grid[key] = grid.get(key, 0) + 1
            except Exception:
                pass

    result = []
    for dow in range(7):
        for hour in range(24):
            result.append({"dow": dow, "hour": hour, "count": grid.get((dow, hour), 0)})
    return result


# ── Ad Spend ──

async def list_ad_spend(limit: int = 100) -> list[dict]:
    return await _get("manual_ad_spend", {
        "select": "*",
        "order": "date.desc",
        "limit": str(limit),
    })


async def upsert_ad_spend(date: str, campaign_id: str, spend_mxn: float, notes: str = "") -> dict | None:
    return await _post("manual_ad_spend", {
        "date": date, "campaign_id": campaign_id, "spend_mxn": spend_mxn, "notes": notes,
    }, {"Prefer": "resolution=merge-duplicates,return=representation"})


async def delete_ad_spend(row_id: int) -> bool:
    return await _delete("manual_ad_spend", {"id": f"eq.{row_id}"})


# ── Reports ──

async def list_reports(limit: int = 20) -> list[dict]:
    return await _get("daily_review_reports", {
        "select": "*",
        "order": "date.desc",
        "limit": str(limit),
    })


async def get_report(date: str) -> dict | None:
    rows = await _get("daily_review_reports", {
        "select": "*",
        "date": f"eq.{date}",
        "limit": "1",
    })
    return rows[0] if rows else None


async def save_report(date: str, conversations_reviewed: int, report_markdown: str,
                      source_phones: list[str]) -> dict | None:
    return await _post("daily_review_reports", {
        "date": date,
        "conversations_reviewed": conversations_reviewed,
        "report_markdown": report_markdown,
        "source_phone_numbers": source_phones,
    }, {"Prefer": "resolution=merge-duplicates,return=representation"})


# ── Search ──

async def search_turns(query: str, limit: int = 50) -> list[dict]:
    """Full-text search across turn content."""
    return await _get("sales_conversation_turns", {
        "select": "phone_number,role,content,created_at",
        "content": f"ilike.%{query}%",
        "order": "created_at.desc",
        "limit": str(limit),
    })
