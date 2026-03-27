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

term_id = "271713"

print("[2] Get ACCT dept...")
resp = sess.post(BASE_URL + "/SelectTermDept/Department",
                 data={"__RequestVerificationToken": form_token, "termId": term_id},
                 headers=AJAX_HEADERS, timeout=30)
text = resp.text
if text.startswith('"') and text.endswith('"'):
    text = json.loads(text)
dept_m = re.search(r'data-id\s*=\s*"dpt-(\d+)"[^>]*>\s*ACCT\s*<', text)
dept_id = dept_m.group(1) if dept_m else None
print(f"    ACCT dept_id: {dept_id}")

print("[3] Get ACCT courses...")
resp = sess.post(BASE_URL + "/SelectTermDept/Courses",
                 data={"__RequestVerificationToken": form_token, "termId": term_id, "deptId": dept_id},
                 headers=AJAX_HEADERS, timeout=30)
text = resp.text
if text.startswith('"') and text.endswith('"'):
    text = json.loads(text)
course_matches = re.findall(r'data-id\s*=\s*"cou-(\d+)"[^>]*>\s*(.*?)\s*<', text)
print(f"    Found {len(course_matches)} courses:")
for cid, ctext in course_matches:
    print(f"      {cid}: {ctext}")

print("\n[4] Testing CourseList for each course...")
for cid, ctext in course_matches:
    time.sleep(0.3)
    payload = {
        "__RequestVerificationToken": form_token,
        "model.TermId": term_id,
        "model.DeptId": dept_id,
        "model.CourseId": cid,
        "model.TermName": "SPRING 26 (Order Now)",
        "model.DeptName": "ACCT",
        "model.CourseName": ctext,
    }
    resp = sess.post(BASE_URL + "/SelectTermDept/CourseList",
                     data=payload, headers=AJAX_HEADERS, timeout=30)
    result = resp.text
    success = '"retval":true' in result.lower()
    print(f"    {cid} ({ctext[:40]}): {'OK' if success else 'FAIL'} — {result[:150]}")

print("\n[5] Fetching materials...")
time.sleep(0.5)
resp = sess.get(BASE_URL + "/CourseMaterials", timeout=60)
print(f"    Status: {resp.status_code}, Length: {len(resp.text)}")

from bs4 import BeautifulSoup
soup = BeautifulSoup(resp.text, "html.parser")
cards = soup.find_all("div", class_=re.compile(r"Materials_Course"))
print(f"    Found {len(cards)} course cards")
for card in cards:
    dept_inp = card.find("input", class_="ga4-course-department")
    course_inp = card.find("input", class_="ga4-course-courseNumber")
    sect_inp = card.find("input", class_="ga4-course-sectionNumber")
    isbn_inp = card.find("input", class_="ga4-book-isbn")
    no_mat = card.find(class_=re.compile(r"No_Material"))
    print(f"    {dept_inp.get('value','?') if dept_inp else '?'} "
          f"{course_inp.get('value','?') if course_inp else '?'} "
          f"Sec:{sect_inp.get('value','?') if sect_inp else '?'} "
          f"ISBN:{isbn_inp.get('value','N/A') if isbn_inp else 'N/A'} "
          f"NoMat:{'Yes' if no_mat else 'No'}")
