with open("scrapers/meteo.py", "r", encoding="utf-8") as f:
    content = f.read()

old_class = """class MeteoFetcher:
    \"\"\"Fetches real-time weather forecasts and saves to weather_forecasts.\"\"\"

    CITY_COORDS = {"""

new_class = """class MeteoFetcher:
    \"\"\"Fetches real-time weather forecasts and saves to weather_forecasts.\"\"\"

    def __init__(self):
        self._async_client = None

    async def close_session(self):
        \"\"\"Close the AsyncHttpClient aiohttp session (if any).\"\"\"
        client = getattr(self, "_async_client", None)
        if client is not None and hasattr(client, "aclose"):
            await client.aclose()

    CITY_COORDS = {"""

content = content.replace(old_class, new_class)

with open("scrapers/meteo.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Fixed meteo.py")
