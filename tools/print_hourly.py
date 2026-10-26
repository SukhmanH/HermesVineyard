import json

with open("/tmp/hourly_penticton.json") as f:
    hourly = json.load(f)

# Print as valid python literal or compact json
print(json.dumps(hourly))
