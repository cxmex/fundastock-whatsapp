"""Conversation state management — load/save whatsapp_conversations + sales_conversation_turns."""

import json
import logging
from datetime import datetime

import httpx

from main import SUPABASE_URL, SUPA_HEADERS

logger = logging.getLogger(__name__)


async def load_conversation(phone_number: str) -> dict | None:
    """Load the whatsapp_conversations row for a phone number. Returns None if not found."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/whatsapp_conversations",
                headers=SUPA_HEADERS,
                params={
                    "select": "*",
                    "phone_number": f"eq.{phone_number}",
                    "limit": "1",
                },
            )
            if resp.status_code == 200:
                rows = resp.json()
                return rows[0] if rows else None
    except Exception as e:
        logger.error(f"load_conversation error: {e}")
    return None


async def upsert_conversation(phone_number: str, data: dict) -> bool:
    """Upsert a whatsapp_conversations row. `data` should contain the fields to set."""
    payload = {"phone_number": phone_number, **data, "updated_at": datetime.utcnow().isoformat()}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SUPABASE_URL}/rest/v1/whatsapp_conversations",
                headers={
                    **SUPA_HEADERS,
                    "Prefer": "resolution=merge-duplicates",
                },
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error(f"upsert_conversation HTTP {resp.status_code}: {resp.text[:300]}")
                return False
            return True
    except Exception as e:
        logger.error(f"upsert_conversation error: {e}")
        return False


async def update_conversation(phone_number: str, updates: dict) -> bool:
    """Patch specific fields on an existing conversation row."""
    updates["updated_at"] = datetime.utcnow().isoformat()
    updates["last_message_at"] = datetime.utcnow().isoformat()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.patch(
                f"{SUPABASE_URL}/rest/v1/whatsapp_conversations",
                headers=SUPA_HEADERS,
                params={"phone_number": f"eq.{phone_number}"},
                json=updates,
            )
            if resp.status_code >= 400:
                logger.error(f"update_conversation HTTP {resp.status_code}: {resp.text[:300]}")
                return False
            return True
    except Exception as e:
        logger.error(f"update_conversation error: {e}")
        return False


async def log_turn(phone_number: str, role: str, content: str = None,
                   tool_name: str = None, tool_args: dict = None,
                   tool_result: dict = None, stage_at_turn: str = None) -> bool:
    """Insert a row into sales_conversation_turns."""
    payload = {
        "phone_number": phone_number,
        "role": role,
        "content": (content or "")[:10000],
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_result": tool_result,
        "stage_at_turn": stage_at_turn,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SUPABASE_URL}/rest/v1/sales_conversation_turns",
                headers=SUPA_HEADERS,
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error(f"log_turn HTTP {resp.status_code}: {resp.text[:300]}")
                return False
            return True
    except Exception as e:
        logger.error(f"log_turn error: {e}")
        return False


async def load_history(phone_number: str, limit: int = 20) -> list[dict]:
    """Load last N turns from sales_conversation_turns, ordered ASC (oldest first)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/sales_conversation_turns",
                headers=SUPA_HEADERS,
                params={
                    "select": "role,content,tool_name,tool_args,tool_result,stage_at_turn,created_at",
                    "phone_number": f"eq.{phone_number}",
                    "order": "created_at.desc",
                    "limit": str(limit),
                },
            )
            if resp.status_code == 200:
                rows = resp.json()
                rows.reverse()  # oldest first
                return rows
    except Exception as e:
        logger.error(f"load_history error: {e}")
    return []
