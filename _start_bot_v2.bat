@echo off
set PYTHONPATH=C:\Users\fdemir\Documents\New project\QwenBot
set DRY_RUN=true
set HOST=127.0.0.1
set PORT=8091
set FLAT_BET_USD=10
set SCAN_INTERVAL=300
cd /d C:\Users\fdemir\Documents\New project\QwenBot
start /B python main.py run > logs\server.out.log 2> logs\server.err.log
