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

print("[1] Bootstrap...")
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

sess = requests.Session()
sess.cookies.update(cookies)
sess.headers.update({
    "User-Agent": ua,
    "Origin": BASE_URL,
    "Referer": BASE_URL + "/SelectTermDept",
})

print("[2] Terms...")
resp = sess.post(BASE_URL + "/SelectTermDept/Terms",
                 data={"__RequestVerificationToken": form_token},
                 headers=AJAX_HEADERS, timeout=30)
text = resp.text
if text.startswith('"') and text.endswith('"'):
    text = json.loads(text)
term_m = re.search(r'data-id\s*=\s*"ter-(\d+)"', text)
term_id = term_m.group(1) if term_m else None
print(f"    Term: {term_id}")

print("[3] Departments...")
resp = sess.post(BASE_URL + "/SelectTermDept/Department",
                 data={"__RequestVerificationToken": form_token, "termId": term_id},
                 headers=AJAX_HEADERS, timeout=30)
text = resp.text
if text.startswith('"') and text.endswith('"'):
    text = json.loads(text)
dept_matches = re.findall(r'data-id\s*=\s*"dpt-(\d+)"[^>]*>\s*(.*?)\s*<', text)
if dept_matches:
    dept_id, dept_code = dept_matches[0]
    print(f"    Dept: {dept_code} (id={dept_id})")
else:
    print(f"    NO depts found! Text: {text[:300]}")
    exit(1)

print("[4] Courses...")
resp = sess.post(BASE_URL + "/SelectTermDept/Courses",
                 data={"__RequestVerificationToken": form_token, "termId": term_id, "deptId": dept_id},
                 headers=AJAX_HEADERS, timeout=30)
text = resp.text
if text.startswith('"') and text.endswith('"'):
    text = json.loads(text)
course_matches = re.findall(r'data-id\s*=\s*"cou-(\d+)"[^>]*>\s*(.*?)\s*<', text)
if course_matches:
    course_id, course_text = course_matches[0]
    print(f"    Course: {course_text} (id={course_id})")
else:
    print(f"    NO courses found! Text: {text[:300]}")
    exit(1)

print(f"\n[5] Adding course to cart with REAL IDs...")
payload = {
    "__RequestVerificationToken": form_token,
    "model.TermId": term_id,
    "model.DeptId": dept_id,
    "model.CourseId": course_id,
    "model.TermName": "SPRING 26 (Order Now)",
    "model.DeptName": dept_code,
    "model.CourseName": course_text,
}
print(f"    Payload keys: {list(payload.keys())}")
print(f"    TermId={term_id}, DeptId={dept_id}, CourseId={course_id}")

time.sleep(0.5)
resp = sess.post(BASE_URL + "/SelectTermDept/CourseList",
                 data=payload, headers=AJAX_HEADERS, timeout=30)
print(f"    Status: {resp.status_code}")
print(f"    Response: '{resp.text}'")

success = '"retval":true' in resp.text.lower() or '"retval": true' in resp.text.lower()
print(f"    Success: {success}")

if success:
    print("\n[6] Fetching materials page...")
    time.sleep(0.5)
    resp = sess.get(BASE_URL + "/CourseMaterials", timeout=60)
    print(f"    Status: {resp.status_code}, Length: {len(resp.text)}")

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.find_all("div", class_=re.compile(r"Materials_Course"))
    print(f"    Found {len(cards)} course cards")

    for card in cards[:3]:
        dept_inp = card.find("input", class_="ga4-course-department")
        course_inp = card.find("input", class_="ga4-course-courseNumber")
        isbn_inp = card.find("input", class_="ga4-book-isbn")
        print(f"    Card: dept={dept_inp.get('value') if dept_inp else '?'}, "
              f"course={course_inp.get('value') if course_inp else '?'}, "
              f"isbn={isbn_inp.get('value') if isbn_inp else 'N/A'}")
