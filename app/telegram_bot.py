import asyncio
import logging
import os
import sqlite3

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.approvals import ApprovalError, ApprovalStore
from app.graph import build_agent
from app.observability import make_callbacks, setup_logging

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4096
AGENT_TIMEOUT = 120  # seconds

# asyncio.wait_for() cancels the awaiter, not the worker thread created by
# asyncio.to_thread(). Keep timed-out invocations tracked so a later message
# cannot resume the same LangGraph thread while its previous invocation is
# still writing checkpoint messages.
_active_invocations: dict[str, asyncio.Task] = {}

INVALID_CHAT_HISTORY_MARKER = "/errors/INVALID_CHAT_HISTORY"
APPROVAL_CALLBACK_PATTERN = r"^mutation:(approve|reject):[0-9a-f]{24}$"


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


def _result_text(result: dict) -> str:
    content = result["messages"][-1].content
    if isinstance(content, list):
        content = " ".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        ) or "Agent did not produce a text response."
    return extract_answer(content)


def _interrupts(result: dict) -> tuple:
    return tuple(result.get("__interrupt__", ()))


def _approval_text(payload: dict) -> str:
    summary = payload.get("summary", "Kubernetes mutation")
    parameters = payload.get("parameters", {})
    details = "\n".join(f"• {key}: {value}" for key, value in parameters.items())
    return (
        "⚠️ Approval required\n\n"
        f"{summary}\n\n"
        f"{details}\n\n"
        "This request expires in 5 minutes."
    )


def invoke_with_history_recovery(agent, message: HumanMessage, config: dict, thread_id: str):
    """Invoke the agent, resetting only a thread whose saved tool history is incomplete."""
    try:
        return agent.invoke({"messages": [message]}, config=config)
    except ValueError as exc:
        if INVALID_CHAT_HISTORY_MARKER not in str(exc):
            raise

        checkpointer = getattr(agent, "checkpointer", None)
        if checkpointer is None or not hasattr(checkpointer, "delete_thread"):
            raise

        logger.warning(
            "Resetting invalid conversation history for thread_id=%s",
            thread_id,
        )
        checkpointer.delete_thread(thread_id)
        return agent.invoke({"messages": [message]}, config=config)


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    agent,
    allowed_chat_ids: frozenset[int],
    approval_store: ApprovalStore | None = None,
) -> None:
    chat_id = update.effective_chat.id
    if chat_id not in allowed_chat_ids:
        logger.warning("Rejected message from chat_id=%s", chat_id)
        return

    thread_id = str(chat_id)
    if approval_store is not None and approval_store.has_pending(thread_id):
        await update.message.reply_text(
            "⚠️ A mutation is awaiting approval. Use its Approve or Reject button first."
        )
        return

    active_invocation = _active_invocations.get(thread_id)
    if active_invocation is not None and not active_invocation.done():
        await update.message.reply_text(
            "⏳ The previous investigation is still finishing. Please try again shortly."
        )
        return
    _active_invocations.pop(thread_id, None)

    reply = await update.message.reply_text("🔍 Investigating...")

    callbacks, handler = make_callbacks()
    timed_out = False
    try:
        config = {"configurable": {"thread_id": thread_id}}
        config["callbacks"] = callbacks
        config["metadata"] = {
            "thread_id": str(chat_id),
            "langfuse_session_id": f"telegram:{chat_id}",
        }
        invoke_task = asyncio.create_task(
            asyncio.to_thread(
                lambda: invoke_with_history_recovery(
                    agent,
                    HumanMessage(content=update.message.text),
                    config,
                    thread_id,
                )
            )
        )
        _active_invocations[thread_id] = invoke_task
        result = await asyncio.wait_for(
            asyncio.shield(invoke_task),
            timeout=AGENT_TIMEOUT,
        )
        interrupts = _interrupts(result)
        if interrupts:
            if approval_store is None:
                raise RuntimeError("Mutation approval store is not configured")
            if len(interrupts) != 1:
                raise RuntimeError("Only one mutation can be approved at a time")
            payload = interrupts[0].value
            if not isinstance(payload, dict) or payload.get("kind") != "mutation_approval":
                raise RuntimeError("Agent produced an unsupported interrupt")

            approval = approval_store.create(
                thread_id=thread_id,
                chat_id=chat_id,
                user_id=update.effective_user.id,
                payload=payload,
            )
            keyboard = InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "✅ Approve",
                        callback_data=f"mutation:approve:{approval.approval_id}",
                    ),
                    InlineKeyboardButton(
                        "❌ Reject",
                        callback_data=f"mutation:reject:{approval.approval_id}",
                    ),
                ]]
            )
            answer = _approval_text(payload)
        else:
            answer = _result_text(result)
    except asyncio.TimeoutError:
        timed_out = True
        answer = f"Investigation timed out after {AGENT_TIMEOUT} seconds."
    except Exception as e:
        logger.exception("Agent error for chat_id=%s", chat_id)
        answer = f"Error: {e}"
    finally:
        if "invoke_task" in locals():
            if invoke_task.done():
                _active_invocations.pop(thread_id, None)
            else:
                def clear_finished_invocation(task: asyncio.Task) -> None:
                    # Retrieve any late exception so asyncio does not emit an
                    # unhandled-task warning after a timed-out request.
                    try:
                        task.exception()
                    except asyncio.CancelledError:
                        pass
                    if _active_invocations.get(thread_id) is task:
                        _active_invocations.pop(thread_id, None)

                invoke_task.add_done_callback(clear_finished_invocation)
        handler.emit_request_summary(update.message.text, timed_out=timed_out)

    if "keyboard" in locals():
        await reply.edit_text(answer, reply_markup=keyboard)
    else:
        await reply.edit_text(answer)


async def handle_approval(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    agent,
    allowed_chat_ids: frozenset[int],
    approval_store: ApprovalStore,
) -> None:
    query = update.callback_query

    chat_id = update.effective_chat.id
    if chat_id not in allowed_chat_ids:
        logger.warning("Rejected approval from chat_id=%s", chat_id)
        return

    try:
        _, raw_decision, approval_id = query.data.split(":", 2)
        if raw_decision not in {"approve", "reject"}:
            raise ApprovalError("Invalid approval decision.")
        decision = "approved" if raw_decision == "approve" else "rejected"
        approval = approval_store.claim(
            approval_id,
            chat_id=chat_id,
            user_id=update.effective_user.id,
            decision=decision,
        )
    except (ApprovalError, AttributeError, ValueError) as exc:
        await query.answer(str(exc), show_alert=True)
        return

    await query.answer()
    approved = decision == "approved"
    logger.info(
        "event=mutation_approval action=%s decision=%s approval_id=%s "
        "chat_id=%s user_id=%s",
        approval.payload.get("action", "unknown"),
        decision,
        approval.approval_id,
        chat_id,
        update.effective_user.id,
    )
    status = "Approved — executing…" if approved else "Rejected — cancelling…"
    await query.edit_message_text(f"{_approval_text(approval.payload)}\n\n{status}")

    callbacks, handler = make_callbacks()
    timed_out = False
    try:
        config = {
            "configurable": {"thread_id": approval.thread_id},
            "callbacks": callbacks,
            "metadata": {
                "thread_id": approval.thread_id,
                "langfuse_session_id": f"telegram:{chat_id}",
                "mutation_approval": decision,
            },
        }
        invoke_task = asyncio.create_task(
            asyncio.to_thread(
                lambda: agent.invoke(Command(resume=approved), config=config)
            )
        )
        _active_invocations[approval.thread_id] = invoke_task
        result = await asyncio.wait_for(
            asyncio.shield(invoke_task),
            timeout=AGENT_TIMEOUT,
        )
        if _interrupts(result):
            raise RuntimeError("A second mutation requires a new user request")
        answer = _result_text(result)
    except asyncio.TimeoutError:
        timed_out = True
        answer = f"Mutation handling timed out after {AGENT_TIMEOUT} seconds."
    except Exception as exc:
        logger.exception("Mutation approval error for chat_id=%s", chat_id)
        answer = f"Error: {exc}"
    finally:
        if "invoke_task" in locals():
            if invoke_task.done():
                _active_invocations.pop(approval.thread_id, None)
            else:
                def clear_finished_invocation(task: asyncio.Task) -> None:
                    try:
                        task.exception()
                    except asyncio.CancelledError:
                        pass
                    if _active_invocations.get(approval.thread_id) is task:
                        _active_invocations.pop(approval.thread_id, None)

                invoke_task.add_done_callback(clear_finished_invocation)
        handler.emit_request_summary(
            f"mutation approval: {approval.payload.get('action', 'unknown')}",
            timed_out=timed_out,
        )

    await query.edit_message_text(answer)


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
    approval_store = ApprovalStore(db_path)
    agent = build_agent(checkpointer=checkpointer)
    logger.info("Agent ready. Allowed chat IDs: %s", allowed_chat_ids)

    app = Application.builder().token(token).build()

    async def _handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_message(update, context, agent, allowed_chat_ids, approval_store)

    async def _approval_handler(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await handle_approval(update, context, agent, allowed_chat_ids, approval_store)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handler))
    app.add_handler(
        CallbackQueryHandler(_approval_handler, pattern=APPROVAL_CALLBACK_PATTERN)
    )
    logger.info("Starting long-polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
