"""Local full-stack server for LMS Buddy without the Vercel CLI."""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from api.course import handler as CourseHandler
from api.dashboard import handler as DashboardHandler
from api.download import handler as DownloadHandler
from api.login import handler as LoginHandler


ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "web" / "dist"

API_HANDLERS = {
    "/api/login": LoginHandler,
    "/api/dashboard": DashboardHandler,
    "/api/course": CourseHandler,
    "/api/download": DownloadHandler,
}


class LocalHandler(SimpleHTTPRequestHandler):
    """Serve static app files and delegate API requests to Vercel-style handlers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

    def do_OPTIONS(self):
        if self.path in API_HANDLERS:
            return self._dispatch_api()
        return super().do_OPTIONS()

    def do_POST(self):
        if self.path in API_HANDLERS:
            return self._dispatch_api()
        self.send_error(404, "Not found")

    def do_GET(self):
        if self.path.startswith("/api/"):
            self.send_error(405, "Method not allowed")
            return
        if not (DIST_DIR / self.path.lstrip("/")).exists() and "." not in Path(self.path).name:
            self.path = "/index.html"
        return super().do_GET()

    def _dispatch_api(self):
        handler_cls = API_HANDLERS[self.path]
        original_class = self.__class__
        self.__class__ = handler_cls
        try:
            method = getattr(self, f"do_{self.command}", None)
            if method is None:
                self.send_error(405, "Method not allowed")
                return
            return method()
        finally:
            self.__class__ = original_class


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LMS Buddy locally without Vercel.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    if not DIST_DIR.exists():
        raise SystemExit("web/dist not found. Run `npm run build` first.")

    server = ThreadingHTTPServer((args.host, args.port), LocalHandler)
    print(f"LMS Buddy local server: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
