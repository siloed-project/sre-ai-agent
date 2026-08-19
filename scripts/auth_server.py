"""
Minimal HTTP auth server for the LangFuse dashboard (port 8081).

Routes:
  GET  /login[?next=<path>]  — render login form
  POST /login                — validate credentials, set session cookie
  GET  /_auth                — nginx auth_request endpoint (200 or 401)

Run:
  DASHBOARD_USERNAME=admin DASHBOARD_PASSWORD=secret \
  DASHBOARD_SECRET=32-char-random \
  python scripts/auth_server.py
"""

import http.server
import os
import urllib.parse
from http import HTTPStatus

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_COOKIE_NAME = "sre_session"
_MAX_AGE_SECONDS = 86400  # 24 h

_USERNAME = os.environ["DASHBOARD_USERNAME"]
_PASSWORD = os.environ["DASHBOARD_PASSWORD"]
_SECRET = os.environ["DASHBOARD_SECRET"]

_signer = URLSafeTimedSerializer(_SECRET)

_LOGIN_HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>sre-agent · dashboard</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0f172a;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:monospace}}
  .card{{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:2rem;width:320px}}
  h1{{color:#e2e8f0;font-size:1rem;margin-bottom:1.5rem;text-align:center}}
  label{{color:#94a3b8;font-size:.75rem;display:block;margin-bottom:.25rem}}
  input{{width:100%;background:#0f172a;border:1px solid #475569;border-radius:4px;color:#e2e8f0;font-family:monospace;font-size:.875rem;padding:.5rem .75rem;margin-bottom:1rem}}
  input:focus{{outline:none;border-color:#6366f1}}
  button{{width:100%;background:#6366f1;border:none;border-radius:4px;color:#fff;cursor:pointer;font-family:monospace;font-size:.875rem;padding:.6rem;margin-top:.25rem}}
  button:hover{{background:#818cf8}}
  .error{{color:#f87171;font-size:.75rem;margin-bottom:.75rem;text-align:center}}
</style>
</head>
<body>
<div class="card">
  <h1>sre-agent &middot; dashboard</h1>
  {error}
  <form method="post" action="/login">
    <input type="hidden" name="next" value="{next}">
    <label for="u">Username</label>
    <input id="u" name="username" type="text" autocomplete="username" required>
    <label for="p">Password</label>
    <input id="p" name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Sign in</button>
  </form>
</div>
</body>
</html>"""


def _render_login(next_path: str = "/", error: str = "") -> bytes:
    error_html = f'<p class="error">{error}</p>' if error else ""
    return _LOGIN_HTML.format(next=next_path, error=error_html).encode()


def _make_session_cookie(value: str) -> str:
    token = _signer.dumps(value)
    return (
        f"{_COOKIE_NAME}={token}; "
        f"HttpOnly; Secure; SameSite=Lax; Max-Age={_MAX_AGE_SECONDS}; Path=/"
    )


def _validate_cookie(cookie_header: str) -> bool:
    for part in cookie_header.split(";"):
        name, _, value = part.strip().partition("=")
        if name.strip() == _COOKIE_NAME:
            try:
                _signer.loads(value.strip(), max_age=_MAX_AGE_SECONDS)
                return True
            except (BadSignature, SignatureExpired):
                return False
    return False


class AuthHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:  # silence access log
        pass

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/_auth":
            self._handle_auth_check()
        elif parsed.path == "/login":
            next_path = urllib.parse.parse_qs(parsed.query).get("next", ["/"])[0]
            body = _render_login(next_path)
            self._respond(HTTPStatus.OK, "text/html; charset=utf-8", body)
        else:
            self._respond(HTTPStatus.NOT_FOUND, "text/plain", b"Not found")

    def do_POST(self) -> None:
        if self.path.split("?")[0] != "/login":
            self._respond(HTTPStatus.NOT_FOUND, "text/plain", b"Not found")
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode()
        params = urllib.parse.parse_qs(body)
        username = params.get("username", [""])[0]
        password = params.get("password", [""])[0]
        next_path = params.get("next", ["/"])[0]

        if username == _USERNAME and password == _PASSWORD:
            cookie = _make_session_cookie(username)
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Set-Cookie", cookie)
            self.send_header("Location", next_path)
            self.end_headers()
        else:
            body_html = _render_login(next_path, error="Invalid username or password.")
            self._respond(HTTPStatus.OK, "text/html; charset=utf-8", body_html)

    def _handle_auth_check(self) -> None:
        cookie_header = self.headers.get("Cookie", "")
        if _validate_cookie(cookie_header):
            self._respond(HTTPStatus.OK, "text/plain", b"OK")
        else:
            self._respond(HTTPStatus.UNAUTHORIZED, "text/plain", b"Unauthorized")

    def _respond(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = http.server.HTTPServer(("127.0.0.1", 8081), AuthHandler)
    print("Auth server listening on http://127.0.0.1:8081")
    server.serve_forever()
