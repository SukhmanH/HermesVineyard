import json

with open("/tmp/weather_fetch_result.json") as f:
    d = json.load(f)

for s in ["penticton", "naramata", "oliver"]:
    temps = [h["temp_c"] for h in d[s]["hourly"] if h["temp_c"] is not None]
    winds = [h["wind_kmh"] for h in d[s]["hourly"] if h["wind_kmh"] is not None]
    pops = [h["precip_prob_pct"] for h in d[s]["hourly"] if h["precip_prob_pct"] is not None]
    print(f"=== {s} ===")
    print(f"Tmax: {max(temps)}, Tmin: {min(temps)}")
    print(f"Wind max: {max(winds)}, Wind min: {min(winds)}")
    print(f"POP max: {max(pops)}")
    print("Conditions summary:", set(h["condition"] for h in d[s]["hourly"]))
