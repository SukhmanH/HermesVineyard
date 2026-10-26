import json

with open("/tmp/hourly_penticton.json") as f:
    d = json.load(f)

print(json.dumps(d["hourly"]))
