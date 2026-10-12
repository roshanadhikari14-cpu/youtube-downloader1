@echo off
rem Double-click to launch the downloader (updates yt-dlp first, since YouTube changes often).
python -m pip install --upgrade --quiet yt-dlp
start "" pythonw "%~dp0yt_downloader.py"
