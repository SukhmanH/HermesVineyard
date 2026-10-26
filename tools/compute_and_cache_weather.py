import sys
import json
from vineyard_mcp import server

compute_fn = getattr(server.compute_spray_window, "fn", server.compute_spray_window)

with open("/tmp/weather_fetch_result.json") as f:
    data = json.load(f)

results = {}
for site_key, site_data in data.items():
    if "error" in site_data:
        results[site_key] = site_data
        continue
    
    hourly = site_data["hourly"]
    age_hours = site_data["age_hours"]
    
    res = compute_fn(
        site=site_key,
        hourly=hourly,
        source="eccc",
        age_hours=age_hours
    )
    results[site_key] = {
        "verdict_result": res,
        "station_name": site_data["station_name"],
        "age_hours": age_hours,
        "eccc_current": site_data["eccc_current"],
        "pws_current": site_data["pws_current"]
    }

with open("/tmp/weather_verdicts.json", "w") as f:
    json.dump(results, f, indent=2)

print("SUCCESS: Computed and cached verdicts for all sites.")
for k, v in results.items():
    print(f"Site: {k}, Verdict: {v.get('verdict_result', {}).get('verdict')}, Recorded: {v.get('verdict_result', {}).get('recorded')}")
