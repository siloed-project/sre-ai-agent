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
