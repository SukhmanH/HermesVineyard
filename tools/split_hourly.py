import json

with open("/tmp/weather_fetch_result.json") as f:
    data = json.load(f)
for s in ["penticton", "naramata", "oliver"]:
    with open(f"/tmp/hourly_{s}.json", "w") as out_f:
        json.dump(data[s]["hourly"], out_f)
    print(f"Saved {s}: {data[s]['age_hours']} age_hours")
