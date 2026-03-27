#!/usr/bin/env python3

import csv
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

SCHOOL_NAME = "santa_clara_university"
SCHOOL_ID = "2995749"
SOURCE_URL = "https://scu.studentstore.com"
BASE_API = "https://api.studentstore.com/webcomm-rest/catalog"
LOCATION_ID = "991027"

REQUEST_DELAY = 0.2
MAX_WORKERS = 5

CSV_FIELDS = [
    "source_url",
    "school_id",
    "department_code",
    "course_code",
    "course_title",
    "section",
    "section_instructor",
    "term",
    "isbn",
    "title",
    "author",
    "material_adoption_code",
    "crawled_on",
]

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; textbook-scraper/1.0)",
    "Accept": "application/json",
}

_csv_lock = threading.Lock()
_total_rows = 0
_rows_lock = threading.Lock()

def api_get(url, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
            else:
                raise

def fetch_terms():
    data = api_get(f"{BASE_API}/terms?location-id={LOCATION_ID}")
    return data if isinstance(data, list) else []

def fetch_departments(term_id):
    data = api_get(f"{BASE_API}/departments?term-id={term_id}")
    return data if isinstance(data, list) else []

def fetch_courses(dept_id):
    data = api_get(f"{BASE_API}/courses?department-id={dept_id}")
    return data if isinstance(data, list) else []

def fetch_sections(course_id):
    data = api_get(f"{BASE_API}/sections?course-id={course_id}")
    return data if isinstance(data, list) else []

def fetch_adoptions(section_id):
    data = api_get(f"{BASE_API}/adoptions?section-id={section_id}")
    return data if isinstance(data, list) else []

def append_csv(rows, filepath):
    if not rows:
        return
    with _csv_lock:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
        with open(filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerows(rows)

def get_scraped_departments(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    scraped = set()
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dept = row.get("department_code", "").strip()
            if dept:
                scraped.add(dept)
    return scraped

def process_department(dept, term_name, crawled_on):
    global _total_rows
    dept_id = dept.get("id")
    dept_code = dept.get("code", "")
    rows_written = 0

    try:
        courses = fetch_courses(dept_id)
    except Exception as e:
        tqdm.write(f"  [ERROR] fetch_courses dept={dept_code}: {e}")
        return 0

    for course in courses:
        course_id = course.get("id")
        course_num = course.get("code", "")
        course_title = course.get("name", "")
        course_code = f"|{course_num}".strip()

        try:
            sections = fetch_sections(course_id)
        except Exception as e:
            tqdm.write(f"  [ERROR] fetch_sections course={course_code}: {e}")
            continue

        for section in sections:
            section_id = section.get("id")
            section_code = section.get("code", "")
            instructor = section.get("instructorName", "") or ""
            books_required = section.get("booksRequired", True)
            books_loaded = section.get("booksLoaded", False)

            base_row = {
                "source_url": SOURCE_URL,
                "school_id": SCHOOL_ID,
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": course_title,
                "section": f"|{section_code}",
                "section_instructor": instructor,
                "term": term_name,
                "crawled_on": crawled_on,
            }

            rows = []

            if not books_required and books_loaded:
                rows.append({
                    **base_row,
                    "isbn": "",
                    "title": "",
                    "author": "",
                    "material_adoption_code": "This course does not require any course materials",
                })

            elif not books_loaded:
                rows.append({
                    **base_row,
                    "isbn": "",
                    "title": "",
                    "author": "",
                    "material_adoption_code": "This course does not require any course materials",
                })

            else:
                try:
                    adoptions = fetch_adoptions(section_id)
                except Exception as e:
                    tqdm.write(f"  [ERROR] fetch_adoptions section={section_id}: {e}")
                    continue

                for adoption in adoptions:
                    isbn = (adoption.get("productCode") or "").replace("-", "").strip()
                    rows.append({
                        **base_row,
                        "isbn": isbn,
                        "title": adoption.get("name", "") or "",
                        "author": adoption.get("author", "") or "",
                        "material_adoption_code": adoption.get("requiredStatus", "") or "",
                    })

            if rows:
                append_csv(rows, CSV_PATH)
                rows_written += len(rows)
                with _rows_lock:
                    _total_rows += len(rows)

    return rows_written

def scrape(fresh=False):
    global _total_rows
    _total_rows = 0
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_depts = get_scraped_departments(CSV_PATH)
    if done_depts:
        print(f"[*] {len(done_depts)} departments already scraped: {sorted(done_depts)}")
        print("[*] Will only scrape missing departments.")

    print("[*] Fetching terms...")
    terms = fetch_terms()
    print(f"    Found {len(terms)} terms: {[t.get('name') for t in terms]}")

    if not terms:
        print("[!] No terms found. Exiting.")
        return

    all_expected_depts = set()

    for term in terms:
        term_id = term.get("id")
        term_name = re.sub(r"\s*\(.*?\)\s*", "", term.get("name", "")).strip()
        print(f"\n[*] Processing term: {term_name} (id={term_id})")

        depts = fetch_departments(term_id)
        print(f"    Found {len(depts)} departments")

        if not depts:
            continue

        all_expected_depts.update(d.get("code", "") for d in depts)

        depts_to_scrape = [d for d in depts if d.get("code", "") not in done_depts]
        skipped = len(depts) - len(depts_to_scrape)
        if skipped:
            print(f"    Skipped {skipped} already-scraped departments")
        print(f"    Departments to scrape: {len(depts_to_scrape)} (workers={MAX_WORKERS})")

        if not depts_to_scrape:
            print("    Nothing to scrape for this term.")
            continue

        with tqdm(total=len(depts_to_scrape), desc=f"  Depts ({term_name})") as pbar:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(process_department, dept, term_name, crawled_on): dept
                    for dept in depts_to_scrape
                }
                for future in as_completed(futures):
                    dept = futures[future]
                    dept_code = dept.get("code", "")
                    try:
                        n = future.result()
                        tqdm.write(f"    [{dept_code}] +{n} rows (total: {_total_rows})")
                    except Exception as e:
                        tqdm.write(f"  [ERROR] dept={dept_code}: {e}")
                    pbar.update(1)

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"Total rows written: {_total_rows}")
    print(f"CSV: {CSV_PATH}")

    final_depts = get_scraped_departments(CSV_PATH)
    missing = all_expected_depts - final_depts
    if missing:
        print(f"\n[!] MISSING {len(missing)} departments: {sorted(missing)}")
        print("  Re-run without --fresh to scrape only these.")
    else:
        print(f"\n[OK] All {len(all_expected_depts)} departments scraped successfully!")

if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    scrape(fresh=fresh)
