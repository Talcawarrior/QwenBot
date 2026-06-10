@echo off
set PYTHONPATH=C:\Users\fdemir\Documents\New project\QwenBot
set DRY_RUN=true
set HOST=127.0.0.1
set PORT=8091
set FLAT_BET_USD=10
set SCAN_INTERVAL=300
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d C:\Users\fdemir\Documents\New project\QwenBot
chcp 65001 >nul
start /B python -X utf8 main.py run > logs\server_v3.out.log 2> logs\server_v3.err.log

