import json

with open("/tmp/weather_fetch_result.json") as f:
    data = json.load(f)

for s in ["penticton", "naramata", "oliver"]:
    d = data[s]
    print(f"SITE: {s}")
    print(f"Age: {d['age_hours']}")
    print(f"Hourly len: {len(d['hourly'])}")
    temps = [h["temp_c"] for h in d["hourly"] if h.get("temp_c") is not None]
    times = [h["time"] for h in d["hourly"]]
    print(f"Temps count: {len(temps)}")
    print(f"Min temp next 24h: {min(temps) if temps else 'N/A'}")
    print(f"First 12 hours: {list(zip(times[:12], temps[:12]))}")
    print(f"PWS Current: {d.get('pws_current')}")
    print(f"ECCC Current: {d.get('eccc_current')}")

