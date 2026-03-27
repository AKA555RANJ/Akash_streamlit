#!/usr/bin/env python3
import json
import re
import requests
import time

BASE_URL = "https://www.mystcstore.com"
FLARESOLVERR_URL = "http://localhost:8191/v1"
AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/x-www-form-urlencoded"}

print("[1] Fresh FlareSolverr session...")
try: requests.post(FLARESOLVERR_URL, json={"cmd": "sessions.destroy", "session": "bulk"}, timeout=10)
except: pass
requests.post(FLARESOLVERR_URL, json={"cmd": "sessions.create", "session": "bulk"}, timeout=30)

resp = requests.post(FLARESOLVERR_URL, json={
    "cmd": "request.get", "url": BASE_URL + "/SelectTermDept",
    "session": "bulk", "maxTimeout": 60000})
sol = resp.json()["solution"]
html, ua = sol["response"], sol["userAgent"]
cookies = {c["name"]: c["value"] for c in sol.get("cookies", []) if c.get("name")}
m = re.search(r'name="__RequestVerificationToken".*?value="([^"]+)"', html)
token = m.group(1) if m else ""

sess = requests.Session()
sess.cookies.update(cookies)
sess.headers.update({"User-Agent": ua, "Origin": BASE_URL, "Referer": BASE_URL + "/SelectTermDept"})
print(f"    Token OK, Cookies: {list(cookies.keys())}")

term_id = "271713"
resp = sess.post(BASE_URL + "/SelectTermDept/Department",
    data={"__RequestVerificationToken": token, "termId": term_id}, headers=AJAX_HEADERS, timeout=30)
text = json.loads(resp.text) if resp.text.startswith('"') else resp.text
depts = re.findall(r'data-id\s*=\s*"dpt-(\d+)"[^>]*>\s*(.*?)\s*<', text)
print(f"\n[2] Found {len(depts)} departments, using first 3...")

all_courses = []
for dept_id, dept_code in depts[:3]:
    resp = sess.post(BASE_URL + "/SelectTermDept/Courses",
        data={"__RequestVerificationToken": token, "termId": term_id, "deptId": dept_id},
        headers=AJAX_HEADERS, timeout=30)
    text = json.loads(resp.text) if resp.text.startswith('"') else resp.text
    courses = re.findall(r'data-id\s*=\s*"cou-(\d+)"[^>]*>\s*(.*?)\s*<', text)
    for cid, ctext in courses:
        all_courses.append((cid, ctext, dept_id, dept_code))
    print(f"    {dept_code}: {len(courses)} courses")
    time.sleep(0.3)

print(f"\n[3] Adding {len(all_courses)} courses to cart...")
ok = 0
fail = 0
for cid, ctext, dept_id, dept_code in all_courses:
    time.sleep(0.2)
    resp = sess.post(BASE_URL + "/SelectTermDept/CourseList",
        data={"__RequestVerificationToken": token, "model.TermId": term_id,
              "model.DeptId": dept_id, "model.CourseId": cid,
              "model.TermName": "SPRING 26", "model.DeptName": dept_code,
              "model.CourseName": ctext},
        headers=AJAX_HEADERS, timeout=30)
    lower = resp.text.lower()
    if '"retval":true' in lower or "already been added" in lower:
        ok += 1
    else:
        fail += 1
        print(f"    FAIL: {ctext} => {resp.text[:150]}")

print(f"    OK: {ok}, FAIL: {fail}")

print(f"\n[4] Fetching materials page...")
resp = sess.get(BASE_URL + "/CourseMaterials", timeout=60)
print(f"    Status: {resp.status_code}, Length: {len(resp.text)}")

if "captcha" in resp.text.lower():
    print("    CAPTCHA DETECTED!")
elif "just a moment" in resp.text.lower()[:500]:
    print("    CLOUDFLARE CHALLENGE!")
else:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.find_all("div", class_=re.compile(r"Materials_Course"))
    print(f"    Found {len(cards)} course cards")
    found_depts = set()
    for card in cards:
        d = card.find("input", class_="ga4-course-department")
        if d:
            found_depts.add(d.get("value", ""))
    print(f"    Departments in results: {sorted(found_depts)}")

requests.post(FLARESOLVERR_URL, json={"cmd": "sessions.destroy", "session": "bulk"}, timeout=10)
