import asyncio
import logging
import os
import sqlite3

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from app.graph import build_agent
from app.observability import make_callbacks, setup_logging

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

    callbacks, handler = make_callbacks()
    timed_out = False
    try:
        config = {"configurable": {"thread_id": str(chat_id)}}
        result = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: agent.invoke(
                    {"messages": [HumanMessage(content=update.message.text)]},
                    config={**config, "callbacks": callbacks},
                )
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
        timed_out = True
        answer = f"Investigation timed out after {AGENT_TIMEOUT} seconds."
    except Exception as e:
        logger.exception("Agent error for chat_id=%s", chat_id)
        answer = f"Error: {e}"
    finally:
        handler.emit_request_summary(update.message.text, timed_out=timed_out)

    await reply.edit_text(answer)


def main() -> None:
    setup_logging()

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    allowed_chat_ids = parse_allowed_chat_ids(os.environ["ALLOWED_CHAT_IDS"])

    logger.info("Initialising SRE agent...")
    db_path = os.environ.get("MEMORY_DB_PATH", "/var/lib/sre-agent/memory.db")
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    agent = build_agent(checkpointer=checkpointer)
    logger.info("Agent ready. Allowed chat IDs: %s", allowed_chat_ids)

    app = Application.builder().token(token).build()

    async def _handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_message(update, context, agent, allowed_chat_ids)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handler))
    logger.info("Starting long-polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
