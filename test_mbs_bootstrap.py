#!/usr/bin/env python3
import json
import re
import requests

FLARESOLVERR_URL = "http://localhost:8191/v1"
URL = "https://www.mystcstore.com/SelectTermDept"

print("[1] Calling FlareSolverr...")
resp = requests.post(FLARESOLVERR_URL, json={
    "cmd": "request.get",
    "url": URL,
    "maxTimeout": 60000,
})
data = resp.json()
print(f"    Status: {data.get('status')}")
sol = data["solution"]
print(f"    URL: {sol.get('url')}")
print(f"    Status code: {sol.get('status')}")

html = sol.get("response", "")
print(f"    HTML length: {len(html)}")
print(f"    Title: ", end="")
title_m = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE)
if title_m:
    print(title_m.group(1))
else:
    print("(no title found)")

token_m = re.search(r'name="__RequestVerificationToken".*?value="([^"]+)"', html)
if token_m:
    print(f"    Token found: {token_m.group(1)[:30]}...")
else:
    print("    TOKEN NOT FOUND in HTML!")
    token_m2 = re.search(r'__RequestVerificationToken', html)
    if token_m2:
        print(f"    But __RequestVerificationToken IS mentioned at pos {token_m2.start()}")
        print(f"    Context: {html[max(0,token_m2.start()-50):token_m2.start()+200]}")
    else:
        print("    __RequestVerificationToken not in page at all")

cookies = {}
for c in sol.get("cookies", []):
    if c.get("name"):
        cookies[c["name"]] = c["value"]
print(f"    Cookies: {list(cookies.keys())}")

print(f"\n    HTML first 1000 chars:\n{html[:1000]}")

with open("/tmp/mbs_bootstrap.html", "w") as f:
    f.write(html)
print(f"\n    Full HTML saved to /tmp/mbs_bootstrap.html")
