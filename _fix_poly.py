with open("scrapers/polymarket.py", "r", encoding="utf-8") as f:
    content = f.read()

old_init = """    def __init__(self):
        self.gamma_url = bot_config.polymarket.gamma_url
        self.keywords = bot_config.polymarket.weather_keywords"""

new_init = """    def __init__(self):
        self.gamma_url = bot_config.polymarket.gamma_url
        self.keywords = bot_config.polymarket.weather_keywords
        self._async_client = None"""

content = content.replace(old_init, new_init)

with open("scrapers/polymarket.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Fixed polymarket.py")
