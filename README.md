# YouTube Downloader

A small YouTube downloader built on [yt-dlp](https://github.com/yt-dlp/yt-dlp), in two flavours:

- **Desktop app** (Python + Tkinter): `yt_downloader.py`
- **Web app** that runs on your own computer and opens in your browser: `web_app.py`

Paste a link, pick a quality, download.

## Features

- Quality: best available, 1080p, 720p, 480p, 360p, or audio-only MP3
- Choose the save folder (defaults to Downloads)
- Optional whole-playlist download
- Progress bar with size, speed and time left

## Requirements

- Python 3.9+
- [ffmpeg](https://ffmpeg.org/) (needed for HD merging and MP3 conversion)
- [Node.js](https://nodejs.org/) or [Deno](https://deno.com/) (yt-dlp needs a JavaScript runtime for YouTube)

## Run

```bash
pip install -r requirements.txt
python yt_downloader.py
```

On Windows you can also double-click `run.bat`, which updates yt-dlp and opens the app.

### Web version

```bash
python web_app.py
```

or double-click `run_web.bat`. The page opens at http://localhost:8765 and files are saved to
your Downloads folder (`--dir` changes the folder, `--port` the port). The server only answers
on localhost, so it is not reachable from other devices.

## Note

Only download videos you own or have permission to save. YouTube's terms of service
restrict downloading other content.
