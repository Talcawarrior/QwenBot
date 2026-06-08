import os
os.chdir(r"C:\Users\fdemir\Documents\New project\QwenBot")

with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    new_lines.append(line)
    # After "Database hazir" line, add ensure_initial_portfolio()
    if 'logger.info("Database hazir")' in line or "logger.info('Database hazir')" in line:
        indent = line[:len(line) - len(line.lstrip())]
        new_lines.append(indent + "ensure_initial_portfolio()\n")
        print(f"main.py: added ensure_initial_portfolio() at line {i+2}")

with open("main.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)
print("main.py: saved")
