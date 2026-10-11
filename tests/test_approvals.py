import time

import pytest

from app.approvals import ApprovalError, ApprovalStore


def test_approval_is_single_use_and_bound_to_requester(tmp_path):
    store = ApprovalStore(str(tmp_path / "approvals.db"))
    approval = store.create(
        thread_id="123",
        chat_id=123,
        user_id=456,
        payload={"action": "delete_pod"},
    )
    assert store.has_pending("123") is True

    with pytest.raises(ApprovalError, match="original requester"):
        store.claim(
            approval.approval_id,
            chat_id=123,
            user_id=999,
            decision="approved",
        )

    claimed = store.claim(
        approval.approval_id,
        chat_id=123,
        user_id=456,
        decision="approved",
    )
    assert claimed.payload == {"action": "delete_pod"}
    assert store.has_pending("123") is False

    with pytest.raises(ApprovalError, match="already been handled"):
        store.claim(
            approval.approval_id,
            chat_id=123,
            user_id=456,
            decision="approved",
        )


def test_expired_approval_cannot_be_claimed(tmp_path):
    store = ApprovalStore(str(tmp_path / "approvals.db"))
    approval = store.create(
        thread_id="123",
        chat_id=123,
        user_id=456,
        payload={"action": "delete_pod"},
    )
    store._conn.execute(
        "UPDATE mutation_approvals SET expires_at = ? WHERE approval_id = ?",
        (time.time() - 1, approval.approval_id),
    )
    store._conn.commit()

    with pytest.raises(ApprovalError, match="expired"):
        store.claim(
            approval.approval_id,
            chat_id=123,
            user_id=456,
            decision="approved",
        )
