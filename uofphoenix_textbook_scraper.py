#!/usr/bin/env python3

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

SCHOOL_NAME = "university_of_phoenix_arizona"
SCHOOL_ID = "2990835"
STORE_SLUG = "uofphoenixstore"
BASE_URL = "https://www.bkstr.com"
SVC_URL = "https://svc.bkstr.com"
STORE_HOME = f"{BASE_URL}/{STORE_SLUG}/shop/textbooks-and-course-materials"
FLARESOLVERR_URL = "http://localhost:8191/v1"
FLARESOLVERR_SESSION = "uofphoenix_bkstr_scraper"

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

REQUEST_DELAY = 1.0

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")


def flaresolverr_create_session():
    try:
        requests.post(FLARESOLVERR_URL, json={
            "cmd": "sessions.destroy",
            "session": FLARESOLVERR_SESSION,
        }, timeout=10)
    except Exception:
        pass
    resp = requests.post(FLARESOLVERR_URL, json={
        "cmd": "sessions.create",
        "session": FLARESOLVERR_SESSION,
    }, timeout=120)
    resp.raise_for_status()


def flaresolverr_destroy_session():
    try:
        requests.post(FLARESOLVERR_URL, json={
            "cmd": "sessions.destroy",
            "session": FLARESOLVERR_SESSION,
        }, timeout=10)
    except Exception:
        pass


def flaresolverr_get(url, max_timeout=90000):
    resp = requests.post(FLARESOLVERR_URL, json={
        "cmd": "request.get",
        "url": url,
        "session": FLARESOLVERR_SESSION,
        "maxTimeout": max_timeout,
    }, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"FlareSolverr error: {data}")
    sol = data["solution"]
    return sol.get("response", ""), sol.get("cookies", []), sol.get("userAgent", "")


def flaresolverr_post(url, post_data, max_timeout=90000):
    resp = requests.post(FLARESOLVERR_URL, json={
        "cmd": "request.post",
        "url": url,
        "session": FLARESOLVERR_SESSION,
        "maxTimeout": max_timeout,
        "postData": post_data,
    }, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"FlareSolverr error: {data}")
    sol = data["solution"]
    return sol.get("response", ""), sol.get("cookies", []), sol.get("userAgent", "")


def is_blocked(text):
    if not text:
        return False
    lower = text[:2000].lower()
    return ("just a moment" in lower or "challenge-platform" in lower or
            "<title>attention" in lower or "<title>access denied" in lower or
            "px-captcha" in lower or "access denied" in lower)


def extract_json(html):
    if not html or not html.strip():
        return None
    text = html.strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    m = re.search(r'<(?:pre|body)[^>]*>(.*?)</(?:pre|body)>', text, re.DOTALL)
    if m:
        inner = m.group(1).strip()
        if inner.startswith("{") or inner.startswith("["):
            return json.loads(inner)
    m = re.search(r'(\{["\'](?:finalData|isDivUsed|courseMaterialResultsList).*)', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return None


def normalize_term(term_str):
    if not term_str:
        return ""
    cleaned = re.sub(r'\s*\(.*?\)\s*', ' ', term_str)
    return cleaned.strip().upper()


def format_code(code):
    if not code:
        return ""
    code = code.strip()
    if code and code[0] != "|":
        return f"|{code}"
    return code


def create_session():
    print("[*] Bootstrapping session via FlareSolverr...")
    flaresolverr_create_session()

    print(f"[*] Visiting SPA page: {STORE_HOME}")
    html, cookies, ua = flaresolverr_get(STORE_HOME, max_timeout=120000)
    cookie_names = [c["name"] for c in cookies if c.get("name")]
    print(f"[*] SPA loaded. Cookies: {cookie_names}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    debug_path = os.path.join(OUTPUT_DIR, "debug_bootstrap.html")
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(html)

    if is_blocked(html):
        print("[!] Bootstrap page appears blocked. Retrying...")
        time.sleep(10)
        html, cookies, ua = flaresolverr_get(STORE_HOME, max_timeout=120000)
        if is_blocked(html):
            raise RuntimeError("Cannot bypass protection on bootstrap page")

    return ua


def refresh_session():
    print("[*] Refreshing session...", flush=True)
    for attempt in range(5):
        try:
            flaresolverr_destroy_session()
            time.sleep(5 * (attempt + 1))
            return create_session()
        except Exception as e:
            print(f"  [WARN] Refresh attempt {attempt + 1} failed: {e}", flush=True)
            if attempt == 4:
                raise


def svc_get(endpoint, params=None, retries=3):
    qs = ""
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{SVC_URL}/{endpoint}" + (f"?{qs}" if qs else "")

    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            html, _, _ = flaresolverr_get(url)

            if is_blocked(html):
                if attempt < retries - 1:
                    print(f"  [WARN] Blocked on {endpoint} (attempt {attempt + 1}), refreshing...")
                    refresh_session()
                    continue
                raise RuntimeError(f"Blocked on {endpoint} after {retries} attempts")

            data = extract_json(html)
            if data is not None:
                return data

            if not html.strip():
                return {}
            print(f"  [WARN] Non-JSON response from {endpoint}: {html[:200]}")
            return {}
        except json.JSONDecodeError:
            if attempt < retries - 1:
                print(f"  [WARN] JSON parse error on {endpoint} (attempt {attempt + 1})")
                time.sleep(2)
            else:
                print(f"  [ERROR] JSON parse failed for {endpoint}: {html[:200]}")
                return {}
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] svc_get {endpoint} failed (attempt {attempt + 1}): {e}")
                time.sleep(3 * (attempt + 1))
            else:
                raise
    return {}


def svc_post(endpoint, payload, retries=3):
    url = f"{SVC_URL}/{endpoint}"
    post_data = json.dumps(payload)

    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            html, _, _ = flaresolverr_post(url, post_data)

            if is_blocked(html):
                if attempt < retries - 1:
                    print(f"  [WARN] Blocked on POST {endpoint} (attempt {attempt + 1}), refreshing...")
                    refresh_session()
                    continue
                raise RuntimeError(f"Blocked on POST {endpoint} after {retries} attempts")

            data = extract_json(html)
            if data is not None:
                return data

            if not html.strip():
                return {}
            print(f"  [WARN] Non-JSON POST response from {endpoint}: {html[:200]}")
            return {}
        except json.JSONDecodeError:
            if attempt < retries - 1:
                print(f"  [WARN] JSON parse error on POST {endpoint} (attempt {attempt + 1})")
                time.sleep(2)
            else:
                print(f"  [ERROR] JSON parse failed for POST {endpoint}: {html[:200]}")
                return {}
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] svc_post {endpoint} failed (attempt {attempt + 1}): {e}")
                time.sleep(3 * (attempt + 1))
            else:
                raise
    return {}


def fetch_store_config():
    print("[*] Fetching store config...")
    data = svc_get("store/config", {"storeName": STORE_SLUG})
    store_id = data.get("storeId", "")
    catalog_id = data.get("catalogId", "")
    print(f"    storeId={store_id}, catalogId={catalog_id}")
    return str(store_id), str(catalog_id)


def fetch_terms(store_id):
    print("[*] Fetching terms...")
    data = svc_get("courseMaterial/info", {"storeId": store_id})
    terms = []
    final = data.get("finalData", {})
    for campus in final.get("campus", []):
        for program in campus.get("program", []):
            program_id = program.get("programId", "")
            for term in program.get("term", []):
                terms.append({
                    "termId": term.get("termId", ""),
                    "termName": term.get("termName", ""),
                    "programId": program_id,
                })
    print(f"    Found {len(terms)} terms")
    for t in terms:
        print(f"      {t['termId']}: {t['termName']} (program={t['programId']})")
    return terms


def fetch_courses(store_id, term_id, program_id=""):
    params = {"storeId": store_id, "termId": term_id}
    if program_id:
        params["programId"] = program_id
    data = svc_get("courseMaterial/courses", params)
    departments = []
    final = data.get("finalDDCSData", {})
    for div in final.get("division", []):
        for dept in div.get("department", []):
            dep_name = dept.get("depName", "")
            for course in dept.get("course", []):
                course_name = course.get("courseName", "")
                for section in course.get("section", []):
                    sec_name = section.get("sectionName", "")
                    course_id = section.get("courseId", "")
                    departments.append({
                        "department": dep_name,
                        "course": course_name,
                        "section": sec_name,
                        "courseId": course_id,
                    })
    return departments


def fetch_results(store_id, catalog_id, term_id, program_id, dept, course, section):
    payload = {
        "storeId": store_id,
        "langId": "-1",
        "catalogId": catalog_id,
        "requestType": "DDCSBrowse",
        "courses": [{
            "divisionName": "",
            "departmentName": dept,
            "courseName": course,
            "sectionName": section,
        }],
        "programId": program_id,
        "termId": term_id,
    }
    return svc_post("courseMaterial/results", payload)


def parse_results(data, source_url, dept_code, course_code, section_code, term_name):
    rows = []
    results_list = data.get("courseMaterialResultsList", [])
    if not results_list:
        rows.append({
            "source_url": source_url,
            "department_code": dept_code,
            "course_code": format_code(course_code),
            "course_title": "",
            "section": format_code(section_code),
            "section_instructor": "",
            "term": normalize_term(term_name),
            "isbn": "",
            "title": "",
            "author": "",
            "material_adoption_code": "This course does not require any course materials",
        })
        return rows

    for result in results_list:
        course_title = result.get("courseName", "")
        instructor = result.get("instructor", "")
        materials = result.get("courseMaterialList", [])
        if not materials:
            materials = result.get("materialList", [])

        if not materials:
            rows.append({
                "source_url": source_url,
                "department_code": dept_code,
                "course_code": format_code(course_code),
                "course_title": course_title,
                "section": format_code(section_code),
                "section_instructor": instructor,
                "term": normalize_term(term_name),
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": "This course does not require any course materials",
            })
            continue

        for mat in materials:
            isbn = str(mat.get("isbn", mat.get("isbn13", ""))).replace("-", "").strip()
            title = mat.get("title", mat.get("bookTitle", ""))
            author = mat.get("author", mat.get("bookAuthor", ""))
            adoption = mat.get("materialStatus", mat.get("adoptionStatus",
                       mat.get("requiredStatus", mat.get("status", ""))))

            if adoption.lower() in ("required", "true", "yes", "r"):
                adoption = "Required"
            elif adoption.lower() in ("recommended", "false", "no"):
                adoption = "Recommended"
            elif adoption.lower() in ("optional", "o"):
                adoption = "Optional"
            elif adoption.lower() in ("go to class first", "goclass"):
                adoption = "Go to class first"
            elif not adoption:
                adoption = "Required"

            if isbn or title:
                rows.append({
                    "source_url": source_url,
                    "department_code": dept_code,
                    "course_code": format_code(course_code),
                    "course_title": course_title,
                    "section": format_code(section_code),
                    "section_instructor": instructor,
                    "term": normalize_term(term_name),
                    "isbn": isbn,
                    "title": title or "",
                    "author": author or "",
                    "material_adoption_code": adoption,
                })

    if not rows:
        rows.append({
            "source_url": source_url,
            "department_code": dept_code,
            "course_code": format_code(course_code),
            "course_title": "",
            "section": format_code(section_code),
            "section_instructor": "",
            "term": normalize_term(term_name),
            "isbn": "",
            "title": "",
            "author": "",
            "material_adoption_code": "This course does not require any course materials",
        })
    return rows


def append_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def get_scraped_keys(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    scraped = set()
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row.get("term", ""), row.get("department_code", ""),
                   row.get("course_code", ""), row.get("section", ""))
            scraped.add(key)
    return scraped


def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run -- deleted existing CSV.")

    done_keys = get_scraped_keys(CSV_PATH)
    if done_keys:
        print(f"[*] {len(done_keys)} course/section combos already scraped.")

    ua = create_session()

    store_id, catalog_id = fetch_store_config()
    if not store_id:
        print("[!] Could not get store config. Exiting.")
        return

    terms = fetch_terms(store_id)
    if not terms:
        print("[!] No terms found. Exiting.")
        return

    total_rows = 0
    debug_dumped = False

    for term in terms:
        term_id = term["termId"]
        term_name = term["termName"]
        program_id = term["programId"]

        print(f"\n[*] Processing term: {term_name} ({term_id})")

        course_list = fetch_courses(store_id, term_id, program_id)
        if not course_list:
            print("    No courses found for this term.")
            continue

        dept_groups = {}
        for c in course_list:
            key = c["department"]
            if key not in dept_groups:
                dept_groups[key] = []
            dept_groups[key].append(c)

        print(f"    Found {len(dept_groups)} departments, {len(course_list)} course/sections")

        for dept_code, courses in tqdm(dept_groups.items(), desc=f"  {term_name}"):
            dept_rows = 0
            for course_entry in courses:
                course_code = course_entry["course"]
                section_code = course_entry["section"]

                check_key = (normalize_term(term_name), dept_code,
                             format_code(course_code), format_code(section_code))
                if check_key in done_keys:
                    continue

                source_url = (f"{SVC_URL}/courseMaterial/results?"
                              f"storeId={store_id}&termId={term_id}"
                              f"&dept={dept_code}&course={course_code}"
                              f"&section={section_code}")

                try:
                    data = fetch_results(store_id, catalog_id, term_id,
                                         program_id, dept_code, course_code, section_code)
                except Exception as e:
                    print(f"\n  [ERROR] results {dept_code}/{course_code}/{section_code}: {e}")
                    try:
                        refresh_session()
                        data = fetch_results(store_id, catalog_id, term_id,
                                             program_id, dept_code, course_code, section_code)
                    except Exception as e2:
                        print(f"  [ERROR] Retry failed: {e2}")
                        data = {}

                if not debug_dumped and data:
                    debug_path = os.path.join(OUTPUT_DIR, "debug_results.json")
                    with open(debug_path, "w", encoding="utf-8") as df:
                        json.dump(data, df, indent=2, ensure_ascii=False)
                    print(f"\n    [DEBUG] First results response saved to {debug_path}")
                    debug_dumped = True

                rows = parse_results(data, source_url, dept_code,
                                     course_code, section_code, term_name)
                for row in rows:
                    row["school_id"] = SCHOOL_ID
                    row["crawled_on"] = crawled_on
                if rows:
                    append_csv(rows, CSV_PATH)
                    dept_rows += len(rows)
                    total_rows += len(rows)

            if dept_rows:
                tqdm.write(f"    [{dept_code}] +{dept_rows} rows (total: {total_rows})")

    flaresolverr_destroy_session()

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"Total rows written: {total_rows}")
    print(f"CSV: {CSV_PATH}")

    if total_rows == 0:
        print("\n[!] No data collected. Check debug files in output directory.")


if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    scrape(fresh=fresh)
