@echo off
cd /d "C:\Users\fdemir\Documents\New project\QwenBot"
python -m uvicorn main:app --host 0.0.0.0 --port 8091
