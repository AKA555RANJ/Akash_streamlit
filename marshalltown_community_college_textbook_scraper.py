import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

BASE_URL   = "https://iavalley.vitalsource.com"
CAMPUS_ID  = "1"
SCHOOL_ID  = "3020618"
SCHOOL_NAME = "marshalltown_community_college"

CSV_FIELDS = [
    "source_url", "school_id", "department_code", "course_code", "course_title",
    "section", "section_instructor", "term", "isbn", "title", "author",
    "material_adoption_code", "crawled_on", "updated_on",
]

DEFAULT_DELAY = 0.4

def make_session():
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, */*",
        "Referer": BASE_URL + "/courses/select",
    })
    return sess

def api_get(sess, path, params=None, delay=DEFAULT_DELAY):
    time.sleep(delay)
    r = sess.get(BASE_URL + path, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def fetch_terms(sess):
    return api_get(sess, "/courses/terms", {"campus_id": CAMPUS_ID})

def fetch_departments(sess, term_id):
    return api_get(sess, "/courses/departments", {"campus": CAMPUS_ID, "term": term_id})

def fetch_courses(sess, term_id, dept_id):
    return api_get(sess, "/courses/courses", {"campus": CAMPUS_ID, "term": term_id, "department": dept_id})

def fetch_sections(sess, term_id, dept_id, course_id):
    return api_get(sess, "/courses/sections", {"campus": CAMPUS_ID, "term": term_id, "department": dept_id, "course": course_id})

def fetch_materials(sess, term_id, term_name, dept_id, course_id, section_id, delay=DEFAULT_DELAY):
    time.sleep(delay)
    url = BASE_URL + "/courses"
    params = {
        "campus_id": CAMPUS_ID,
        "department_id": dept_id,
        "course_id": course_id,
        "section_id": section_id,
        "term_id": term_id,
        "term_name": term_name,
    }
    r = sess.get(url, params=params, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    books = []
    for script in soup.find_all("script"):
        txt = script.string or ""
        if '"CourseMaterials"' not in txt and '"assetProps"' not in txt:
            continue
        try:
            data = json.loads(txt)
            if not isinstance(data, dict):
                continue
            if data.get("name") not in ("CourseMaterials",):
                continue
            props = data.get("props", {})
            asset = props.get("assetProps", {})
            isbn = re.sub(r"[^0-9X]", "", (asset.get("canonicalIsbn") or "").upper())
            title  = asset.get("title", "") or ""
            author = asset.get("author", "") or ""
            required = props.get("hasRequiredStatus", False)
            adoption = "Required Material(s)" if required else "Optional Material(s)"
            if title:
                books.append({"isbn": isbn, "title": title, "author": author,
                              "material_adoption_code": adoption,
                              "source_url": r.url})
        except Exception:
            continue
    return books

def get_scraped_keys(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return {(r.get("term",""), r.get("department_code",""), r.get("course_code",""), r.get("section",""))
                for r in csv.DictReader(f)}

def append_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    new_file = not os.path.exists(filepath) or os.path.getsize(filepath) == 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)

def scrape(csv_path, fresh=False, term_filter=None):
    if fresh and os.path.exists(csv_path):
        os.remove(csv_path)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys = get_scraped_keys(csv_path)
    if done_keys:
        print(f"[*] {len(done_keys)} section combos already scraped — resuming.")

    sess = make_session()
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    total = 0

    terms = fetch_terms(sess)
    print(f"[*] Terms: {[(t['id'], t['name']) for t in terms]}")

    for term in terms:
        term_id   = term["id"]
        term_name = term["name"].upper()
        if term_filter and term_filter.lower() not in term_name.lower():
            print(f"[*] Skipping: {term_name}")
            continue

        print(f"\n[*] Term: {term_name} ({term_id})")
        try:
            depts = fetch_departments(sess, term_id)
        except Exception as e:
            print(f"    [!] No departments ({e}) — skipping term.")
            continue
        print(f"    {len(depts)} departments")

        for dept in tqdm(depts, desc=f"  {term_name}"):
            dept_id   = dept["id"]
            dept_code = dept["name"]

            try:
                courses = fetch_courses(sess, term_id, dept_id)
            except Exception as e:
                tqdm.write(f"  [WARN] {dept_code} fetch_courses: {e}")
                continue

            for course in courses:
                course_id   = course["id"]
                course_num  = course["name"]
                course_code = "|" + course_num

                try:
                    sections = fetch_sections(sess, term_id, dept_id, course_id)
                except Exception as e:
                    tqdm.write(f"  [WARN] {dept_code} {course_num} fetch_sections: {e}")
                    continue

                for sec in sections:
                    section_id   = sec["id"]
                    section_name = "|" + sec["name"]
                    instructor   = " ".join((sec.get("instructor") or "").split())
                    key = (term_name, dept_code, course_code, section_name)
                    if key in done_keys:
                        continue

                    base = {
                        "school_id": SCHOOL_ID,
                        "department_code": dept_code,
                        "course_code": course_code,
                        "course_title": "",
                        "section": section_name,
                        "section_instructor": instructor,
                        "term": term_name,
                        "crawled_on": crawled_on,
                        "updated_on": crawled_on,
                    }

                    try:
                        books = fetch_materials(sess, term_id, term["name"], dept_id, course_id, section_id)
                    except Exception as e:
                        tqdm.write(f"  [WARN] section {section_id}: {e}")
                        books = []

                    if not books:
                        row = {**base, "source_url": f"{BASE_URL}/courses?section_id={section_id}&term_id={term_id}",
                               "isbn": "", "title": "", "author": "", "material_adoption_code": ""}
                        append_csv([row], csv_path)
                        total += 1
                    else:
                        rows = [{**base, **b} for b in books]
                        append_csv(rows, csv_path)
                        total += len(rows)

    return total

def main():
    parser = argparse.ArgumentParser(description="Scrape textbooks from Marshalltown CC (VitalSource).")
    parser.add_argument("--fresh",       action="store_true")
    parser.add_argument("--term-filter", default=None)
    args = parser.parse_args()

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", f"{SCHOOL_NAME}__{SCHOOL_ID}__bks")
    csv_path   = os.path.join(output_dir, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")
    print(f"[*] Output: {csv_path}")

    total = scrape(csv_path, fresh=args.fresh, term_filter=args.term_filter)
    print(f"\n[+] Done — {total} rows written to {csv_path}")

if __name__ == "__main__":
    main()
