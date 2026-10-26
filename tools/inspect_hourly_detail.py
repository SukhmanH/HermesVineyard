import json

with open("/tmp/weather_fetch_result.json") as f:
    data = json.load(f)

for site, d in data.items():
    hourly = d.get("hourly", [])
    temps = [h["temp_c"] for h in hourly if h.get("temp_c") is not None]
    winds = [h["wind_kmh"] for h in hourly if h.get("wind_kmh") is not None]
    gusts = [h["gust_kmh"] for h in hourly if h.get("gust_kmh") is not None]
    print(f"Site {site}:")
    print(f"  Min temp: {min(temps)} C, Max temp: {max(temps)} C")
    print("  Daylight hours (next 8 hours):")
    for h in hourly[:8]:
        print(f"    {h['time']} | Temp: {h['temp_c']}C | Wind: {h['wind_kmh']} km/h | Gust: {h['gust_kmh']} | PoP: {h['precip_prob_pct']}% | {h['condition']}")
