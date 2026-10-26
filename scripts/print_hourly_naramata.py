import json

with open("/tmp/hourly_naramata.json") as f:
    d = json.load(f)

print(json.dumps(d["hourly"]))
