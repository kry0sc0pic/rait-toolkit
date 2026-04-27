from http.server import BaseHTTPRequestHandler

try:
    from ._shared import client_from_payload, read_json, safe_error, send_json, send_options
except ImportError:
    from _shared import client_from_payload, read_json, safe_error, send_json, send_options


CURRENT_SEM_COUNT = 8


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_options(self)

    def do_POST(self):
        try:
            payload = read_json(self)
            client, login = client_from_payload(payload)
            if client is None:
                send_json(self, 401, login)
                return

            courses = client.list_courses()
            if isinstance(courses, str):
                send_json(self, 502, safe_error(courses))
                return

            attendance = client.get_attendance()
            send_json(self, 200, {
                "success": True,
                "login": login,
                "courses": courses,
                "current_courses": courses[:CURRENT_SEM_COUNT],
                "attendance": attendance,
            })
        except Exception as exc:
            send_json(self, 500, safe_error(str(exc)))
