import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client import MydyClient  # noqa: E402


def read_json(request_handler) -> dict:
    length = int(request_handler.headers.get("content-length", "0") or 0)
    if not length:
        return {}
    body = request_handler.rfile.read(length).decode("utf-8")
    return json.loads(body or "{}")


def send_json(request_handler, status: int, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    request_handler.send_response(status)
    request_handler.send_header("content-type", "application/json; charset=utf-8")
    request_handler.send_header("access-control-allow-origin", "*")
    request_handler.send_header("access-control-allow-methods", "GET,POST,OPTIONS")
    request_handler.send_header("access-control-allow-headers", "content-type")
    request_handler.send_header("access-control-expose-headers", "content-disposition")
    request_handler.send_header("content-length", str(len(data)))
    request_handler.end_headers()
    request_handler.wfile.write(data)


def send_options(request_handler) -> None:
    request_handler.send_response(204)
    request_handler.send_header("access-control-allow-origin", "*")
    request_handler.send_header("access-control-allow-methods", "GET,POST,OPTIONS")
    request_handler.send_header("access-control-allow-headers", "content-type")
    request_handler.end_headers()


PORTAL_DEAD_MESSAGE = "MyDy LMS portal is dead. Try again later."


def _is_portal_down(result: dict) -> bool:
    """True if the failure looks like the LMS itself being broken (vs bad creds)."""
    message = (result.get("message") or "").lower()
    return (
        "lms may be down" in message
        or "network error" in message
        or "login result unclear" in message
        or "returned status" in message
    )


def client_from_payload(payload: dict) -> tuple[MydyClient | None, dict]:
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    client = MydyClient()
    result = client.login(username, password)
    if result.get("success"):
        return client, result

    if _is_portal_down(result):
        client = MydyClient()
        result = client.login(username, password)
        if result.get("success"):
            return client, result
        if _is_portal_down(result):
            return None, {"success": False, "message": PORTAL_DEAD_MESSAGE, "portal_down": True}

    return None, result


def safe_error(message: str) -> dict:
    return {"success": False, "message": message}
