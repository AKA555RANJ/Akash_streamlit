import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

SCHOOL_NAME = "howard_community_college"
SCHOOL_ID   = "3039673"
PORTAL_ID   = 68
STORE_HOME  = "https://howardcc.slingshotedu.com/buy-books"
API_BASE    = f"https://portalapi.slingshotedu.com/app-rest/portal/v1/{PORTAL_ID}"

REQUEST_DELAY = 0.5

ADOPTION_MAP = {
    "REQ": "Required",
    "REC": "Recommended",
    "OPT": "Optional",
    "CHO": "Choose One",
    "ALT": "Alternate",
}

CSV_FIELDS = [
    "source_url", "school_id", "department_code", "course_code", "course_title",
    "section", "section_instructor", "term", "isbn", "title", "author",
    "material_adoption_code", "crawled_on", "updated_on",
]

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")

def make_session():
    sess = requests.Session()
    sess.headers.update({
        "Accept":          "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin":          "https://howardcc.slingshotedu.com",
        "Referer":         STORE_HOME + "/",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    })
    return sess

def api_get(sess, endpoint, params=None, retries=3):
    url = f"{API_BASE}/{endpoint}"
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, params=params, timeout=30)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", []) if isinstance(data, dict) else data
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] api_get {endpoint} attempt {attempt + 1}: {e}", flush=True)
                time.sleep(3 * (attempt + 1))
            else:
                raise
    return []

def fetch_terms(sess):
    print("[*] Fetching terms...")
    results = api_get(sess, "catalog/term")
    terms = [t for t in results if t.get("active") and t.get("webSelling")]
    print(f"    Found {len(terms)} active/web-selling terms")
    for t in terms:
        print(f"      {t['id']}: {t['displayName']}")
    return terms

def fetch_departments(sess, term_id):
    return api_get(sess, "catalog/department", {"termId": term_id})

def fetch_courses(sess, term_id, dept_id):
    results = api_get(sess, "catalog/course",
                      {"termId": term_id, "departmentId": dept_id})
    if not results:

        results = api_get(sess, "catalog/course", {"departmentId": dept_id})
    return [c for c in results if c.get("active", True)]

def fetch_sections(sess, term_id, course_id):
    results = api_get(sess, "catalog/section",
                      {"termId": term_id, "courseId": course_id})
    if not results:

        results = api_get(sess, "catalog/section", {"courseId": course_id})
    return [s for s in results
            if s.get("active", True) and s.get("showOnPortal", True)]

def fetch_listings(sess, section_id):
    return api_get(sess, "catalog/listing", {"sectionId": section_id})

def normalize_term(s):
    s = (s or "").strip()
    s = re.sub(r'\s*-\s*Howard\b.*$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s*\(.*?\)\s*', ' ', s).strip()
    return s.upper()

def fmt(code):
    code = (code or "").strip()
    return f"|{code}" if code and not code.startswith("|") else code

def parse_course_num(course_code_str):
    if "-" in course_code_str:
        return course_code_str.split("-", 1)[-1]
    return course_code_str

def parse_listings(listings, source_url, dept_code, course_code_str, course_title,
                   section_code, term_name, section_data):
    base = {
        "department_code":    dept_code,
        "course_code":        fmt(parse_course_num(course_code_str)),
        "course_title":       course_title,
        "section":            fmt(section_code),
        "section_instructor": "",
        "term":               normalize_term(term_name),
        "source_url":         source_url,
    }

    if section_data.get("noTextRequired"):
        return [{**base, "isbn": "", "title": "", "author": "",
                 "material_adoption_code": "This course does not require any course materials"}]

    rows = []
    for listing in listings:
        title_obj = listing.get("title") or {}
        isbn      = str(title_obj.get("isbn", "")).replace("-", "").strip()
        title     = title_obj.get("title", "") or ""
        author    = title_obj.get("author", "") or ""
        req       = (listing.get("required") or "").strip().upper()
        adoption  = ADOPTION_MAP.get(req, req) if req else "Required"

        if isbn or title:
            rows.append({**base, "isbn": isbn, "title": title, "author": author,
                         "material_adoption_code": adoption})

    if not rows:
        rows.append({**base, "isbn": "", "title": "", "author": "",
                     "material_adoption_code": "This course does not require any course materials"})
    return rows

def append_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    new_file = not os.path.exists(filepath) or os.path.getsize(filepath) == 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)

def get_scraped_keys(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return {(r.get("term", ""), r.get("department_code", ""),
                 r.get("course_code", ""), r.get("section", ""))
                for r in csv.DictReader(f)}

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys = get_scraped_keys(CSV_PATH)
    if done_keys:
        print(f"[*] {len(done_keys)} combos already scraped, resuming.")

    sess = make_session()
    terms = fetch_terms(sess)
    if not terms:
        print("[!] No terms found. Exiting.")
        return

    total_rows   = 0
    debug_saved  = False

    for term in terms:
        term_id   = term["id"]
        term_name = term["displayName"]
        print(f"\n[*] Term: {term_name} ({term_id})")

        depts = fetch_departments(sess, term_id)
        if not depts:
            print("    No departments found.")
            continue
        print(f"    {len(depts)} departments")

        for dept in tqdm(depts, desc=f"  {normalize_term(term_name)}"):
            dept_id   = dept["id"]
            dept_code = dept["code"]

            try:
                courses = fetch_courses(sess, term_id, dept_id)
            except Exception as e:
                tqdm.write(f"\n  [ERROR] fetch_courses {dept_code}: {e}")
                continue

            dept_rows = 0
            for course in courses:
                course_id    = course["id"]
                course_code  = course["code"]
                course_title = course.get("name", "")

                try:
                    sections = fetch_sections(sess, term_id, course_id)
                except Exception as e:
                    tqdm.write(f"\n  [ERROR] fetch_sections {dept_code}/{course_code}: {e}")
                    continue

                for section in sections:
                    section_id   = section["id"]
                    section_code = section["code"]

                    check_key = (
                        normalize_term(term_name),
                        dept_code,
                        fmt(parse_course_num(course_code)),
                        fmt(section_code),
                    )
                    if check_key in done_keys:
                        continue

                    source_url = f"{API_BASE}/catalog/listing?sectionId={section_id}"

                    try:
                        listings = fetch_listings(sess, section_id)
                    except Exception as e:
                        tqdm.write(f"\n  [ERROR] fetch_listings {dept_code}/{course_code}/{section_code}: {e}")
                        listings = []

                    if not debug_saved and listings:
                        debug_path = os.path.join(OUTPUT_DIR, "debug_listings.json")
                        os.makedirs(OUTPUT_DIR, exist_ok=True)
                        with open(debug_path, "w", encoding="utf-8") as df:
                            json.dump(listings, df, indent=2, ensure_ascii=False)
                        tqdm.write(f"\n    [DEBUG] First listing saved → {debug_path}")
                        debug_saved = True

                    rows = parse_listings(
                        listings, source_url,
                        dept_code, course_code, course_title,
                        section_code, term_name, section
                    )
                    for row in rows:
                        row["school_id"]  = SCHOOL_ID
                        row["crawled_on"] = crawled_on
                        row["updated_on"] = crawled_on

                    append_csv(rows, CSV_PATH)
                    dept_rows  += len(rows)
                    total_rows += len(rows)

            if dept_rows:
                tqdm.write(f"    [{dept_code}] +{dept_rows} rows (total: {total_rows})")

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE — {total_rows} rows written")
    print(f"CSV: {CSV_PATH}")
    if total_rows == 0:
        print("[!] No data written. Check debug_listings.json and API responses.")

if __name__ == "__main__":
    scrape(fresh="--fresh" in sys.argv)
