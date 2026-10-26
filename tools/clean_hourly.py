import json

with open("/tmp/weather_fetch_result.json") as f:
    d = json.load(f)

for s in ["penticton", "naramata", "oliver"]:
    for h in d[s]["hourly"]:
        del h["condition"]
        del h["wind_dir"]

with open("/tmp/hourly_clean.json", "w") as f:
    json.dump({s: d[s]["hourly"] for s in ["penticton", "naramata", "oliver"]}, f)
print("Saved clean hourly")
