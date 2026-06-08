import os
os.chdir(r"C:\Users\fdemir\Documents\New project\QwenBot")

with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find line 811 (0-indexed: 810) which is init_db() in run_cli
# Line 812 (0-indexed: 811) should be logger.info
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == "init_db()" and i > 700:  # run_cli context, not lifespan
        # Check next line has logger.info
        if i + 1 < len(lines) and "logger.info" in lines[i + 1]:
            # Check if ensure_initial_portfolio already there
            if i + 2 < len(lines) and "ensure_initial_portfolio" in lines[i + 2]:
                print("main.py: ensure_initial_portfolio already added")
                break
            indent = line[:len(line) - len(line.lstrip())]
            lines.insert(i + 2, indent + "ensure_initial_portfolio()\n")
            print(f"main.py: added ensure_initial_portfolio() at position {i+2}")
            break

with open("main.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
print("main.py: saved")
