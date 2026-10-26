import json

with open("/tmp/hourly_oliver.json") as f:
    d = json.load(f)

print(json.dumps(d["hourly"]))
