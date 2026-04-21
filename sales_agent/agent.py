"""Sales agent: Claude API call with JSON parsing, retry, and tool execution loop."""

import json
import logging
import os
import re

import httpx

from main import ANTHROPIC_API_KEY, send_whatsapp_message
from sales_agent.prompts import SALES_AGENT_SYSTEM
from sales_agent.state import (
    load_conversation, update_conversation, log_turn, load_history,
)
from sales_agent.tools import dispatch_tool

logger = logging.getLogger(__name__)

ANTHROPIC_SALES_MODEL = os.getenv("ANTHROPIC_SALES_MODEL", "claude-sonnet-4-6")

# Maximum tool-call rounds per single user message (prevent infinite loops)
MAX_TOOL_ROUNDS = 3


def _build_messages(history: list[dict], user_text: str, conversation_state: dict,
                    tool_context: str | None = None) -> list[dict]:
    """Build the messages array for the Claude API call."""
    messages = []

    # History turns
    for turn in history:
        role = turn.get("role")
        content = turn.get("content") or ""
        if role == "user":
            messages.append({"role": "user", "content": content})
        elif role == "assistant":
            messages.append({"role": "assistant", "content": content})
        elif role == "tool" and turn.get("tool_result"):
            # Inject tool results as assistant context
            messages.append({
                "role": "assistant",
                "content": f"[Tool {turn.get('tool_name')} result: {json.dumps(turn['tool_result'], ensure_ascii=False)[:2000]}]",
            })

    # Current user message
    user_content = user_text
    if tool_context:
        user_content = f"{user_text}\n\n[Contexto del sistema: {tool_context}]"

    # Add state context
    stage = conversation_state.get("stage", "greeting")
    lead_type = conversation_state.get("lead_type", "unknown")
    captured = conversation_state.get("captured_data") or {}
    ad_headline = conversation_state.get("ad_headline", "")
    ad_body = conversation_state.get("ad_body", "")

    state_note = (
        f"[Estado actual — stage: {stage}, lead_type: {lead_type}, "
        f"captured_data: {json.dumps(captured, ensure_ascii=False)[:1000]}"
    )
    if ad_headline:
        state_note += f", ad_headline: {ad_headline}"
    if ad_body:
        state_note += f", ad_body: {ad_body}"
    state_note += "]"

    user_content += f"\n\n{state_note}"

    messages.append({"role": "user", "content": user_content})

    return messages


def _parse_agent_json(raw_text: str) -> dict | None:
    """Try to parse the agent's JSON response."""
    raw_text = raw_text.strip()
    # Remove markdown code fences if present
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return None


async def _call_claude(messages: list[dict]) -> str | None:
    """Make a single Claude API call, return raw text or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=45) as client:
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
                    "system": SALES_AGENT_SYSTEM,
                    "messages": messages,
                },
            )
            if resp.status_code >= 400:
                logger.error(f"Sales agent Claude error: {resp.status_code} {resp.text[:400]}")
                return None
            data = resp.json()
            return (data.get("content", [{}])[0] or {}).get("text", "").strip()
    except Exception as e:
        logger.error(f"Sales agent Claude call error: {e}")
        return None


async def run_sales_agent(phone_number: str, user_text: str,
                          conversation_state: dict, image_url: str | None = None) -> dict:
    """
    Run the sales agent for one user message. Handles tool calls in a loop.
    Returns the final parsed agent response dict.
    """
    history = await load_history(phone_number, limit=20)

    # Log user turn
    await log_turn(phone_number, "user", content=user_text,
                   stage_at_turn=conversation_state.get("stage"))

    # If an image was sent, add context
    tool_context = None
    if image_url:
        tool_context = f"El usuario envió una imagen: {image_url}"

    messages = _build_messages(history, user_text, conversation_state, tool_context)

    # Agent loop: call Claude → execute tool if needed → re-call with result
    for round_num in range(MAX_TOOL_ROUNDS + 1):
        raw_text = await _call_claude(messages)

        if raw_text is None:
            # API failure — fallback
            return await _handle_failure(phone_number, conversation_state)

        # Log raw response
        await log_turn(phone_number, "assistant", content=raw_text,
                       stage_at_turn=conversation_state.get("stage"))

        parsed = _parse_agent_json(raw_text)

        if parsed is None:
            # Retry once with correction prompt
            if round_num == 0:
                messages.append({"role": "assistant", "content": raw_text})
                messages.append({
                    "role": "user",
                    "content": "Tu respuesta anterior no fue JSON válido. Responde SOLO el JSON estricto.",
                })
                continue
            else:
                return await _handle_failure(phone_number, conversation_state)

        # Update conversation state
        new_stage = parsed.get("stage", conversation_state.get("stage"))
        new_lead_type = parsed.get("lead_type", conversation_state.get("lead_type"))
        captured_update = parsed.get("captured_data_update") or {}

        current_captured = conversation_state.get("captured_data") or {}
        current_captured.update(captured_update)

        state_updates = {
            "stage": new_stage,
            "lead_type": new_lead_type,
            "captured_data": current_captured,
            "last_message_at": __import__("datetime").datetime.utcnow().isoformat(),
        }
        await update_conversation(phone_number, state_updates)

        # Update local state for next iteration
        conversation_state["stage"] = new_stage
        conversation_state["lead_type"] = new_lead_type
        conversation_state["captured_data"] = current_captured

        # Send message to user (if any)
        agent_message = (parsed.get("message") or "").strip()
        if agent_message:
            await send_whatsapp_message(phone_number, agent_message)

        # Execute tool if requested
        tool_name = parsed.get("tool")
        tool_args = parsed.get("tool_args") or {}

        if tool_name and round_num < MAX_TOOL_ROUNDS:
            tool_result = await dispatch_tool(tool_name, phone_number, tool_args, conversation_state)

            # If tool was create_order, inject the order_id into captured_data
            if tool_name == "create_order" and tool_result.get("ok"):
                current_captured["last_order_id"] = tool_result["order_id"]
                current_captured["last_expected_amount"] = tool_result["expected_amount"]
                await update_conversation(phone_number, {"captured_data": current_captured})

            # Feed tool result back to Claude for next response
            messages.append({"role": "assistant", "content": raw_text})
            messages.append({
                "role": "user",
                "content": f"[Resultado de herramienta {tool_name}: {json.dumps(tool_result, ensure_ascii=False)[:3000]}]",
            })
            continue  # next round

        # No tool call — we're done
        return parsed

    # Exhausted rounds
    return parsed if parsed else await _handle_failure(phone_number, conversation_state)


async def _handle_failure(phone_number: str, conversation_state: dict) -> dict:
    """Handle agent failure: send generic message, escalate."""
    fallback_msg = "Déjame consultar con el equipo, te respondo en unos minutos."
    await send_whatsapp_message(phone_number, fallback_msg)

    from sales_agent.tools import tool_escalate_to_human
    await tool_escalate_to_human(phone_number, {"reason": "Agent JSON parse failure or API error"}, conversation_state)

    return {
        "message": fallback_msg,
        "tool": "escalate_to_human",
        "tool_args": {"reason": "JSON parse failure"},
        "stage": "escalated",
        "lead_type": conversation_state.get("lead_type", "unknown"),
        "captured_data_update": {},
        "confidence": 0.0,
    }
