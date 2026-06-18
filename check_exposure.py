import sqlite3

db = sqlite3.connect(r"C:\Users\fdemir\Documents\New project\QwenBot\data\bot.db")

# Open bets
rows = db.execute(
    "SELECT status, COUNT(*), SUM(amount) FROM bets WHERE status IN ('placed','active','open','pending') GROUP BY status"
).fetchall()
for r in rows:
    print(f"{r[0]}: {r[1]} bets, ${r[2]}")

# Total exposure
r = db.execute("SELECT SUM(amount) FROM bets WHERE status IN ('placed','active','open','pending')").fetchone()
print(f"Total exposure: ${r[0]}")

# Closed bets count
r2 = db.execute("SELECT status, COUNT(*) FROM bets WHERE status IN ('won','lost','settled') GROUP BY status").fetchall()
for r in r2:
    print(f"{r[0]}: {r[1]}")

# Latest placed bets
rows2 = db.execute(
    "SELECT id, city, status, amount, placed_at FROM bets WHERE status IN ('placed','active','open','pending') ORDER BY placed_at DESC LIMIT 10"
).fetchall()
print("\nLatest 10 open bets:")
for r in rows2:
    print(f"  #{r[0]} {r[1]} status={r[2]} ${r[3]} placed={r[4]}")

# Bet placer - check where exposure check happens
db.close()
