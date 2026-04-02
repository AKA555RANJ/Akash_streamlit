#!/usr/bin/env python3
"""
Cape Fear Community College Bookstore Textbook Scraper
Platform: bkstr.com (Follett) — svc.bkstr.com REST API
URL: https://www.bkstr.com/capefearstore/shop/textbooks-and-course-materials

Uses Playwright (headless=False) so that PerimeterX sensor data is generated
inside the live Chrome session. All API calls — including the POST to
courseMaterial/results — are executed via page.evaluate() (browser fetch),
which keeps the PX session intact and avoids 403 blocks.
"""

import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

SCHOOL_NAME = "cape_fear_community_college"
SCHOOL_ID   = "3055607"
STORE_SLUG  = "capefearstore"
BASE_URL    = "https://www.bkstr.com"
SVC_URL     = "https://svc.bkstr.com"
STORE_HOME  = f"{BASE_URL}/{STORE_SLUG}/shop/textbooks-and-course-materials"

REQUEST_DELAY = 1.2   # seconds between API calls

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



def page_get(page, url, retries=3):
    """Send a GET request via Playwright's APIRequestContext.

    page.request uses the browser's cookie store (so _px3 and all bkstr.com
    cookies are included) without navigating the page away from the SPA.
    """
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = page.request.get(url, headers={
                "Accept":          "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer":         STORE_HOME,
                "Origin":          BASE_URL,
            })
            if resp.status == 403:
                print(f"  [WARN] 403 on GET {url} (attempt {attempt+1})")
                if attempt < retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Blocked GET {url}")
            body = resp.text().strip()
            if not body:
                return {}
            return json.loads(body)
        except json.JSONDecodeError:
            print(f"  [WARN] Non-JSON GET (attempt {attempt+1}): {body[:200]}")
            if attempt == retries - 1:
                return {}
            time.sleep(2)
        except RuntimeError:
            raise
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] page_get attempt {attempt+1}: {e}")
                time.sleep(3 * (attempt + 1))
            else:
                raise
    return {}


def page_post(page, url, payload, retries=3):
    """POST JSON via Playwright's APIRequestContext (same cookie store as browser)."""
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = page.request.post(url,
                data=json.dumps(payload),
                headers={
                    "Content-Type":  "application/json",
                    "Accept":        "application/json, text/plain, */*",
                    "Referer":       STORE_HOME,
                    "Origin":        BASE_URL,
                },
            )
            if resp.status == 403:
                print(f"  [WARN] 403 on POST {url} (attempt {attempt+1})")
                if attempt < retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Blocked POST {url}")
            body = resp.text().strip()
            if not body:
                return {}
            return json.loads(body)
        except json.JSONDecodeError:
            print(f"  [WARN] Non-JSON POST (attempt {attempt+1}): {body[:200]}")
            if attempt == retries - 1:
                return {}
            time.sleep(2)
        except RuntimeError:
            raise
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] page_post attempt {attempt+1}: {e}")
                time.sleep(3 * (attempt + 1))
            else:
                raise
    return {}


# ---------------------------------------------------------------------------
# BKStr API calls
# ---------------------------------------------------------------------------

def fetch_store_config(page):
    print("[*] Fetching store config...")
    url = f"{SVC_URL}/store/config?storeName={STORE_SLUG}"
    data = page_get(page, url)
    store_id = str(data.get("storeId", ""))
    catalog_id = ""
    for cat in data.get("defaultCatalog", []):
        catalog_id = cat.get("catalogIdentifier", {}).get("uniqueID", "")
        if catalog_id:
            break
    if not catalog_id:
        catalog_id = str(data.get("catalogId", ""))
    print(f"    storeId={store_id}, catalogId={catalog_id}")
    return store_id, catalog_id


def fetch_terms(page, store_id):
    print("[*] Fetching terms...")
    url = f"{SVC_URL}/courseMaterial/info?storeId={store_id}"
    data = page_get(page, url)
    terms = []
    for campus in data.get("finalData", {}).get("campus", []):
        for program in campus.get("program", []):
            program_id = program.get("programId", "")
            for term in program.get("term", []):
                terms.append({
                    "termId":    term.get("termId", ""),
                    "termName":  term.get("termName", ""),
                    "programId": program_id,
                })
    print(f"    Found {len(terms)} terms")
    for t in terms:
        print(f"      {t['termId']}: {t['termName']} (program={t['programId']})")
    return terms


def fetch_courses(page, store_id, term_id, program_id):
    qs = f"storeId={store_id}&termId={term_id}"
    if program_id:
        qs += f"&programId={program_id}"
    url = f"{SVC_URL}/courseMaterial/courses?{qs}"
    data = page_get(page, url)
    rows = []
    for div in data.get("finalDDCSData", {}).get("division", []):
        for dept in div.get("department", []):
            dep_name = dept.get("depName", "")
            for course in dept.get("course", []):
                course_name = course.get("courseName", "")
                for section in course.get("section", []):
                    rows.append({
                        "department": dep_name,
                        "course":     course_name,
                        "section":    section.get("sectionName", ""),
                    })
    return rows


def fetch_results(page, store_id, catalog_id, term_id, program_id,
                  dept, course, section):
    url     = f"{SVC_URL}/courseMaterial/results"
    payload = {
        "storeId":     store_id,
        "langId":      "-1",
        "catalogId":   catalog_id,
        "requestType": "DDCSBrowse",
        "courses": [{
            "divisionName":    "",
            "departmentName":  dept,
            "courseName":      course,
            "sectionName":     section,
        }],
        "programId": program_id,
        "termId":    term_id,
    }
    return page_post(page, url, payload)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def normalize_term(s):
    return re.sub(r'\s*\(.*?\)\s*', ' ', s).strip().upper() if s else ""


def fmt(code):
    code = (code or "").strip()
    return f"|{code}" if code and not code.startswith("|") else code


def parse_results(data, source_url, dept, course, section, term_name):
    rows = []
    results_list = data.get("courseMaterialResultsList", [])

    if not results_list:
        rows.append({"department_code": dept, "course_code": fmt(course),
                     "course_title": "", "section": fmt(section),
                     "section_instructor": "", "term": normalize_term(term_name),
                     "isbn": "", "title": "", "author": "",
                     "material_adoption_code": "This course does not require any course materials",
                     "source_url": source_url})
        return rows

    for result in results_list:
        course_title = result.get("courseName", "")
        instructor   = result.get("instructor", "")
        materials    = result.get("courseMaterialList") or result.get("materialList") or []

        if not materials:
            rows.append({"department_code": dept, "course_code": fmt(course),
                         "course_title": course_title, "section": fmt(section),
                         "section_instructor": instructor,
                         "term": normalize_term(term_name),
                         "isbn": "", "title": "", "author": "",
                         "material_adoption_code": "This course does not require any course materials",
                         "source_url": source_url})
            continue

        for mat in materials:
            isbn     = str(mat.get("isbn", mat.get("isbn13", ""))).replace("-", "").strip()
            title    = mat.get("title",  mat.get("bookTitle",  "")) or ""
            author   = mat.get("author", mat.get("bookAuthor", "")) or ""
            adoption = mat.get("materialStatus", mat.get("adoptionStatus",
                       mat.get("requiredStatus", mat.get("status", "")))) or ""

            adoption_lc = adoption.lower()
            if adoption_lc in ("required", "true", "yes", "r"):
                adoption = "Required"
            elif adoption_lc in ("recommended",):
                adoption = "Recommended"
            elif adoption_lc in ("optional", "o"):
                adoption = "Optional"
            elif adoption_lc in ("go to class first", "goclass"):
                adoption = "Go to class first"
            elif not adoption:
                adoption = "Required"

            if isbn or title:
                rows.append({"department_code": dept, "course_code": fmt(course),
                             "course_title": course_title, "section": fmt(section),
                             "section_instructor": instructor,
                             "term": normalize_term(term_name),
                             "isbn": isbn, "title": title, "author": author,
                             "material_adoption_code": adoption,
                             "source_url": source_url})

    if not rows:
        rows.append({"department_code": dept, "course_code": fmt(course),
                     "course_title": "", "section": fmt(section),
                     "section_instructor": "", "term": normalize_term(term_name),
                     "isbn": "", "title": "", "author": "",
                     "material_adoption_code": "This course does not require any course materials",
                     "source_url": source_url})
    return rows


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

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
        return {
            (r.get("term",""), r.get("department_code",""),
             r.get("course_code",""), r.get("section",""))
            for r in csv.DictReader(f)
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys = get_scraped_keys(CSV_PATH)
    if done_keys:
        print(f"[*] {len(done_keys)} combos already scraped, resuming.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx     = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()

        # -------------------------------------------------------------------
        # Bootstrap: visit SPA so PX can fingerprint the browser session
        # -------------------------------------------------------------------
        print(f"[*] Loading SPA: {STORE_HOME}")
        page.goto(STORE_HOME, wait_until="networkidle", timeout=90000)
        # Extra dwell time so PX sensor data fully initialises
        time.sleep(8)

        # Save bootstrap HTML for debugging
        with open(os.path.join(OUTPUT_DIR, "debug_bootstrap.html"), "w", encoding="utf-8") as f:
            f.write(page.content())
        print("[*] SPA loaded and PX session ready.")

        # -------------------------------------------------------------------
        # API calls — all via page.evaluate() so they run inside the live
        # Chrome session and carry valid PX tokens automatically
        # -------------------------------------------------------------------
        store_id, catalog_id = fetch_store_config(page)
        if not store_id:
            print("[!] Could not get store config. Check debug_bootstrap.html.")
            browser.close()
            return

        terms = fetch_terms(page, store_id)
        if not terms:
            print("[!] No terms found.")
            browser.close()
            return

        total_rows  = 0
        debug_saved = False

        for term in terms:
            term_id    = term["termId"]
            term_name  = term["termName"]
            program_id = term["programId"]

            print(f"\n[*] Term: {term_name} ({term_id})")
            course_list = fetch_courses(page, store_id, term_id, program_id)
            if not course_list:
                print("    No courses found.")
                continue

            dept_groups = {}
            for c in course_list:
                dept_groups.setdefault(c["department"], []).append(c)

            print(f"    {len(dept_groups)} departments, {len(course_list)} course/sections")

            for dept_code, courses in tqdm(dept_groups.items(), desc=f"  {term_name}"):
                dept_rows = 0
                for entry in courses:
                    course_code  = entry["course"]
                    section_code = entry["section"]
                    check_key = (normalize_term(term_name), dept_code,
                                 fmt(course_code), fmt(section_code))
                    if check_key in done_keys:
                        continue

                    source_url = (
                        f"{SVC_URL}/courseMaterial/results"
                        f"?storeId={store_id}&termId={term_id}"
                        f"&dept={dept_code}&course={course_code}&section={section_code}"
                    )

                    try:
                        data = fetch_results(page, store_id, catalog_id,
                                             term_id, program_id,
                                             dept_code, course_code, section_code)
                    except Exception as e:
                        tqdm.write(f"\n  [ERROR] {dept_code}/{course_code}/{section_code}: {e}")
                        data = {}

                    if not debug_saved and data:
                        with open(os.path.join(OUTPUT_DIR, "debug_results.json"),
                                  "w", encoding="utf-8") as df:
                            json.dump(data, df, indent=2, ensure_ascii=False)
                        tqdm.write(f"\n    [DEBUG] First result saved to debug_results.json")
                        debug_saved = True

                    rows = parse_results(data, source_url,
                                         dept_code, course_code, section_code, term_name)
                    for row in rows:
                        row["school_id"]   = SCHOOL_ID
                        row["crawled_on"]  = crawled_on
                        row["updated_on"]  = crawled_on

                    append_csv(rows, CSV_PATH)
                    dept_rows  += len(rows)
                    total_rows += len(rows)

                if dept_rows:
                    tqdm.write(f"    [{dept_code}] +{dept_rows} rows (total: {total_rows})")

        browser.close()

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE — {total_rows} rows written")
    print(f"CSV: {CSV_PATH}")
    if total_rows == 0:
        print("[!] No data. Check debug_bootstrap.html and debug_results.json.")


if __name__ == "__main__":
    scrape(fresh="--fresh" in sys.argv)
