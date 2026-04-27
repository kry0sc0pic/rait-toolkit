from http.server import BaseHTTPRequestHandler

try:
    from ._shared import client_from_payload, read_json, safe_error, send_json, send_options
except ImportError:
    from _shared import client_from_payload, read_json, safe_error, send_json, send_options


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_options(self)

    def do_POST(self):
        try:
            payload = read_json(self)
            _, result = client_from_payload(payload)
            status = 200 if result.get("success") else 401
            send_json(self, status, result)
        except Exception as exc:
            send_json(self, 500, safe_error(str(exc)))
