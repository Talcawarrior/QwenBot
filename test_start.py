import os
import subprocess
import sys

os.chdir(r"C:\Users\fdemir\Documents\New project\QwenBot")
log = open(r"C:\Users\fdemir\Documents\New project\QwenBot\start_log.txt", "w")
try:
    result = subprocess.run(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8091"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    log.write("STDOUT:\n" + result.stdout + "\n")
    log.write("STDERR:\n" + result.stderr + "\n")
    log.write(f"Return code: {result.returncode}\n")
except Exception as e:
    log.write(f"Exception: {e}\n")
finally:
    log.close()
