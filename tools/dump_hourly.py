import json

with open("/tmp/weather_fetch_result.json") as f:
    data = json.load(f)

for site in ["penticton", "naramata", "oliver"]:
    hourly = data[site]["hourly"]
    age = data[site]["age_hours"]
    with open(f"/tmp/hourly_{site}.json", "w") as f_out:
        json.dump({"site": site, "age_hours": age, "hourly": hourly}, f_out)
print("Dumped hourly json files successfully.")
