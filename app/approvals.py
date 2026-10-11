import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass


APPROVAL_TTL_SECONDS = 300


@dataclass(frozen=True)
class PendingApproval:
    approval_id: str
    thread_id: str
    chat_id: int
    user_id: int
    payload: dict
    expires_at: float


class ApprovalError(ValueError):
    pass


class ApprovalStore:
    """Durable, single-use Telegram approvals backed by SQLite."""

    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mutation_approvals (
                    approval_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
                """
            )

    def create(
        self,
        *,
        thread_id: str,
        chat_id: int,
        user_id: int,
        payload: dict,
    ) -> PendingApproval:
        approval = PendingApproval(
            approval_id=secrets.token_hex(12),
            thread_id=thread_id,
            chat_id=chat_id,
            user_id=user_id,
            payload=payload,
            expires_at=time.time() + APPROVAL_TTL_SECONDS,
        )
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE mutation_approvals SET status = 'superseded' "
                "WHERE thread_id = ? AND status = 'pending'",
                (thread_id,),
            )
            self._conn.execute(
                "INSERT INTO mutation_approvals "
                "(approval_id, thread_id, chat_id, user_id, payload, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    approval.approval_id,
                    approval.thread_id,
                    approval.chat_id,
                    approval.user_id,
                    json.dumps(approval.payload),
                    approval.expires_at,
                ),
            )
        return approval

    def has_pending(self, thread_id: str) -> bool:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE mutation_approvals SET status = 'expired' "
                "WHERE status = 'pending' AND expires_at < ?",
                (time.time(),),
            )
            row = self._conn.execute(
                "SELECT 1 FROM mutation_approvals "
                "WHERE thread_id = ? AND status = 'pending' LIMIT 1",
                (thread_id,),
            ).fetchone()
        return row is not None

    def claim(
        self,
        approval_id: str,
        *,
        chat_id: int,
        user_id: int,
        decision: str,
    ) -> PendingApproval:
        if decision not in {"approved", "rejected"}:
            raise ApprovalError("Invalid approval decision.")

        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT thread_id, chat_id, user_id, payload, expires_at, status "
                "FROM mutation_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                raise ApprovalError("This approval request is no longer available.")

            thread_id, expected_chat, expected_user, payload, expires_at, status = row
            if status != "pending":
                raise ApprovalError("This approval request has already been handled.")
            if expected_chat != chat_id or expected_user != user_id:
                raise ApprovalError("Only the original requester can approve this action.")
            if expires_at < time.time():
                self._conn.execute(
                    "UPDATE mutation_approvals SET status = 'expired' WHERE approval_id = ?",
                    (approval_id,),
                )
                raise ApprovalError("This approval request has expired.")

            updated = self._conn.execute(
                "UPDATE mutation_approvals SET status = ? "
                "WHERE approval_id = ? AND status = 'pending'",
                (decision, approval_id),
            )
            if updated.rowcount != 1:
                raise ApprovalError("This approval request has already been handled.")

        return PendingApproval(
            approval_id=approval_id,
            thread_id=thread_id,
            chat_id=expected_chat,
            user_id=expected_user,
            payload=json.loads(payload),
            expires_at=expires_at,
        )
