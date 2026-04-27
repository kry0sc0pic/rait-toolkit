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
            course_id = str(payload.get("course_id") or "").strip()
            if not course_id:
                send_json(self, 400, safe_error("Missing course_id."))
                return

            client, login = client_from_payload(payload)
            if client is None:
                send_json(self, 401, login)
                return

            send_json(self, 200, {
                "success": True,
                "content": client.get_course_content(course_id),
                "assignments": client.get_assignments(course_id),
                "grades": client.get_grades(course_id),
                "announcements": client.get_announcements(course_id),
                "materials": client.list_downloadable_materials(course_id),
            })
        except Exception as exc:
            send_json(self, 500, safe_error(str(exc)))
