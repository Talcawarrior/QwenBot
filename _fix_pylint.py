import os
os.chdir(r"C:\Users\fdemir\Documents\New project\QwenBot")

with open("executor/bet_placer.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix import 1
old1 = "from py_clob_client.client import ClobClient"
new1 = "from py_clob_client.client import ClobClient  # pylint: disable=import-error,no-name-in-module"
if old1 in content and "# pylint: disable" not in content.split(old1)[1][:20]:
    content = content.replace(old1, new1, 1)
    print("bet_placer.py: pylint disable added to ClobClient import")

# Fix import 2
old2 = "from py_clob_client.order_builder.constants import BUY"
new2 = "from py_clob_client.order_builder.constants import BUY  # pylint: disable=import-error,no-name-in-module"
if old2 in content and "# pylint: disable" not in content.split(old2)[1][:20]:
    content = content.replace(old2, new2, 1)
    print("bet_placer.py: pylint disable added to BUY import")

with open("executor/bet_placer.py", "w", encoding="utf-8") as f:
    f.write(content)
print("bet_placer.py: saved")
