import json
import ssl
import urllib.request

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

urls = [
    'https://bciaf.ca/programs/',
    'https://www.bcwgc.org/funding-opportunities/',
    'https://grapegrowers.bc.ca/funding',
    'https://www2.gov.bc.ca/gov/content/industry/agriculture-seafood/programs'
]

results = {}
for url in urls:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            results[url] = {"status": "ok", "length": len(html), "snippet": html[:500]}
    except Exception as e:
        results[url] = {"status": "error", "error": str(e)}

print(json.dumps(results, indent=2))
