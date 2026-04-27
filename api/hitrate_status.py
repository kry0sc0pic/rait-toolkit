from http.server import BaseHTTPRequestHandler

try:
    from ._shared import client_from_payload, read_json, safe_error, send_json, send_options
except ImportError:
    from _shared import client_from_payload, read_json, safe_error, send_json, send_options

COURSE_VIEW = "https://mydy.dypatil.edu/rait/course/view.php"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_options(self)

    def do_POST(self):
        try:
            payload = read_json(self)
            course_id = (payload.get("course_id") or "").strip()
            if not course_id:
                send_json(self, 400, safe_error("course_id is required."))
                return

            client, login = client_from_payload(payload)
            if client is None:
                send_json(self, 401, login)
                return

            course = {
                "id": course_id,
                "name": (payload.get("course_name") or "").strip(),
                "url": f"{COURSE_VIEW}?id={course_id}",
            }
            result = client.hit_rate_snapshot_course(course)
            err = result.get("error")
            if err:
                send_json(self, 200, {**safe_error(str(err)), "course_name": result.get("course_name", "")})
                return

            send_json(self, 200, {"success": True, **result})
        except Exception as exc:
            send_json(self, 500, safe_error(str(exc)))
