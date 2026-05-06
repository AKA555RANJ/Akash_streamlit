"""
Spring 2026 scraper for University of Montevallo (OPEID 2987566).
Uses the Shopify App Proxy API (not svc.bkstr.com) because Spring 2026
is only available through the store's Shopify metaobject backend.

API flow:
  1. Bootstrap session via FlareSolverr
  2. GET /apps/shopifyData/getFilteredCampusTerm  → terms + campus UUIDs
  3. GET /apps/shopifyData/getFilteredData?campus_entity_id=...&term_id=...  → sections (with GIDs)
  4. For each section GID:
       GET /apps/shopifyData/products?query=metafields.ddcs.ddcs_section:'{gid}'
       → returns products with isbn_ean, author, section_data_mapping (RequirementIND)
"""
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from curl_cffi import requests as curl_requests
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

SCHOOL_NAME = "university_of_montevallo"
SCHOOL_ID   = "2987566"
BASE_URL    = "https://freddiesbooksandmore.bkstr.com"
STORE_HOME  = f"{BASE_URL}/pages/courses-materials-results"
FLARESOLVERR_URL     = "http://localhost:8191/v1"
FLARESOLVERR_SESSION = "montevallo_spring26"

# Only scrape Spring 2026 with this script
TARGET_TERM_NAME = "Spring 2026"

REQUEST_DELAY = 0.8

CSV_FIELDS = [
    "source_url", "school_id", "department_code", "course_code", "course_title",
    "section", "section_instructor", "term", "isbn", "title", "author",
    "material_adoption_code", "crawled_on", "updated_on",
]

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data", f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")

REQUIREMENT_MAP = {"RQ": "Required Material(s)", "RM": "Recommended Material(s)",
                   "CH": "Choose - Please select from the following...",
                   "BR": "Suggested by the Bookstore"}


def fs_create():
    try:
        requests.post(FLARESOLVERR_URL, json={"cmd":"sessions.destroy","session":FLARESOLVERR_SESSION}, timeout=10)
    except Exception: pass
    requests.post(FLARESOLVERR_URL, json={"cmd":"sessions.create","session":FLARESOLVERR_SESSION}, timeout=120).raise_for_status()

def fs_destroy():
    try:
        requests.post(FLARESOLVERR_URL, json={"cmd":"sessions.destroy","session":FLARESOLVERR_SESSION}, timeout=10)
    except Exception: pass

def fs_get(url, max_timeout=90000):
    resp = requests.post(FLARESOLVERR_URL, json={
        "cmd":"request.get","url":url,
        "session":FLARESOLVERR_SESSION,"maxTimeout":max_timeout,
    }, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"FlareSolverr error: {data}")
    sol = data["solution"]
    return sol.get("cookies",[]), sol.get("userAgent","")

def create_session():
    print("[*] Creating FlareSolverr session...")
    fs_create()
    print(f"[*] Visiting: {STORE_HOME}")
    cookies, ua = fs_get(STORE_HOME)
    cmap = {c["name"]:c["value"] for c in cookies if c.get("name")}
    print(f"    Cookies: {list(cmap.keys())}")
    fs_destroy()

    sess = curl_requests.Session(impersonate="chrome120")
    for k, v in cmap.items():
        sess.cookies.set(k, v)
    sess.headers.update({
        "User-Agent": ua,
        "Referer": STORE_HOME,
        "Origin": BASE_URL,
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    print("[*] Session ready.")
    return sess

def shopify_get(sess, path, retries=3):
    url = f"{BASE_URL}{path}"
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            r = sess.get(url, timeout=30)
            r.raise_for_status()
            data = r.json()
            if not data.get("success", True):
                raise RuntimeError(f"API error: {data}")
            return data
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] {path} attempt {attempt+1}: {e}")
                time.sleep(3 * (attempt + 1))
            else:
                raise

def fetch_terms(sess):
    print("[*] Fetching terms...")
    data = shopify_get(sess, "/apps/shopifyData/getFilteredCampusTerm")
    terms = data["data"]["ddcs_term"]
    campus = data["data"]["ddcs_campus"]
    print(f"    Terms: {[t['name'] for t in terms]}")
    return terms, campus

def fetch_sections(sess, campus_id, term_id):
    data = shopify_get(sess, f"/apps/shopifyData/getFilteredData?campus_entity_id={campus_id}&term_id={term_id}")
    d = data["data"]
    return d.get("ddcs_section",[]), d.get("ddcs_course",[]), d.get("ddcs_campus_department",[])

def fetch_products(sess, section_gid, retries=3):
    q = f"metafields.ddcs.ddcs_section:'{section_gid}'"
    path = f"/apps/shopifyData/products?query={quote(q)}"
    url = f"{BASE_URL}{path}"
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            r = sess.get(url, timeout=30)
            r.raise_for_status()
            data = r.json()
            return data.get("products", [])
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] products attempt {attempt+1}: {e}")
                time.sleep(3 * (attempt + 1))
            else:
                raise

def fmt(code):
    code = (code or "").strip()
    return f"|{code}" if code and not code.startswith("|") else code

def normalize_term(s):
    return re.sub(r'\s*\(.*?\)\s*', ' ', s or "").strip().upper()

def get_scraped_keys(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return {(r.get("term",""), r.get("department_code",""),
                 r.get("course_code",""), r.get("section",""))
                for r in csv.DictReader(f)}

def append_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    new_file = not os.path.exists(filepath) or os.path.getsize(filepath) == 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)

def parse_products(products, dept_code, course_num, section_name, term_name, source_url):
    term = normalize_term(term_name)
    base = {"department_code": dept_code, "course_code": fmt(course_num),
            "section": fmt(section_name), "term": term,
            "source_url": source_url, "course_title": "", "section_instructor": ""}

    if not products:
        return [{**base, "isbn":"","title":"","author":"",
                 "material_adoption_code":"This course does not require any course materials"}]

    rows = []
    seen = set()
    for p in products:
        mf = p.get("metafields", {})
        isbn   = (mf.get("isbn_ean") or mf.get("isbn") or "").strip().replace("-","")
        title  = (p.get("title") or "").strip()
        author = (mf.get("author") or "").strip()

        # Get adoption/requirement type from section_data_mapping
        adoption = ""
        sdm_raw = mf.get("section_data_mapping","") or mf.get("course_materials",{}).get("section_data_mapping","") or ""
        try:
            sdm = json.loads(sdm_raw) if isinstance(sdm_raw,str) and sdm_raw else []
            if sdm:
                req_ind = sdm[0].get("RequirementIND","")
                adoption = REQUIREMENT_MAP.get(req_ind, req_ind or "Required")
        except Exception:
            pass
        if not adoption:
            adoption = "Required"

        key = (isbn, title.lower())
        if key in seen:
            continue
        seen.add(key)
        rows.append({**base, "isbn":isbn, "title":title, "author":author,
                     "material_adoption_code":adoption})

    return rows if rows else [{**base, "isbn":"","title":"","author":"",
                               "material_adoption_code":"This course does not require any course materials"}]

def scrape():
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    done_keys = get_scraped_keys(CSV_PATH)
    if done_keys:
        spring_done = {k for k in done_keys if "SPRING" in k[0]}
        print(f"[*] {len(spring_done)} Spring combos already scraped, resuming.")

    sess = create_session()

    terms, campuses = fetch_terms(sess)
    spring = next((t for t in terms if TARGET_TERM_NAME.lower() in t["name"].lower()), None)
    if not spring:
        print(f"[!] {TARGET_TERM_NAME} not found. Available: {[t['name'] for t in terms]}")
        return
    print(f"[*] Scraping: {spring['name']} (term_id={spring['term_id']})")

    campus_id = spring["campus_entity_id"]
    term_id   = spring["term_id"]

    sections, courses, depts = fetch_sections(sess, campus_id, term_id)
    print(f"    {len(sections)} sections, {len(courses)} courses, {len(depts)} departments")

    # Build lookup maps
    dept_by_id   = {d["campus_department_id"]: d for d in depts}
    course_by_id = {c["course_id"]: c for c in courses}

    total_rows = 0
    debug_saved = False

    for sec in tqdm(sections, desc=f"  {spring['name']}"):
        course = course_by_id.get(sec.get("course_id",""), {})
        dept   = dept_by_id.get(course.get("campus_department_id",""), {})

        dept_code   = dept.get("abbreviation") or dept.get("name","")
        course_num  = course.get("coursenumber","")
        section_name= sec.get("name","")

        check_key = (normalize_term(spring["name"]), dept_code, fmt(course_num), fmt(section_name))
        if check_key in done_keys:
            continue

        instructor = f"{sec.get('instructor_first_name','')} {sec.get('instructor_last_name','')}".strip()
        gid = sec.get("gid","")

        source_url = (f"{BASE_URL}/apps/shopifyData/products"
                      f"?termId={term_id}&dept={quote(dept_code)}"
                      f"&course={quote(course_num)}&section={quote(section_name)}")
        try:
            products = fetch_products(sess, gid)
        except Exception as e:
            tqdm.write(f"  [ERROR] {dept_code}/{course_num}/{section_name}: {e}")
            products = []

        if not debug_saved and products:
            with open(os.path.join(OUTPUT_DIR,"debug_spring_products.json"),"w") as f:
                json.dump(products, f, indent=2)
            debug_saved = True

        rows = parse_products(products, dept_code, course_num, section_name, spring["name"], source_url)
        for row in rows:
            row["school_id"]         = SCHOOL_ID
            row["section_instructor"]= instructor
            row["crawled_on"]        = crawled_on
            row["updated_on"]        = crawled_on

        append_csv(rows, CSV_PATH)
        total_rows += len(rows)

    print(f"\n{'='*60}")
    print(f"SPRING 2026 COMPLETE — {total_rows} rows written")
    print(f"CSV: {CSV_PATH}")

if __name__ == "__main__":
    scrape()
