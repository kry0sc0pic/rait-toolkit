from http.server import BaseHTTPRequestHandler
from urllib.parse import quote

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
            activity_url = (payload.get("activity_url") or "").strip()
            if not activity_url:
                send_json(self, 400, safe_error("Missing activity_url."))
                return

            client, login = client_from_payload(payload)
            if client is None:
                send_json(self, 401, login)
                return

            stream = client.open_material_stream(activity_url)
            if isinstance(stream, str):
                send_json(self, 502, safe_error(stream))
                return

            response = stream["response"]
            filename = stream["filename"]
            content_type = response.headers.get("content-type", "application/octet-stream")

            self.send_response(200)
            self.send_header("content-type", content_type)
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-expose-headers", "content-disposition")
            length = response.headers.get("content-length")
            if length:
                self.send_header("content-length", length)
            self.send_header(
                "content-disposition",
                f"attachment; filename*=UTF-8''{quote(filename)}",
            )
            self.end_headers()

            for chunk in response.iter_content(chunk_size=64 * 1024):
                if chunk:
                    self.wfile.write(chunk)
        except Exception as exc:
            send_json(self, 500, safe_error(str(exc)))
