from http.server import BaseHTTPRequestHandler

try:
    from ._shared import client_from_payload, read_json, safe_error, send_json, send_options
except ImportError:
    from _shared import client_from_payload, read_json, safe_error, send_json, send_options

COURSE_VIEW = "https://mydy.dypatil.edu/rait/course/view.php"


def _course_obj(item: dict) -> dict | None:
    cid = str(item.get("course_id") or item.get("id") or "").strip()
    if not cid:
        return None
    return {
        "id": cid,
        "name": (item.get("course_name") or item.get("name") or "").strip(),
        "url": f"{COURSE_VIEW}?id={cid}",
    }


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        send_options(self)

    def do_POST(self):
        try:
            payload = read_json(self)

            courses_payload = payload.get("courses")
            if isinstance(courses_payload, list):
                resolved = [c for c in (_course_obj(item) for item in courses_payload) if c]
                if not resolved:
                    send_json(self, 400, safe_error("courses list is required."))
                    return

                client, login = client_from_payload(payload)
                if client is None:
                    send_json(self, 401, login)
                    return

                batch = client.hit_rate_snapshot_courses(resolved)
                send_json(self, 200, {"success": True, **batch})
                return

            single = _course_obj(payload)
            if single is None:
                send_json(self, 400, safe_error("course_id is required."))
                return

            client, login = client_from_payload(payload)
            if client is None:
                send_json(self, 401, login)
                return

            result = client.hit_rate_snapshot_course(single)
            err = result.get("error")
            if err:
                send_json(self, 200, {**safe_error(str(err)), "course_name": result.get("course_name", "")})
                return

            send_json(self, 200, {"success": True, **result})
        except Exception as exc:
            send_json(self, 500, safe_error(str(exc)))
