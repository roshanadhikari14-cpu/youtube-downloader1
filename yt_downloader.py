"""YouTube Downloader - a small desktop GUI around yt-dlp.

Run:  python yt_downloader.py
Needs: pip install "yt-dlp[default]", ffmpeg (merging / MP3) and Node.js or Deno
"""

import glob
import os
import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import yt_dlp

# Label shown in the dropdown -> max video height (None = no cap, "audio" = MP3)
QUALITIES = {
    "Best available": None,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
    "Audio only (MP3)": "audio",
}


def find_ffmpeg():
    """Locate ffmpeg even when this process started with an out-of-date PATH."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    if os.name != "nt":
        return None
    # PATH as currently saved in Windows (ours may predate an ffmpeg install/upgrade).
    import winreg
    dirs = []
    for root, key in (
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ):
        try:
            with winreg.OpenKey(root, key) as k:
                dirs += os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]).split(os.pathsep)
        except OSError:
            pass
    found = shutil.which("ffmpeg", path=os.pathsep.join(dirs))
    if found:
        return found
    # winget installs ffmpeg under a versioned folder; take the newest.
    pattern = os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin\ffmpeg.exe")
    matches = sorted(glob.glob(pattern), key=os.path.getmtime)
    return matches[-1] if matches else None


FFMPEG = find_ffmpeg()
HAS_FFMPEG = FFMPEG is not None


def build_options(quality, out_dir, playlist=False, progress_hook=None):
    """Translate the GUI choices into a yt-dlp options dict."""
    choice = QUALITIES[quality]
    opts = {
        "outtmpl": str(Path(out_dir) / "%(title)s.%(ext)s"),
        "noplaylist": not playlist,
        "quiet": True,
        "no_warnings": True,
        "windowsfilenames": True,
        # YouTube needs a JavaScript runtime; yt-dlp only looks for deno unless told otherwise.
        "js_runtimes": {"deno": {}, "node": {}},
    }
    if HAS_FFMPEG:
        opts["ffmpeg_location"] = FFMPEG
    if progress_hook:
        opts["progress_hooks"] = [progress_hook]

    if choice == "audio":
        opts["format"] = "bestaudio/best"
        if HAS_FFMPEG:
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
    elif HAS_FFMPEG:
        cap = f"[height<={choice}]" if choice else ""
        opts["format"] = f"bestvideo{cap}+bestaudio/best{cap}/best"
        opts["merge_output_format"] = "mp4"
    else:
        # Without ffmpeg we can't merge streams, so take a single combined file.
        cap = f"[height<={choice}]" if choice else ""
        opts["format"] = f"best{cap}/best"
    return opts


def human_size(n):
    if not n:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Downloader")
        self.geometry("620x330")
        self.minsize(520, 330)

        self.events = queue.Queue()  # worker thread -> UI thread
        self.busy = False

        self.url = tk.StringVar()
        self.quality = tk.StringVar(value="Best available")
        self.folder = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.playlist = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Paste a link and press Download.")
        self.title_text = tk.StringVar()

        self._build()
        self.after(100, self._drain_events)

    def _build(self):
        pad = {"padx": 12, "pady": 6}
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Video URL").grid(row=0, column=0, sticky="w", **pad)
        entry = ttk.Entry(frame, textvariable=self.url)
        entry.grid(row=0, column=1, sticky="ew", **pad)
        entry.focus()
        entry.bind("<Return>", lambda _e: self.start())
        ttk.Button(frame, text="Paste", command=self.paste).grid(row=0, column=2, **pad)

        ttk.Label(frame, text="Quality").grid(row=1, column=0, sticky="w", **pad)
        ttk.Combobox(
            frame, textvariable=self.quality, values=list(QUALITIES),
            state="readonly", width=22,
        ).grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(frame, text="Save to").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.folder).grid(row=2, column=1, sticky="ew", **pad)
        ttk.Button(frame, text="Browse", command=self.browse).grid(row=2, column=2, **pad)

        ttk.Checkbutton(
            frame, text="Download whole playlist", variable=self.playlist,
        ).grid(row=3, column=1, sticky="w", **pad)

        self.button = ttk.Button(frame, text="Download", command=self.start)
        self.button.grid(row=4, column=1, sticky="w", **pad)

        ttk.Label(frame, textvariable=self.title_text, font=("Segoe UI", 9, "bold")).grid(
            row=5, column=0, columnspan=3, sticky="w", padx=12)
        self.bar = ttk.Progressbar(frame, maximum=100)
        self.bar.grid(row=6, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Label(frame, textvariable=self.status, wraplength=580).grid(
            row=7, column=0, columnspan=3, sticky="w", padx=12)

        if not HAS_FFMPEG:
            self.status.set("ffmpeg not found - HD merging and MP3 conversion are disabled.")

    def paste(self):
        try:
            self.url.set(self.clipboard_get().strip())
        except tk.TclError:
            pass

    def browse(self):
        chosen = filedialog.askdirectory(initialdir=self.folder.get())
        if chosen:
            self.folder.set(chosen)

    def start(self):
        if self.busy:
            return
        url = self.url.get().strip()
        if not url.startswith(("http://", "https://")):
            messagebox.showwarning("Invalid link", "Please paste a full video URL.")
            return
        out_dir = Path(self.folder.get())
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Folder error", str(exc))
            return

        self.busy = True
        self.button.config(state="disabled")
        self.bar["value"] = 0
        self.title_text.set("")
        self.status.set("Fetching video info...")
        opts = build_options(self.quality.get(), out_dir, self.playlist.get(), self._hook)
        threading.Thread(target=self._work, args=(url, opts), daemon=True).start()

    # ---- worker thread -------------------------------------------------
    def _work(self, url, opts):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            self.events.put(("done", None))
        except Exception as exc:  # yt-dlp raises many error types
            self.events.put(("error", str(exc)))

    def _hook(self, d):
        info = d.get("info_dict") or {}
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes", 0)
            pct = done / total * 100 if total else 0
            speed = d.get("speed")
            eta = d.get("eta")
            text = f"{pct:.1f}%  of {human_size(total)}"
            if speed:
                text += f"  -  {human_size(speed)}/s"
            if eta is not None:
                text += f"  -  {int(eta)}s left"
            self.events.put(("progress", (pct, text, info.get("title", ""))))
        elif d["status"] == "finished":
            self.events.put(("progress", (100, "Processing file...", info.get("title", ""))))

    # ---- UI thread -----------------------------------------------------
    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    pct, text, title = payload
                    self.bar["value"] = pct
                    self.status.set(text)
                    if title:
                        self.title_text.set(title)
                elif kind == "done":
                    self._finish(f"Done. Saved to {self.folder.get()}")
                    self.bar["value"] = 100
                elif kind == "error":
                    self._finish("Download failed.")
                    messagebox.showerror("Download failed", payload)
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _finish(self, message):
        self.busy = False
        self.button.config(state="normal")
        self.status.set(message)


if __name__ == "__main__":
    App().mainloop()
