# YouTube Downloader

A small Windows desktop app (Python + Tkinter) built on [yt-dlp](https://github.com/yt-dlp/yt-dlp).
Paste a link, pick a quality, download.

## Features

- Quality: best available, 1080p, 720p, 480p, 360p, or audio-only MP3
- Choose the save folder (defaults to Downloads)
- Optional whole-playlist download
- Progress bar with size, speed and time left

## Requirements

- Python 3.9+
- [ffmpeg](https://ffmpeg.org/) on PATH (needed for HD merging and MP3 conversion)

## Run

```bash
pip install -r requirements.txt
python yt_downloader.py
```

On Windows you can also double-click `run.bat`, which updates yt-dlp and opens the app.

## Note

Only download videos you own or have permission to save. YouTube's terms of service
restrict downloading other content.
