import asyncio
import logging
import os

from langchain_core.messages import HumanMessage
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from app.graph import build_agent

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4096
AGENT_TIMEOUT = 120  # seconds


def parse_allowed_chat_ids(value: str) -> frozenset[int]:
    """Parse ALLOWED_CHAT_IDS env var. Raises ValueError on empty or non-numeric input."""
    if not value.strip():
        raise ValueError("ALLOWED_CHAT_IDS must not be empty")
    return frozenset(int(x.strip()) for x in value.split(","))


def extract_answer(content: str) -> str:
    """Extract Answer: section from agent output and truncate to Telegram's limit."""
    idx = content.find("Answer:")
    text = content[idx:] if idx != -1 else content
    if len(text) <= TELEGRAM_MAX_LENGTH:
        return text
    return text[: TELEGRAM_MAX_LENGTH - 3] + "..."


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    agent,
    allowed_chat_ids: frozenset[int],
) -> None:
    chat_id = update.effective_chat.id
    if chat_id not in allowed_chat_ids:
        logger.warning("Rejected message from chat_id=%s", chat_id)
        return

    reply = await update.message.reply_text("🔍 Investigating...")

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                agent.invoke, {"messages": [HumanMessage(content=update.message.text)]}
            ),
            timeout=AGENT_TIMEOUT,
        )
        content = result["messages"][-1].content
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict)
            ) or "Agent did not produce a text response."
        answer = extract_answer(content)
    except asyncio.TimeoutError:
        answer = f"Investigation timed out after {AGENT_TIMEOUT} seconds."
    except Exception as e:
        logger.exception("Agent error for chat_id=%s", chat_id)
        answer = f"Error: {e}"

    await reply.edit_text(answer)
