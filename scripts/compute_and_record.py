import os
import sys

sys.path.insert(0, os.path.abspath("."))
import json

from vineyard_mcp import server

compute_fn = getattr(server.compute_spray_window, "fn", server.compute_spray_window)

with open("/tmp/weather_fetch_data.json") as f:
    data = json.load(f)

results = {}
for site_key, site_data in data.items():
    hourly = site_data["hourly"]
    age_hours = site_data["age_hours"]

    res = compute_fn(
        site=site_key,
        hourly=hourly,
        source="eccc",
        age_hours=age_hours
    )
    results[site_key] = res
    print(f"Site: {site_key}, Verdict: {res.get('verdict')}, Reason: {res.get('reason')}, Recorded: {res.get('recorded')}")

with open("/tmp/weather_verdicts.json", "w") as f:
    json.dump(results, f, indent=2)
