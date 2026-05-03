from __future__ import annotations

import base64
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client import MydyClient  # noqa: E402

try:
    from ._shared import client_from_payload, read_json, safe_error, send_json, send_options
except ImportError:
    from _shared import client_from_payload, read_json, safe_error, send_json, send_options


def _b64url_decode(value: str) -> str | None:
    if not value:
        return None
    try:
        padded = value + "=" * ((4 - len(value) % 4) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:
        return None


def _stream_to_client(req: BaseHTTPRequestHandler, client: MydyClient, activity_url: str) -> None:
    stream = client.open_material_stream(activity_url)
    if isinstance(stream, str):
        send_json(req, 502, safe_error(stream))
        return

    response = stream["response"]
    filename = stream["filename"]
    content_type = response.headers.get("content-type", "application/octet-stream")

    req.send_response(200)
    req.send_header("content-type", content_type)
    req.send_header("access-control-allow-origin", "*")
    req.send_header("access-control-expose-headers", "content-disposition")
    length = response.headers.get("content-length")
    if length:
        req.send_header("content-length", length)
    req.send_header(
        "content-disposition",
        f"attachment; filename*=UTF-8''{quote(filename)}",
    )
    req.end_headers()

    for chunk in response.iter_content(chunk_size=64 * 1024):
        if chunk:
            req.wfile.write(chunk)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_options(self)

    def do_GET(self):
        try:
            url = urlparse(self.path)
            params = parse_qs(url.query)
            email = _b64url_decode((params.get("u") or [""])[0])
            password = _b64url_decode((params.get("p") or [""])[0])
            activity_url = _b64url_decode((params.get("a") or [""])[0])

            if not email or password is None or not activity_url:
                send_json(self, 400, safe_error("Missing or invalid u / p / a query params."))
                return

            client = MydyClient()
            login = client.login(email, password)
            if not login.get("success"):
                send_json(self, 401, safe_error(login.get("message") or "Login failed."))
                return

            _stream_to_client(self, client, activity_url)
        except Exception as exc:
            send_json(self, 500, safe_error(str(exc)))

    def do_POST(self):
        try:
            payload = read_json(self)
            activity_url = (payload.get("activity_url") or "").strip()
            if not activity_url:
                send_json(self, 400, safe_error("Missing activity_url."))
                return

            client, login = client_from_payload(payload)
            if client is None:
                send_json(self, 401, login)
                return

            _stream_to_client(self, client, activity_url)
        except Exception as exc:
            send_json(self, 500, safe_error(str(exc)))
