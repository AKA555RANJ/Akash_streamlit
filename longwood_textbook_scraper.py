import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from curl_cffi import requests as curl_requests
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

SCHOOL_NAME = "longwood_university"
SCHOOL_ID   = "3106033"
STORE_SLUG  = "longwoodstore"
BASE_URL    = "https://www.bkstr.com"
SVC_URL     = "https://svc.bkstr.com"
STORE_HOME  = f"{BASE_URL}/{STORE_SLUG}/shop/textbooks-and-course-materials"

FLARESOLVERR_URL     = "http://localhost:8191/v1"
FLARESOLVERR_SESSION = "longwood_bkstr_scraper"

REQUEST_DELAY = 1.0

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

def fs_create():
    try:
        requests.post(FLARESOLVERR_URL, json={
            "cmd": "sessions.destroy",
            "session": FLARESOLVERR_SESSION,
        }, timeout=10)
    except Exception:
        pass
    requests.post(FLARESOLVERR_URL, json={
        "cmd": "sessions.create",
        "session": FLARESOLVERR_SESSION,
    }, timeout=120).raise_for_status()

def fs_destroy():
    try:
        requests.post(FLARESOLVERR_URL, json={
            "cmd": "sessions.destroy",
            "session": FLARESOLVERR_SESSION,
        }, timeout=10)
    except Exception:
        pass

def fs_get(url, max_timeout=120000):
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

def create_session():
    print("[*] Creating FlareSolverr session...")
    fs_create()

    print(f"[*] Step 1 — visiting SPA: {STORE_HOME}")
    html, cookies1, ua = fs_get(STORE_HOME)
    cmap = {c["name"]: c["value"] for c in cookies1 if c.get("name")}
    print(f"    Cookies so far: {list(cmap.keys())}")

    svc_config_url = f"{SVC_URL}/store/config?storeName={STORE_SLUG}"
    print(f"[*] Step 2 — visiting svc to trigger _pxhd: {svc_config_url}")
    _, cookies2, _ = fs_get(svc_config_url)
    cmap2 = {c["name"]: c["value"] for c in cookies2 if c.get("name")}
    cmap.update(cmap2)
    print(f"    All merged cookies: {list(cmap.keys())}")
    print(f"    _pxhd present: {bool(cmap.get('_pxhd'))}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "debug_bootstrap.html"), "w", encoding="utf-8") as f:
        f.write(html)

    fs_destroy()
    print("[*] FlareSolverr session destroyed. Handing off to curl_cffi.")

    sess = curl_requests.Session(impersonate="chrome120")
    for name, value in cmap.items():
        sess.cookies.set(name, value)
    sess.headers.update({
        "User-Agent": ua,
        "Referer": STORE_HOME + "/",
        "Origin": BASE_URL,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    })

    print("[*] Session ready.")
    return sess, html

def refresh_session():
    print("[*] Refreshing session...", flush=True)
    for attempt in range(4):
        try:
            time.sleep(8 * (attempt + 1))
            sess, _ = create_session()
            return sess
        except Exception as e:
            print(f"  [WARN] Refresh attempt {attempt+1} failed: {e}", flush=True)
            if attempt == 3:
                raise

def is_px_block(text):
    if not text:
        return False
    try:
        d = json.loads(text) if isinstance(text, str) else text
        return isinstance(d, dict) and "appId" in d and "jsClientSrc" in d
    except Exception:
        return False

def svc_get(sess, endpoint, params=None, retries=3):
    qs = "&".join(f"{k}={v}" for k, v in (params or {}).items())
    url = f"{SVC_URL}/{endpoint}" + (f"?{qs}" if qs else "")
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, timeout=30)
            text = resp.text
            if resp.status_code == 403 or is_px_block(text):
                print(f"  [WARN] PX block on GET {endpoint} (attempt {attempt+1})")
                if attempt < retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Blocked GET {endpoint}")
            resp.raise_for_status()
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"  [WARN] Non-JSON GET {endpoint}: {text[:200]}")
            return {}
        except RuntimeError:
            raise
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] svc_get {endpoint} attempt {attempt+1}: {e}")
                time.sleep(3 * (attempt + 1))
            else:
                raise
    return {}

def svc_post_results(sess, store_id, catalog_id, term_id, program_id,
                     dept, course, section, retries=3):
    url = (f"{SVC_URL}/courseMaterial/results"
           f"?storeId={store_id}&langId=-1&catalogId={catalog_id}&requestType=DDCSBrowse")
    payload = {
        "storeId":   store_id,
        "termId":    term_id,
        "programId": program_id,
        "courses": [{
            "secondaryvalues":       f"{dept}/{course}/{section}",
            "divisionDisplayName":   "",
            "departmentDisplayName": dept,
            "courseDisplayName":     course,
            "sectionDisplayName":    section,
        }],
    }
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.post(url, json=payload, timeout=60)
            text = resp.text
            if resp.status_code == 403 or is_px_block(text):
                print(f"  [WARN] PX block on POST results (attempt {attempt+1})")
                if attempt < retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError("Blocked POST courseMaterial/results")
            resp.raise_for_status()
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"  [WARN] Non-JSON POST results: {text[:200]}")
            return []
        except RuntimeError:
            raise
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] svc_post attempt {attempt+1}: {e}")
                time.sleep(3 * (attempt + 1))
            else:
                raise
    return []

def fetch_store_config(sess):
    print("[*] Fetching store config...")
    data = svc_get(sess, "store/config", {"storeName": STORE_SLUG})
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

def fetch_terms(sess, store_id):
    print("[*] Fetching terms...")
    data = svc_get(sess, "courseMaterial/info", {"storeId": store_id})
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

def fetch_courses(sess, store_id, term_id, program_id):
    params = {"storeId": store_id, "termId": term_id}
    if program_id:
        params["programId"] = program_id
    data = svc_get(sess, "courseMaterial/courses", params)
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
    seen = set()
    unique = []
    for r in rows:
        key = (r["department"], r["course"], r["section"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique

def normalize_term(s):
    return re.sub(r'\s*\(.*?\)\s*', ' ', s or "").strip().upper()

def fmt(code):
    code = (code or "").strip()
    return f"|{code}" if code and not code.startswith("|") else code

def parse_results(raw, source_url, dept, course, section, term_name):
    rows = []
    base = {
        "department_code": dept,
        "course_code":     fmt(course),
        "section":         fmt(section),
        "term":            normalize_term(term_name),
        "source_url":      source_url,
    }

    if not isinstance(raw, list) or not raw:
        rows.append({**base, "course_title": "", "section_instructor": "",
                     "isbn": "", "title": "", "author": "",
                     "material_adoption_code": "This course does not require any course materials"})
        return rows

    for store_data in raw:
        req_map = store_data.get("requirementTypeLabelMap", {})
        for sec in store_data.get("courseSectionDTO", []):
            instructor = sec.get("instructor", "") or sec.get("instructorName", "")
            materials  = sec.get("courseMaterialResultsList", [])

            if not materials:
                rows.append({**base, "course_title": "",
                             "section_instructor": instructor,
                             "isbn": "", "title": "", "author": "",
                             "material_adoption_code": "This course does not require any course materials"})
                continue

            for mat in materials:
                isbn   = str(mat.get("isbn13", mat.get("isbn", ""))).replace("-", "").strip()
                if isbn in ("None", "nan"):
                    isbn = ""
                title  = mat.get("title", "") or ""
                author = mat.get("author", "") or ""

                req_type = mat.get("requirementType", "")
                adoption = req_map.get(req_type, req_type) or "Required"

                if isbn or title:
                    rows.append({**base, "course_title": "",
                                 "section_instructor": instructor,
                                 "isbn": isbn, "title": title, "author": author,
                                 "material_adoption_code": adoption})

    if not rows:
        rows.append({**base, "course_title": "", "section_instructor": "",
                     "isbn": "", "title": "", "author": "",
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

    sess, _ = create_session()

    store_id, catalog_id = fetch_store_config(sess)
    if not store_id:
        print("[!] Could not get store config. Exiting.")
        return

    terms = fetch_terms(sess, store_id)
    if not terms:
        print("[!] No terms found. Exiting.")
        return

    total_rows  = 0
    debug_saved = False

    for term in terms:
        term_id    = term["termId"]
        term_name  = term["termName"]
        program_id = term["programId"]

        print(f"\n[*] Term: {term_name} ({term_id})")
        course_list = fetch_courses(sess, store_id, term_id, program_id)
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

                source_url = (f"{SVC_URL}/courseMaterial/results"
                              f"?storeId={store_id}&termId={term_id}"
                              f"&dept={dept_code}&course={course_code}&section={section_code}")

                try:
                    raw = svc_post_results(sess, store_id, catalog_id, term_id, program_id,
                                           dept_code, course_code, section_code)
                except RuntimeError as e:
                    tqdm.write(f"\n  [ERROR] {dept_code}/{course_code}/{section_code}: {e}")
                    tqdm.write("  [INFO] Session likely expired — refreshing...")
                    try:
                        sess = refresh_session()
                        store_id, catalog_id = fetch_store_config(sess)
                        raw = svc_post_results(sess, store_id, catalog_id, term_id, program_id,
                                               dept_code, course_code, section_code)
                    except Exception as e2:
                        tqdm.write(f"  [ERROR] Retry failed: {e2}")
                        raw = []
                except Exception as e:
                    tqdm.write(f"\n  [ERROR] {dept_code}/{course_code}/{section_code}: {e}")
                    raw = []

                if not debug_saved and raw:
                    debug_path = os.path.join(OUTPUT_DIR, "debug_results.json")
                    with open(debug_path, "w", encoding="utf-8") as df:
                        json.dump(raw, df, indent=2, ensure_ascii=False)
                    tqdm.write(f"\n    [DEBUG] First result saved to {debug_path}")
                    debug_saved = True

                rows = parse_results(raw, source_url, dept_code, course_code, section_code, term_name)
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
        print("[!] No data. Check debug_bootstrap.html and debug_results.json.")

if __name__ == "__main__":
    scrape(fresh="--fresh" in sys.argv)
