#!/usr/bin/env python3
"""
Cape Fear Community College Bookstore Textbook Scraper
Platform: bkstr.com (Follett) — svc.bkstr.com REST API
URL: https://www.bkstr.com/capefearstore/shop/textbooks-and-course-materials

Two-page Playwright approach to bypass PerimeterX:
  page1 — stays on STORE_HOME (SPA) forever; used for POST via page1.evaluate()
           so PX sensor data (_pxde) is always live.
  page2 — used for GET navigations to svc.bkstr.com; Chrome carries bkstr.com
           cookies from the shared BrowserContext, giving valid TLS fingerprint.

Both pages share one BrowserContext so .bkstr.com cookies (incl. _px3) are shared.
"""

import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

SCHOOL_NAME = "cape_fear_community_college"
SCHOOL_ID   = "3055607"
STORE_SLUG  = "capefearstore"
BASE_URL    = "https://www.bkstr.com"
SVC_URL     = "https://svc.bkstr.com"
STORE_HOME  = f"{BASE_URL}/{STORE_SLUG}/shop/textbooks-and-course-materials"

REQUEST_DELAY = 1.5   # seconds between API calls

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


# ---------------------------------------------------------------------------
# Xvfb helper — start a virtual display when DISPLAY is not set (e.g. Codespace)
# ---------------------------------------------------------------------------

def start_xvfb():
    """Start Xvfb on :99 if we are in a headless environment (no $DISPLAY)."""
    if os.environ.get("DISPLAY"):
        return None  # already have a display
    try:
        proc = subprocess.Popen(
            ["Xvfb", ":99", "-screen", "0", "1280x800x24"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.environ["DISPLAY"] = ":99"
        time.sleep(1.5)  # give Xvfb time to start
        print("[*] Xvfb started on :99 (headless display)")
        return proc
    except FileNotFoundError:
        print("[!] Xvfb not found — will try headless=True instead.")
        return None


# ---------------------------------------------------------------------------
# GET via page2.goto() — Chrome navigates, cookies & TLS fingerprint intact
# ---------------------------------------------------------------------------

def page2_get(page2, url, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = page2.goto(url, wait_until="domcontentloaded", timeout=30000)
            if resp is None:
                raise RuntimeError("page2.goto returned None")
            status = resp.status
            if status == 403:
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
                print(f"  [WARN] page2_get attempt {attempt+1}: {e}")
                time.sleep(3 * (attempt + 1))
            else:
                raise
    return {}


# ---------------------------------------------------------------------------
# POST via page1.evaluate() — runs fetch() inside the live SPA tab
# PX sensor data (_pxde) is fully populated because page1 never navigates away
# ---------------------------------------------------------------------------

def page1_post(page1, url, payload, retries=3):
    js = """
    async ([url, payload]) => {
        const resp = await fetch(url, {
            method: 'POST',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json, text/plain, */*'
            },
            body: JSON.stringify(payload)
        });
        return { status: resp.status, body: await resp.text() };
    }
    """
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            result = page1.evaluate(js, [url, payload])
            status = result.get("status", 0)
            body   = result.get("body", "").strip()
            if status == 403:
                print(f"  [WARN] 403 on POST {url} (attempt {attempt+1})")
                if attempt < retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Blocked POST {url}")
            if not body:
                return {}
            return json.loads(body)
        except json.JSONDecodeError:
            body_preview = result.get("body", "")[:200] if "result" in dir() else ""
            print(f"  [WARN] Non-JSON POST (attempt {attempt+1}): {body_preview}")
            if attempt == retries - 1:
                return {}
            time.sleep(2)
        except RuntimeError:
            raise
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] page1_post attempt {attempt+1}: {e}")
                time.sleep(3 * (attempt + 1))
            else:
                raise
    return {}


# ---------------------------------------------------------------------------
# BKStr API calls
# ---------------------------------------------------------------------------

def fetch_store_config(page2, store_id_hint=None):
    print("[*] Fetching store config...")
    url  = f"{SVC_URL}/store/config?storeName={STORE_SLUG}"
    data = page2_get(page2, url)
    store_id   = str(data.get("storeId", ""))
    catalog_id = ""
    for cat in data.get("defaultCatalog", []):
        catalog_id = cat.get("catalogIdentifier", {}).get("uniqueID", "")
        if catalog_id:
            break
    if not catalog_id:
        catalog_id = str(data.get("catalogId", ""))
    print(f"    storeId={store_id}, catalogId={catalog_id}")
    return store_id, catalog_id


def fetch_terms(page2, store_id):
    print("[*] Fetching terms...")
    url  = f"{SVC_URL}/courseMaterial/info?storeId={store_id}"
    data = page2_get(page2, url)
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


def fetch_courses(page2, store_id, term_id, program_id):
    qs  = f"storeId={store_id}&termId={term_id}"
    if program_id:
        qs += f"&programId={program_id}"
    url  = f"{SVC_URL}/courseMaterial/courses?{qs}"
    data = page2_get(page2, url)
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


def fetch_results(page1, store_id, catalog_id, term_id, program_id,
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
    return page1_post(page1, url, payload)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def normalize_term(s):
    return re.sub(r'\s*\(.*?\)\s*', ' ', s).strip().upper() if s else ""


def fmt(code):
    code = (code or "").strip()
    return f"|{code}" if code and not code.startswith("|") else code


def parse_results(data, source_url, dept, course, section, term_name):
    rows         = []
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
            (r.get("term", ""), r.get("department_code", ""),
             r.get("course_code", ""), r.get("section", ""))
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

    # Start virtual display if needed (Codespace / headless server)
    xvfb_proc = start_xvfb()
    use_headless = xvfb_proc is None and not os.environ.get("DISPLAY")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=use_headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )

        # page1: stays on STORE_HOME; used for POST via evaluate()
        # page2: used for GET navigations to svc.bkstr.com
        page1 = ctx.new_page()
        page2 = ctx.new_page()

        # -------------------------------------------------------------------
        # Bootstrap: visit SPA on page1 so PX sensor data fully initialises
        # -------------------------------------------------------------------
        print(f"[*] Loading SPA on page1: {STORE_HOME}")
        page1.goto(STORE_HOME, wait_until="networkidle", timeout=90000)
        time.sleep(10)  # let PX sensor data fully initialise

        with open(os.path.join(OUTPUT_DIR, "debug_bootstrap.html"), "w", encoding="utf-8") as f:
            f.write(page1.content())
        print("[*] SPA loaded — PX session ready on page1.")
        print("[*] page2 will handle GET navigations; page1 handles all POSTs.")

        # -------------------------------------------------------------------
        # GETs via page2.goto(); POSTs via page1.evaluate(fetch)
        # -------------------------------------------------------------------
        store_id, catalog_id = fetch_store_config(page2)
        if not store_id:
            print("[!] Could not get store config. Check debug_bootstrap.html.")
            browser.close()
            if xvfb_proc:
                xvfb_proc.terminate()
            return

        terms = fetch_terms(page2, store_id)
        if not terms:
            print("[!] No terms found.")
            browser.close()
            if xvfb_proc:
                xvfb_proc.terminate()
            return

        total_rows  = 0
        debug_saved = False

        for term in terms:
            term_id    = term["termId"]
            term_name  = term["termName"]
            program_id = term["programId"]

            print(f"\n[*] Term: {term_name} ({term_id})")
            course_list = fetch_courses(page2, store_id, term_id, program_id)
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
                        data = fetch_results(page1, store_id, catalog_id,
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
                        row["school_id"]  = SCHOOL_ID
                        row["crawled_on"] = crawled_on
                        row["updated_on"] = crawled_on

                    append_csv(rows, CSV_PATH)
                    dept_rows  += len(rows)
                    total_rows += len(rows)

                if dept_rows:
                    tqdm.write(f"    [{dept_code}] +{dept_rows} rows (total: {total_rows})")

        browser.close()

    if xvfb_proc:
        xvfb_proc.terminate()
        print("[*] Xvfb stopped.")

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE — {total_rows} rows written")
    print(f"CSV: {CSV_PATH}")
    if total_rows == 0:
        print("[!] No data. Check debug_bootstrap.html and debug_results.json.")


if __name__ == "__main__":
    scrape(fresh="--fresh" in sys.argv)
