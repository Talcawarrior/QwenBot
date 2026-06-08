import os
os.chdir(r"C:\Users\fdemir\Documents\New project\QwenBot")

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update import
old_import = "from database.db import init_db, get_db_session, get_db_session_factory"
new_import = "from database.db import init_db, get_db_session, get_db_session_factory, ensure_initial_portfolio"
if old_import in content:
    content = content.replace(old_import, new_import, 1)
    print("main.py: import updated")

# 2. Replace lifespan portfolio block
old_lifespan = """    # Ensure initial portfolio row exists in DB
    try:
        db = get_db_session()
        try:
            portfolio = db.query(Portfolio).filter(Portfolio.id == 1).first()
            if not portfolio:
                portfolio = Portfolio(
                    id=1,
                    initial_value=state.config.INITIAL_PORTFOLIO,
                    current_value=state.config.INITIAL_PORTFOLIO,
                    cash_balance=state.config.INITIAL_PORTFOLIO,
                    total_value=state.config.INITIAL_PORTFOLIO,
                    total_realized_pnl=0.0,
                )
                db.add(portfolio)
                db.commit()
                logger.info("Initial portfolio row created in DB")
        finally:
            db.close()
    except Exception as e:
        logger.warning("Portfolio init warning: %s", e)"""

new_lifespan = """    # Ensure initial portfolio row exists in DB
    try:
        ensure_initial_portfolio()
    except Exception as e:
        logger.warning("Portfolio init warning: %s", e)"""

if old_lifespan in content:
    content = content.replace(old_lifespan, new_lifespan, 1)
    print("main.py: lifespan portfolio block replaced")
else:
    print("main.py: WARNING - lifespan pattern not found")

# 3. Add ensure_initial_portfolio() call in run_cli()
old_cli = '    init_db()\n    logger.info("Database hazir")'
new_cli = '    init_db()\n    logger.info("Database hazir")\n    ensure_initial_portfolio()'
if old_cli in content:
    content = content.replace(old_cli, new_cli, 1)
    print("main.py: ensure_initial_portfolio added to run_cli")
else:
    print("main.py: WARNING - CLI init pattern not found")

# 4. Fix CLI reset
old_reset = """            pf = db.query(PortfolioModel).filter(PortfolioModel.id == 1).first()
            if pf:
                pf.cash_balance = state.config.INITIAL_PORTFOLIO
                pf.current_value = state.config.INITIAL_PORTFOLIO
                pf.total_value = state.config.INITIAL_PORTFOLIO
                pf.initial_value = state.config.INITIAL_PORTFOLIO
                pf.daily_pnl = 0.0
                pf.total_realized_pnl = 0.0
                pf.total_won = 0
                pf.total_lost = 0"""

new_reset = """            pf = db.query(PortfolioModel).filter(PortfolioModel.id == 1).first()
            if not pf:
                pf = PortfolioModel(id=1)
                db.add(pf)
            pf.cash_balance = state.config.INITIAL_PORTFOLIO
            pf.current_value = state.config.INITIAL_PORTFOLIO
            pf.total_value = state.config.INITIAL_PORTFOLIO
            pf.initial_value = state.config.INITIAL_PORTFOLIO
            pf.daily_pnl = 0.0
            pf.total_realized_pnl = 0.0
            pf.total_won = 0
            pf.total_lost = 0"""

if old_reset in content:
    content = content.replace(old_reset, new_reset, 1)
    print("main.py: CLI reset fixed")
else:
    print("main.py: WARNING - CLI reset pattern not found")

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("main.py: saved")
