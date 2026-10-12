@echo off
rem Double-click to start the web version; it opens in your browser. Close this window to stop it.
python -m pip install --upgrade --quiet "yt-dlp[default]"
python "%~dp0web_app.py"
