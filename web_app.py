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

from yt_downloader import HAS_FFMPEG, build_options, human_size

HERE = Path(__file__).parent
JOBS = {}  # job id -> progress dict, read by the page while a download runs
JOBS_LOCK = threading.Lock()
PREVIEWS = {}  # url -> title/thumbnail from the last lookup, reused on the download card
OUT_DIR = Path.home() / "Downloads"

# Offered for playlists, where each video has its own set of resolutions.
PLAYLIST_HEIGHTS = (2160, 1440, 1080, 720, 480, 360)


def update(job_id, **fields):
    with JOBS_LOCK:
        JOBS[job_id].update(fields)


def is_video(f):
    return f.get("vcodec") not in (None, "none") and f.get("height")


def is_audio_only(f):
    return f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")


def size_of(f):
    return (f.get("filesize") or f.get("filesize_approx") or 0) if f else 0


def last_thumbnail(info):
    thumbs = info.get("thumbnails") or []
    return info.get("thumbnail") or (thumbs[-1].get("url") if thumbs else "")


def fetch_info(url, playlist):
    """Look a link up without downloading: title, thumbnail and every resolution on offer."""
    opts = build_options(None, OUT_DIR, playlist)
    opts["extract_flat"] = "in_playlist"
    opts.pop("format", None)  # only listing here; don't fail on a format we never download
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False, process=False)
        if info.get("_type", "video") == "video":
            info = ydl.process_ie_result(info, download=False)

    if info.get("_type") == "playlist":
        entries = list(info.get("entries") or [])
        thumb = last_thumbnail(info) or (last_thumbnail(entries[0]) if entries else "")
        result = {
            "kind": "playlist", "title": info.get("title") or "Playlist",
            "uploader": info.get("uploader") or info.get("channel") or "",
            "count": len(entries), "thumbnail": thumb,
            "options": [{"height": h, "label": f"{h}p", "fps": 0, "size": 0} for h in PLAYLIST_HEIGHTS],
            "audio": {"size": 0},
        }
    else:
        # yt-dlp lists formats worst to best, so the last match is the one it would pick.
        formats = info.get("formats") or []
        audio = next((f for f in reversed(formats) if is_audio_only(f)), None)
        best = {}
        for f in formats:
            if is_video(f):
                best[f["height"]] = f
        options = []
        for height in sorted(best, reverse=True):
            f = best[height]
            fps = round(f.get("fps") or 0)
            video_size = size_of(f)
            # A combined file already contains its audio.
            total = video_size + (size_of(audio) if f.get("acodec") in (None, "none") else 0)
            options.append({
                "height": height, "label": f"{height}p{fps if fps > 30 else ''}",
                "fps": fps, "size": total if video_size else 0,
            })
        result = {
            "kind": "video", "title": info.get("title") or "", "uploader": info.get("uploader") or "",
            "duration": info.get("duration") or 0, "thumbnail": last_thumbnail(info),
            "options": options, "audio": {"size": size_of(audio)},
        }
    PREVIEWS[url] = {"title": result["title"], "thumbnail": result["thumbnail"]}
    return result


def run_job(job_id, url, quality, playlist):
    def hook(d):
        title = (d.get("info_dict") or {}).get("title", "")
        fields = {"title": title} if title and not playlist else {}
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            pct = d.get("downloaded_bytes", 0) / total * 100 if total else 0
            text = f"{pct:.1f}% of {human_size(total)}"
            if d.get("speed"):
                text += f" - {human_size(d['speed'])}/s"
            if d.get("eta") is not None:
                text += f" - {int(d['eta'])}s left"
            if playlist and title:
                text = f"{title}: {text}"
            update(job_id, status="downloading", percent=round(pct, 1), text=text, **fields)
        elif d["status"] == "finished":
            update(job_id, status="processing", percent=100, text="Processing file...", **fields)

    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with yt_dlp.YoutubeDL(build_options(quality, OUT_DIR, playlist, hook)) as ydl:
            ydl.download([url])
        update(job_id, status="done", percent=100, text=f"Saved to {OUT_DIR}")
    except Exception as exc:  # yt-dlp raises many error types
        update(job_id, status="error", text=clean_error(exc))


def clean_error(exc):
    return str(exc).removeprefix("ERROR: ")[:300]


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

    def _json_body(self):
        """Parsed JSON body with a checked url, or None after replying with an error."""
        # Requiring JSON stops other websites from silently posting to this server.
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            self._send(404, {"error": "Not found"})
            return None
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            body["url"] = str(body.get("url", "")).strip()
        except (ValueError, AttributeError, TypeError):
            self._send(400, {"error": "Bad request."})
            return None
        if not body["url"].startswith(("http://", "https://")):
            self._send(400, {"error": "Please paste a full video link."})
            return None
        return body

    def do_GET(self):
        if not self._local_only():
            return
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, (HERE / "web" / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/config":
            self._send(200, {"folder": str(OUT_DIR), "ffmpeg": HAS_FFMPEG})
        elif path == "/api/jobs":
            with JOBS_LOCK:
                self._send(200, {"jobs": list(JOBS.values())})
        else:
            self._send(404, {"error": "Not found"})

    def do_POST(self):
        if not self._local_only():
            return
        if self.path not in ("/api/info", "/api/download"):
            self._send(404, {"error": "Not found"})
            return
        body = self._json_body()
        if body is None:
            return
        url, playlist = body["url"], bool(body.get("playlist"))

        if self.path == "/api/info":
            try:
                self._send(200, fetch_info(url, playlist))
            except Exception as exc:  # yt-dlp raises many error types
                self._send(400, {"error": clean_error(exc)})
            return

        quality = body.get("quality")  # a max height, "audio", or "best"
        if quality == "best":
            quality, label = None, "Best available"
        elif quality == "audio":
            label = "MP3 audio"
        elif isinstance(quality, int) and not isinstance(quality, bool) and 100 <= quality <= 5000:
            label = f"{quality}p"
        else:
            self._send(400, {"error": "Unknown quality."})
            return

        job_id = uuid.uuid4().hex
        preview = PREVIEWS.get(url, {})
        with JOBS_LOCK:
            JOBS[job_id] = {"id": job_id, "url": url, "quality": label, "status": "starting",
                            "percent": 0, "text": "Starting...", "title": preview.get("title", ""),
                            "thumbnail": preview.get("thumbnail", "")}
        threading.Thread(target=run_job, args=(job_id, url, quality, playlist), daemon=True).start()
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
