#!/usr/bin/env python3
import json
import re
import requests
import time

BASE_URL = "https://www.mystcstore.com"
FLARESOLVERR_URL = "http://localhost:8191/v1"
AJAX_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded",
}

print("[1] Bootstrapping via FlareSolverr...")
resp = requests.post(FLARESOLVERR_URL, json={
    "cmd": "request.get",
    "url": BASE_URL + "/SelectTermDept",
    "maxTimeout": 60000,
})
data = resp.json()
sol = data["solution"]
html = sol.get("response", "")
ua = sol.get("userAgent", "")
cookies = {}
for c in sol.get("cookies", []):
    if c.get("name"):
        cookies[c["name"]] = c["value"]

m = re.search(r'name="__RequestVerificationToken".*?value="([^"]+)"', html)
form_token = m.group(1) if m else ""

print(f"    Token: {form_token[:30]}...")
print(f"    Cookies: {list(cookies.keys())}")
print(f"    UA: {ua[:60]}...")

sess = requests.Session()
sess.cookies.update(cookies)
sess.headers.update({
    "User-Agent": ua,
    "Origin": BASE_URL,
    "Referer": BASE_URL + "/SelectTermDept",
})

print("\n[2] Fetching terms...")
resp = sess.post(BASE_URL + "/SelectTermDept/Terms",
                 data={"__RequestVerificationToken": form_token},
                 headers=AJAX_HEADERS, timeout=30)
print(f"    Status: {resp.status_code}, Length: {len(resp.text)}")
print(f"    Response: {resp.text[:500]}")

term_m = re.search(r'data-id="ter-(\d+)"', resp.text)
if not term_m:
    try:
        text = json.loads(resp.text)
        term_m = re.search(r'data-id="ter-(\d+)"', text)
    except:
        pass
term_id = term_m.group(1) if term_m else None
print(f"    Term ID: {term_id}")

print("\n[3] Fetching departments...")
resp = sess.post(BASE_URL + "/SelectTermDept/Department",
                 data={"__RequestVerificationToken": form_token, "termId": term_id},
                 headers=AJAX_HEADERS, timeout=30)
print(f"    Status: {resp.status_code}, Length: {len(resp.text)}")
text = resp.text
try:
    text = json.loads(text)
except:
    pass
dept_m = re.search(r'data-id="dpt-(\d+)"', text)
dept_id = dept_m.group(1) if dept_m else None
dept_name_m = re.search(r'data-id="dpt-\d+"[^>]*>(.*?)<', text)
dept_name = dept_name_m.group(1).strip() if dept_name_m else None
print(f"    First dept: {dept_name} (id={dept_id})")

print("\n[4] Fetching courses for first dept...")
resp = sess.post(BASE_URL + "/SelectTermDept/Courses",
                 data={"__RequestVerificationToken": form_token, "termId": term_id, "deptId": dept_id},
                 headers=AJAX_HEADERS, timeout=30)
print(f"    Status: {resp.status_code}, Length: {len(resp.text)}")
text = resp.text
try:
    text = json.loads(text)
except:
    pass
course_m = re.search(r'data-id="cou-(\d+)"', text)
course_id = course_m.group(1) if course_m else None
course_name_m = re.search(r'data-id="cou-\d+"[^>]*>(.*?)<', text)
course_text = course_name_m.group(1).strip() if course_name_m else None
print(f"    First course: {course_text} (id={course_id})")

print("\n[5] Adding course to cart (CourseList)...")
payload = {
    "__RequestVerificationToken": form_token,
    "model.TermId": term_id,
    "model.DeptId": dept_id,
    "model.CourseId": course_id,
    "model.TermName": "SPRING 26 (Order Now)",
    "model.DeptName": dept_name,
    "model.CourseName": course_text,
}
print(f"    Payload: {json.dumps(payload, indent=2)}")
time.sleep(0.5)
resp = sess.post(BASE_URL + "/SelectTermDept/CourseList",
                 data=payload, headers=AJAX_HEADERS, timeout=30)
print(f"    Status: {resp.status_code}")
print(f"    Headers: {dict(resp.headers)}")
print(f"    Response ({len(resp.text)} chars): {resp.text[:500]}")

if '"retval":true' in resp.text.lower() or '"retval": true' in resp.text.lower():
    print("\n    SUCCESS! Course added to cart.")

    print("\n[6] Fetching CourseMaterials page...")
    time.sleep(0.5)
    resp = sess.get(BASE_URL + "/CourseMaterials", timeout=60)
    print(f"    Status: {resp.status_code}, Length: {len(resp.text)}")
    print(f"    First 500 chars: {resp.text[:500]}")
else:
    print(f"\n    FAILED. Response doesn't contain retval:true")
    print(f"    Full response: {resp.text}")
