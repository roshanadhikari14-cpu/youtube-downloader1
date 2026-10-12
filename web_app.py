"""YouTube Downloader - web version.

Runs a small web server on this computer and opens the page in your browser.
Videos are saved on this computer (Downloads folder by default).

Run:  python web_app.py
"""

import argparse
import json
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yt_dlp

from yt_downloader import HAS_FFMPEG, QUALITIES, build_options, human_size

HERE = Path(__file__).parent
JOBS = {}  # job id -> progress dict, read by the page while a download runs
JOBS_LOCK = threading.Lock()
OUT_DIR = Path.home() / "Downloads"


def update(job_id, **fields):
    with JOBS_LOCK:
        JOBS[job_id].update(fields)


def run_job(job_id, url, quality, playlist):
    def hook(d):
        title = (d.get("info_dict") or {}).get("title", "")
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            pct = d.get("downloaded_bytes", 0) / total * 100 if total else 0
            text = f"{pct:.1f}% of {human_size(total)}"
            if d.get("speed"):
                text += f" - {human_size(d['speed'])}/s"
            if d.get("eta") is not None:
                text += f" - {int(d['eta'])}s left"
            update(job_id, status="downloading", percent=round(pct, 1), text=text, title=title)
        elif d["status"] == "finished":
            update(job_id, status="processing", percent=100, text="Processing file...", title=title)

    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with yt_dlp.YoutubeDL(build_options(quality, OUT_DIR, playlist, hook)) as ydl:
            ydl.download([url])
        update(job_id, status="done", percent=100, text=f"Saved to {OUT_DIR}")
    except Exception as exc:  # yt-dlp raises many error types
        update(job_id, status="error", text=str(exc))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _send(self, code, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _local_only(self):
        # Refuse requests that reach us under another hostname (DNS rebinding).
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host in ("127.0.0.1", "localhost"):
            return True
        self._send(403, {"error": "This app only answers on localhost."})
        return False

    def do_GET(self):
        if not self._local_only():
            return
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, (HERE / "web" / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/config":
            self._send(200, {"qualities": list(QUALITIES), "folder": str(OUT_DIR), "ffmpeg": HAS_FFMPEG})
        elif path == "/api/jobs":
            with JOBS_LOCK:
                self._send(200, {"jobs": list(JOBS.values())})
        else:
            self._send(404, {"error": "Not found"})

    def do_POST(self):
        if not self._local_only():
            return
        # Requiring JSON stops other websites from silently posting to this server.
        if self.path != "/api/download" or "application/json" not in (self.headers.get("Content-Type") or ""):
            self._send(404, {"error": "Not found"})
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            url = str(body.get("url", "")).strip()
            quality = body.get("quality", "Best available")
        except (ValueError, AttributeError):
            self._send(400, {"error": "Bad request."})
            return
        if not url.startswith(("http://", "https://")):
            self._send(400, {"error": "Please paste a full video URL."})
            return
        if quality not in QUALITIES:
            self._send(400, {"error": "Unknown quality."})
            return

        job_id = uuid.uuid4().hex
        with JOBS_LOCK:
            JOBS[job_id] = {"id": job_id, "url": url, "quality": quality, "status": "starting",
                            "percent": 0, "text": "Fetching video info...", "title": ""}
        threading.Thread(
            target=run_job, args=(job_id, url, quality, bool(body.get("playlist"))), daemon=True,
        ).start()
        self._send(200, {"id": job_id})


def main():
    global OUT_DIR
    parser = argparse.ArgumentParser(description="YouTube Downloader (web version)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dir", type=Path, default=OUT_DIR, help="folder to save downloads in")
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser")
    args = parser.parse_args()
    OUT_DIR = args.dir

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    address = f"http://localhost:{args.port}"
    print(f"YouTube Downloader is running at {address}  (close this window to stop it)")
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
