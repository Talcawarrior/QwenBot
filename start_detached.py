import os
import subprocess

os.chdir(r"C:\Users\fdemir\Documents\New project\QwenBot")
subprocess.Popen(
    ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8091"],
    cwd=r"C:\Users\fdemir\Documents\New project\QwenBot",
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
    stdout=open(os.devnull, "w"),
    stderr=open(os.devnull, "w"),
)
