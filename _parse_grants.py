import json

# Let's inspect the saved html or search them
import urllib.request
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def check_url(url, keywords):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        html = resp.read().decode('utf-8', errors='ignore')
        print(f"=== {url} ===")
        for line in html.splitlines():
            lower = line.lower()
            if any(kw in lower for kw in keywords):
                print("  ", line.strip()[:150])

check_url('https://bciaf.ca/programs/', ['efp', 'bmp', 'replant', 'climate', 'food safety', 'open', 'closed', 'coming soon'])
check_url('https://www.bcwgc.org/funding-opportunities/', ['grant', 'fund', 'replant', 'irrigation', 'open', 'closed'])
check_url('https://grapegrowers.bc.ca/funding', ['grant', 'fund', 'replant', 'irrigation', 'open', 'closed'])
