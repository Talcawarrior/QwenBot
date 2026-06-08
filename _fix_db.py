import os
os.chdir(r"C:\Users\fdemir\Documents\New project\QwenBot")

with open("database/db.py", "r", encoding="utf-8") as f:
    content = f.read()

helper = """

def ensure_initial_portfolio():
    \"\"\"Create Portfolio(id=1) with INITIAL_PORTFOLIO values if it does not exist.

    Called by both the FastAPI lifespan (server mode) and run_cli() (CLI mode)
    so that Portfolio(id=1) is guaranteed to exist before any bet is placed.
    Idempotent - safe to call multiple times.
    \"\"\"
    from config.settings import config
    from database.models import Portfolio
    with get_session() as session:
        portfolio = session.query(Portfolio).filter(Portfolio.id == 1).first()
        if not portfolio:
            portfolio = Portfolio(
                id=1,
                initial_value=config.INITIAL_PORTFOLIO,
                current_value=config.INITIAL_PORTFOLIO,
                cash_balance=config.INITIAL_PORTFOLIO,
                total_value=config.INITIAL_PORTFOLIO,
                total_realized_pnl=0.0,
                total_won=0,
                total_lost=0,
                daily_pnl=0.0,
            )
            session.add(portfolio)
            session.commit()
            logger.info("ensure_initial_portfolio: Portfolio(id=1) created")
"""

if "ensure_initial_portfolio" not in content:
    content = content.rstrip() + "\n" + helper
    with open("database/db.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("db.py: ensure_initial_portfolio added")
else:
    print("db.py: ensure_initial_portfolio already exists")
