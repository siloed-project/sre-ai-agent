"""
Delete LangFuse traces older than LANGFUSE_RETENTION_DAYS (default: 30).

Intended as a daily cron:
  0 2 * * * /opt/sre-agent/.venv/bin/python /opt/sre-agent/scripts/cleanup_langfuse.py

Requires LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_HOST in the environment
(or in /etc/sre-agent/env loaded by the cron entry).
"""

import os
import base64
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

_RETENTION_DAYS = int(os.environ.get("LANGFUSE_RETENTION_DAYS", "30"))


def main() -> None:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=_RETENTION_DAYS)
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
    credentials = f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}"
    authorization = "Basic " + base64.b64encode(credentials.encode()).decode()

    def request(path, method="GET"):
        req = Request(host + path, headers={"Authorization": authorization}, method=method)
        with urlopen(req, timeout=30) as response:
            return json.load(response)

    # Collect IDs before deleting, so pagination cannot skip shifted rows.
    trace_ids = []
    page = 1
    while True:
        query = urlencode({"toTimestamp": cutoff.isoformat(), "page": page, "limit": 100})
        traces = request("/api/public/traces?" + query)["data"]
        trace_ids.extend(trace["id"] for trace in traces)
        if len(traces) < 100:
            break
        page += 1

    for trace_id in trace_ids:
        request("/api/public/traces/" + quote(trace_id, safe=""), method="DELETE")

    print(f"Deleted {len(trace_ids)} trace(s) older than {_RETENTION_DAYS} days.")


if __name__ == "__main__":
    main()
