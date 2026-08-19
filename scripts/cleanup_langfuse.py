"""
Delete LangFuse traces older than LANGFUSE_RETENTION_DAYS (default: 30).

Intended as a daily cron:
  0 2 * * * /opt/sre-agent/.venv/bin/python /opt/sre-agent/scripts/cleanup_langfuse.py

Requires LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_HOST in the environment
(or in /etc/sre-agent/env loaded by the cron entry).
"""

import os
from datetime import datetime, timedelta, timezone

from langfuse import Langfuse  # type: ignore[import]

_RETENTION_DAYS = int(os.environ.get("LANGFUSE_RETENTION_DAYS", "30"))


def main() -> None:
    client = Langfuse()
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=_RETENTION_DAYS)
    deleted = 0
    page = 1

    while True:
        traces = client.fetch_traces(
            to_timestamp=cutoff,
            page=page,
            limit=100,
        )
        if not traces.data:
            break
        for trace in traces.data:
            client.delete_trace(trace.id)
            deleted += 1
        if len(traces.data) < 100:
            break
        page += 1

    print(f"Deleted {deleted} trace(s) older than {_RETENTION_DAYS} days.")


if __name__ == "__main__":
    main()
