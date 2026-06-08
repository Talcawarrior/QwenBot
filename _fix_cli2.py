import os
os.chdir(r"C:\Users\fdemir\Documents\New project\QwenBot")

with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find the line with init_db() in run_cli context
found = False
for i, line in enumerate(lines):
    if "init_db()" in line and not found:
        # Check if next line has logger.info with "hazir" (could be Turkish chars)
        if i + 1 < len(lines) and "logger.info" in lines[i+1] and "hazir" in lines[i+1].lower():
            # Check if ensure_initial_portfolio is already there
            if i + 2 < len(lines) and "ensure_initial_portfolio" in lines[i+2]:
                print("main.py: already added")
                found = True
                break
            indent = line[:len(line) - len(line.lstrip())]
            lines.insert(i + 2, indent + "ensure_initial_portfolio()\n")
            print(f"main.py: added ensure_initial_portfolio() after line {i+2}")
            found = True
            break

if not found:
    print("main.py: pattern not found, searching all init_db lines")
    for i, line in enumerate(lines):
        if "init_db()" in line:
            print(f"  line {i+1}: {repr(line.strip())}")
            if i + 1 < len(lines):
                print(f"  line {i+2}: {repr(lines[i+1].strip())}")

with open("main.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
