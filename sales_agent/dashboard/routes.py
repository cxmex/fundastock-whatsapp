"""Dashboard routes — all /admin/* endpoints for the analytics dashboard."""

import csv
import io
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse

from main import send_whatsapp_message, SUPABASE_URL, SUPA_HEADERS
from sales_agent.dashboard.auth import (
    ADMIN_PASSWORD, check_admin_auth, require_admin, create_session_cookie,
)
from sales_agent.dashboard import queries, templates
from sales_agent.dashboard.metrics import refresh_daily_metrics, generate_daily_review
from sales_agent.state import update_conversation

import httpx

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Auth ──

@router.get("/admin/login", response_class=HTMLResponse)
async def login_page():
    return templates.login_page()


@router.post("/admin/login")
async def login_submit(request: Request):
    form = await request.form()
    password = form.get("password", "")
    if not ADMIN_PASSWORD or password != ADMIN_PASSWORD:
        return HTMLResponse(templates.login_page(error="Invalid password"), status_code=401)
    response = RedirectResponse("/admin/dashboard", status_code=302)
    response.set_cookie(
        "admin_session", create_session_cookie(),
        max_age=7 * 24 * 3600, httponly=True, samesite="lax",
    )
    return response


@router.get("/admin/logout")
async def logout():
    response = RedirectResponse("/admin/login", status_code=302)
    response.delete_cookie("admin_session")
    return response


# ── Dashboard ──

@router.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    redirect = require_admin(request)
    if redirect:
        return redirect
    return templates.dashboard_page()


# ── API endpoints (JSON) ──

def _check(request: Request):
    if not check_admin_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return None


@router.get("/admin/api/conversations")
async def api_conversations(request: Request):
    err = _check(request)
    if err:
        return err
    p = request.query_params
    rows, total = await queries.list_conversations(
        date_from=p.get("date_from"),
        date_to=p.get("date_to"),
        lead_type=p.get("lead_type"),
        stage=p.get("stage"),
        campaign_id=p.get("campaign_id"),
        payment_status=p.get("payment_status"),
        escalated_only=p.get("escalated") == "1",
        takeover_only=p.get("takeover") == "1",
        annotated_only=p.get("annotated") == "1",
        search=p.get("search"),
        offset=int(p.get("offset", 0)),
        limit=int(p.get("limit", 50)),
    )
    return {"rows": rows, "total": total}


@router.get("/admin/api/conversation/{phone_number}")
async def api_conversation(request: Request, phone_number: str):
    err = _check(request)
    if err:
        return err
    return await queries.get_conversation(phone_number) or {}


@router.get("/admin/api/transcript/{phone_number}")
async def api_transcript(request: Request, phone_number: str):
    err = _check(request)
    if err:
        return err
    return await queries.get_transcript(phone_number)


@router.get("/admin/api/orders/{phone_number}")
async def api_orders(request: Request, phone_number: str):
    err = _check(request)
    if err:
        return err
    return await queries.get_orders_for_phone(phone_number)


@router.get("/admin/api/annotations/{phone_number}")
async def api_annotations(request: Request, phone_number: str):
    err = _check(request)
    if err:
        return err
    return await queries.get_annotations(phone_number)


@router.post("/admin/api/annotations")
async def api_create_annotation(request: Request):
    err = _check(request)
    if err:
        return err
    body = await request.json()
    result = await queries.create_annotation(body)
    return result or {"error": "Failed to create annotation"}


@router.get("/admin/api/campaigns")
async def api_campaigns(request: Request):
    err = _check(request)
    if err:
        return err
    return await queries.get_distinct_campaigns()


@router.post("/admin/api/update-stage/{phone_number}")
async def api_update_stage(request: Request, phone_number: str):
    err = _check(request)
    if err:
        return err
    body = await request.json()
    stage = body.get("stage", "completed")
    ok = await update_conversation(phone_number, {"stage": stage})
    return {"ok": ok}


@router.post("/admin/api/send-message/{phone_number}")
async def api_send_message(request: Request, phone_number: str):
    """Send a WhatsApp message as a human operator."""
    err = _check(request)
    if err:
        return err
    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        return {"error": "Empty message"}
    result = await send_whatsapp_message(phone_number, text)
    return {"ok": bool(result)}


# ── Metrics API ──

@router.get("/admin/api/funnel")
async def api_funnel(request: Request):
    err = _check(request)
    if err:
        return err
    return await queries.get_funnel_totals(days=30)


@router.get("/admin/api/campaign-table")
async def api_campaign_table(request: Request):
    err = _check(request)
    if err:
        return err
    return await queries.get_campaign_table(days=30)


@router.get("/admin/api/dropoff")
async def api_dropoff(request: Request):
    err = _check(request)
    if err:
        return err
    return await queries.get_dropoff_histogram(days=30)


@router.get("/admin/api/runaway")
async def api_runaway(request: Request):
    err = _check(request)
    if err:
        return err
    return await queries.get_runaway_conversations(days=30)


@router.get("/admin/api/daily-trend")
async def api_daily_trend(request: Request):
    err = _check(request)
    if err:
        return err
    return await queries.get_daily_trend(days=30)


@router.get("/admin/api/heatmap")
async def api_heatmap(request: Request):
    err = _check(request)
    if err:
        return err
    return await queries.get_hourly_heatmap(days=30)


@router.get("/admin/api/annotation-counts")
async def api_annotation_counts(request: Request):
    err = _check(request)
    if err:
        return err
    return await queries.get_annotation_counts(days=30)


@router.get("/admin/api/recent-annotations")
async def api_recent_annotations(request: Request):
    err = _check(request)
    if err:
        return err
    return await queries.get_recent_annotations(limit=10)


# ── Ad Spend ──

@router.get("/admin/api/ad-spend")
async def api_ad_spend(request: Request):
    err = _check(request)
    if err:
        return err
    return await queries.list_ad_spend()


@router.post("/admin/api/ad-spend")
async def api_create_ad_spend(request: Request):
    err = _check(request)
    if err:
        return err
    body = await request.json()
    result = await queries.upsert_ad_spend(
        body.get("date", ""),
        body.get("campaign_id", ""),
        float(body.get("spend_mxn", 0)),
        body.get("notes", ""),
    )
    return result or {"error": "Failed"}


@router.delete("/admin/api/ad-spend/{row_id}")
async def api_delete_ad_spend(request: Request, row_id: int):
    err = _check(request)
    if err:
        return err
    ok = await queries.delete_ad_spend(row_id)
    return {"ok": ok}


# ── Reports ──

@router.get("/admin/api/reports")
async def api_reports(request: Request):
    err = _check(request)
    if err:
        return err
    return await queries.list_reports()


@router.get("/admin/reports/{date}", response_class=HTMLResponse)
async def view_report(request: Request, date: str):
    redirect = require_admin(request)
    if redirect:
        return redirect
    report = await queries.get_report(date)
    if not report:
        return HTMLResponse("<h1>Report not found</h1>", status_code=404)
    # Redirect to dashboard with reports view
    return RedirectResponse(f"/admin/dashboard#reports", status_code=302)


# ── Cron tasks ──

@router.post("/admin/tasks/refresh-metrics")
async def task_refresh_metrics(request: Request):
    err = _check(request)
    if err:
        return err
    return await refresh_daily_metrics()


@router.post("/admin/tasks/daily-review")
async def task_daily_review(request: Request):
    err = _check(request)
    if err:
        return err
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    target_date = body.get("date")
    return await generate_daily_review(target_date)


# ── Exports ──

def _csv_response(filename: str, rows: list[dict]) -> StreamingResponse:
    if not rows:
        return StreamingResponse(iter(["No data"]), media_type="text/csv",
                                 headers={"Content-Disposition": f"attachment; filename={filename}"})
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    for row in rows:
        # Flatten JSON fields to strings
        clean = {}
        for k, v in row.items():
            if isinstance(v, (dict, list)):
                clean[k] = json.dumps(v, ensure_ascii=False)
            else:
                clean[k] = v
        writer.writerow(clean)
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={filename}"})


@router.get("/admin/export/conversations.csv")
async def export_conversations(request: Request):
    err = _check(request)
    if err:
        return err
    p = request.query_params
    rows, _ = await queries.list_conversations(
        date_from=p.get("from"), date_to=p.get("to"), limit=5000
    )
    # Remove internal _orders field
    for r in rows:
        r.pop("_orders", None)
    return _csv_response("conversations.csv", rows)


@router.get("/admin/export/turns.csv")
async def export_turns(request: Request):
    err = _check(request)
    if err:
        return err
    phone = request.query_params.get("phone_number", "")
    if not phone:
        return JSONResponse({"error": "phone_number required"}, status_code=400)
    rows = await queries.get_transcript(phone, limit=5000)
    return _csv_response(f"turns_{phone[-4:]}.csv", rows)


@router.get("/admin/export/annotations.csv")
async def export_annotations(request: Request):
    err = _check(request)
    if err:
        return err
    rows = await queries.get_recent_annotations(limit=5000)
    return _csv_response("annotations.csv", rows)


@router.get("/admin/export/orders.csv")
async def export_orders(request: Request):
    err = _check(request)
    if err:
        return err
    p = request.query_params
    params = {"select": "*", "order": "created_at.desc", "limit": "5000"}
    if p.get("from"):
        params["created_at"] = f"gte.{p['from']}"
    rows = await queries._get("sales_orders", params)
    return _csv_response("orders.csv", rows)
