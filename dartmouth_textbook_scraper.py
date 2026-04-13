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

SCHOOL_NAME = "dartmouth_college"
SCHOOL_ID = "3059937"
BASE_URL = "https://dartmouthbooks.bncollege.com"
FIND_TEXTBOOKS_URL = BASE_URL + "/course-material/find-textbooks"
API_BASE = BASE_URL + "/course-material-caching"
FLARESOLVERR_URL = "http://localhost:8191/v1"

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

REQUEST_DELAY = 0.5

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")

FLARESOLVERR_SESSION = "dartmouth_bnc_scraper"

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

def flaresolverr_get(url, max_timeout=60000):
    resp = requests.post(FLARESOLVERR_URL, json={
        "cmd": "request.get",
        "url": url,
        "session": FLARESOLVERR_SESSION,
        "maxTimeout": max_timeout,
    }, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"FlareSolverr error: {data}")

    sol = data["solution"]
    html = sol.get("response", "")
    ua = sol.get("userAgent", "")

    cookies = {}
    for c in sol.get("cookies", []):
        if c.get("name"):
            cookies[c["name"]] = c["value"]

    return html, cookies, ua

def create_session():
    print("[*] Bootstrapping session via FlareSolverr...")
    flaresolverr_create_session()
    html, cookies, ua = flaresolverr_get(FIND_TEXTBOOKS_URL)

    sess = requests.Session()
    sess.cookies.update(cookies)
    sess.headers.update({
        "User-Agent": ua,
        "Referer": FIND_TEXTBOOKS_URL,
        "Accept": "application/json, text/html, */*",
    })

    print(f"[*] Session ready. Cookies: {list(cookies.keys())}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    debug_path = os.path.join(OUTPUT_DIR, "debug_bootstrap.html")
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"    Bootstrap HTML saved to {debug_path}")

    return sess, html

def refresh_session(sess):
    print("[*] Refreshing session via FlareSolverr...", flush=True)
    for attempt in range(5):
        try:
            flaresolverr_destroy_session()
            time.sleep(5 * (attempt + 1))
            return create_session()
        except Exception as e:
            print(f"  [WARN] Session refresh attempt {attempt + 1} failed: {e}", flush=True)
            if attempt == 4:
                raise

def is_cloudflare_block(text):
    if not text:
        return False
    lower = text[:1000].lower()
    return ("just a moment" in lower or "challenge-platform" in lower or
            "<title>attention" in lower)

def api_get(sess, endpoint, params=None, retries=3):
    url = f"{API_BASE}/{endpoint}"
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, params=params, timeout=30)
            resp.raise_for_status()
            text = resp.text.strip()

            if is_cloudflare_block(text):
                raise RuntimeError("Cloudflare challenge detected")

            if not text:
                return []

            data = json.loads(text)
            return data
        except json.JSONDecodeError:
            if attempt < retries - 1:
                print(f"  [WARN] Non-JSON response from {endpoint} (attempt {attempt + 1})")
                time.sleep(2 * (attempt + 1))
            else:
                print(f"  [ERROR] Non-JSON response from {endpoint}: {text[:200]}")
                return []
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] API call failed (attempt {attempt + 1}): {e}")
                time.sleep(2 * (attempt + 1))
            else:
                raise
    return []

def discover_campus_id(sess, bootstrap_html):
    print("[*] Discovering campus ID...")
    try:
        data = api_get(sess, "campus")
        if isinstance(data, list) and data:
            print(f"    Campus API returned: {json.dumps(data, indent=2)[:500]}")
            if len(data) == 1:
                campus_id = str(data[0].get("id", data[0].get("campusId", "")))
                print(f"    Found single campus: {campus_id}")
                return campus_id, data
            else:
                print(f"    Found {len(data)} campuses")
                return str(data[0].get("id", data[0].get("campusId", ""))), data
        elif isinstance(data, dict):
            print(f"    Campus API returned dict: {json.dumps(data, indent=2)[:500]}")
            if "id" in data:
                return str(data["id"]), [data]
    except Exception as e:
        print(f"    Campus API endpoint failed: {e}")

    patterns = [
        r'"campusId"\s*:\s*"?(\d+)"?',
        r'"campus"\s*:\s*"?(\d+)"?',
        r'campus[=:]\s*["\']?(\d{3,6})["\']?',
        r'data-campus[="\s]+(\d+)',
        r'storeId["\s:=]+["\']?(\d+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, bootstrap_html)
        if m:
            campus_id = m.group(1)
            print(f"    Found campus ID in HTML: {campus_id}")
            return campus_id, []

    script_urls = re.findall(r'src=["\']([^"\']*\.js[^"\']*)["\']', bootstrap_html)
    for script_url in script_urls[:5]:
        if not script_url.startswith("http"):
            script_url = BASE_URL + "/" + script_url.lstrip("/")
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(script_url, timeout=30)
            if resp.status_code == 200:
                js_text = resp.text
                for pattern in patterns:
                    m = re.search(pattern, js_text)
                    if m:
                        campus_id = m.group(1)
                        print(f"    Found campus ID in JS bundle: {campus_id}")
                        return campus_id, []
        except Exception:
            continue

    raise RuntimeError(
        "Could not discover campus ID. Check debug_bootstrap.html in output dir."
    )

def fetch_terms(sess, campus_id):
    data = api_get(sess, "term", params={"campus": campus_id})
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return []

def fetch_departments(sess, campus_id, term_id):
    data = api_get(sess, "department", params={"campus": campus_id, "term": term_id})
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return []

def fetch_courses(sess, campus_id, term_id, dept_id):
    data = api_get(sess, "course", params={
        "campus": campus_id,
        "term": term_id,
        "department": dept_id,
    })
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return []

def fetch_sections(sess, campus_id, term_id, course_id):
    data = api_get(sess, "section", params={
        "campus": campus_id,
        "term": term_id,
        "course": course_id,
    })
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return []

def fetch_materials(sess, campus_id, term_id, course_id, section_id):
    data = api_get(sess, "course", params={
        "campus": campus_id,
        "term": term_id,
        "course": course_id,
        "section": section_id,
        "oer": "false",
    })
    return data

def get_field(obj, *keys, default=""):
    for key in keys:
        if key in obj:
            val = obj[key]
            if val is not None:
                return str(val)
    return default

def normalize_term(term_str):
    if not term_str:
        return ""
    return term_str.strip().upper()

def parse_materials_response(data, campus_id, term_id, term_name,
                              dept_code, course_id, section_id):
    source_url = (
        f"{API_BASE}/course?campus={campus_id}&term={term_id}"
        f"&course={course_id}&section={section_id}&oer=false"
    )

    course_name = ""
    section_name = ""
    instructor = ""
    materials = []

    if isinstance(data, dict):
        course_name = get_field(data, "courseName", "name", "courseTitle", "title")
        section_name = get_field(data, "sectionName", "sectionCode", "section")
        instructor = get_field(data, "instructor", "sectionInstructor", "professorName")

        mats = (data.get("materials") or data.get("books") or
                data.get("adoptions") or data.get("courseMaterials") or [])
        if isinstance(mats, list):
            materials = mats
        elif isinstance(mats, dict):
            materials = list(mats.values()) if mats else []

        if not materials and "course" in data:
            course_data = data["course"]
            if isinstance(course_data, dict):
                course_name = course_name or get_field(course_data, "name", "title")
                mats = (course_data.get("materials") or course_data.get("books") or [])
                if isinstance(mats, list):
                    materials = mats

    elif isinstance(data, list):
        materials = data

    rows = []

    if not materials:
        rows.append({
            "source_url": source_url,
            "department_code": dept_code,
            "course_code": "",
            "course_title": course_name,
            "section": section_name or section_id,
            "section_instructor": instructor,
            "term": normalize_term(term_name),
            "isbn": "",
            "title": "",
            "author": "",
            "material_adoption_code": "This course does not require any course materials",
        })
    else:
        for mat in materials:
            if not isinstance(mat, dict):
                continue

            isbn = get_field(mat, "isbn", "isbn13", "ISBN", "ISBN13")
            isbn = isbn.replace("-", "").strip()

            title = get_field(mat, "title", "bookTitle", "name")
            author = get_field(mat, "author", "bookAuthor", "authors")
            adoption = get_field(mat, "adoptionCode", "adoption_code",
                                 "requiredStatus", "required", "status")

            if adoption.lower() in ("true", "yes"):
                adoption = "Required"
            elif adoption.lower() in ("false", "no"):
                adoption = "Recommended"

            rows.append({
                "source_url": source_url,
                "department_code": dept_code,
                "course_code": "",
                "course_title": course_name,
                "section": section_name or section_id,
                "section_instructor": instructor,
                "term": normalize_term(term_name),
                "isbn": isbn,
                "title": title,
                "author": author,
                "material_adoption_code": adoption,
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

def get_scraped_departments(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    scraped = set()
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dept = row.get("department_code", "").strip()
            term = row.get("term", "").strip()
            if dept:
                scraped.add((term, dept))
    return scraped

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_depts = get_scraped_departments(CSV_PATH)
    if done_depts:
        print(f"[*] {len(done_depts)} (term, dept) combos already scraped.")
        print("[*] Will only scrape missing departments.")

    sess, bootstrap_html = create_session()

    campus_id, campus_data = discover_campus_id(sess, bootstrap_html)
    print(f"[*] Campus ID: {campus_id}")

    print("[*] Fetching terms...")
    terms = fetch_terms(sess, campus_id)
    if not terms:
        print("[!] No terms found. Exiting.")
        flaresolverr_destroy_session()
        return

    print(f"    Found {len(terms)} terms:")
    for t in terms:
        term_id = get_field(t, "id", "termId", "term_id", "value")
        term_name = get_field(t, "name", "termName", "term_name", "label", "text")
        print(f"      {term_id}: {term_name}")

    total_rows = 0
    debug_dumped = False

    for term_obj in terms:
        term_id = get_field(term_obj, "id", "termId", "term_id", "value")
        term_name = get_field(term_obj, "name", "termName", "term_name", "label", "text")
        if not term_id:
            continue

        print(f"\n[*] Processing term: {term_name} ({term_id})")

        print("[*] Fetching departments...")
        departments = fetch_departments(sess, campus_id, term_id)
        if not departments:
            print("    No departments found for this term.")
            continue

        print(f"    Found {len(departments)} departments")

        for dept_obj in tqdm(departments, desc=f"  {term_name}"):
            dept_id = get_field(dept_obj, "id", "departmentId", "dept_id", "value")
            dept_code = get_field(dept_obj, "code", "departmentCode", "name",
                                  "label", "text", "abrev", default=dept_id)
            dept_name = get_field(dept_obj, "name", "departmentName", "label",
                                  "text", default=dept_code)

            if (normalize_term(term_name), dept_code) in done_depts:
                continue

            try:
                courses = fetch_courses(sess, campus_id, term_id, dept_id)
            except Exception as e:
                print(f"\n  [ERROR] fetch_courses dept={dept_code}: {e}", flush=True)
                try:
                    sess, _ = refresh_session(sess)
                    courses = fetch_courses(sess, campus_id, term_id, dept_id)
                except Exception as e2:
                    print(f"  [ERROR] Retry failed for dept={dept_code}: {e2}", flush=True)
                    continue

            if not courses:
                append_csv([{
                    "source_url": f"{API_BASE}/course?campus={campus_id}&term={term_id}&department={dept_id}",
                    "school_id": SCHOOL_ID,
                    "department_code": dept_code,
                    "course_code": "",
                    "course_title": "",
                    "section": "",
                    "section_instructor": "",
                    "term": normalize_term(term_name),
                    "isbn": "",
                    "title": "",
                    "author": "",
                    "material_adoption_code": "This course does not require any course materials",
                    "crawled_on": crawled_on,
                }], CSV_PATH)
                total_rows += 1
                continue

            dept_rows = 0

            for course_obj in courses:
                course_id = get_field(course_obj, "id", "courseId", "course_id", "value")
                course_code = get_field(course_obj, "code", "courseCode", "name",
                                        "label", "text", default=course_id)
                course_name = get_field(course_obj, "name", "courseName", "title",
                                        "label", "text", default="")

                sections = course_obj.get("sections", [])
                if not sections:
                    try:
                        sections = fetch_sections(sess, campus_id, term_id, course_id)
                    except Exception as e:
                        print(f"\n  [WARN] fetch_sections {dept_code}/{course_code}: {e}")
                        sections = []

                if not sections:
                    try:
                        mat_data = fetch_materials(sess, campus_id, term_id, course_id, "")
                    except Exception as e:
                        print(f"\n  [WARN] fetch_materials {dept_code}/{course_code}: {e}")
                        mat_data = {}

                    if not debug_dumped and mat_data:
                        debug_path = os.path.join(OUTPUT_DIR, "debug_materials_response.json")
                        with open(debug_path, "w", encoding="utf-8") as df:
                            json.dump(mat_data, df, indent=2)
                        print(f"\n    [DEBUG] First materials response saved to {debug_path}")
                        debug_dumped = True

                    rows = parse_materials_response(
                        mat_data, campus_id, term_id, term_name,
                        dept_code, course_id, "",
                    )
                    for row in rows:
                        row["school_id"] = SCHOOL_ID
                        row["crawled_on"] = crawled_on
                        row["course_code"] = course_code
                        if not row.get("course_title"):
                            row["course_title"] = course_name
                    if rows:
                        append_csv(rows, CSV_PATH)
                        dept_rows += len(rows)
                        total_rows += len(rows)
                else:
                    for sec_obj in sections:
                        sec_id = get_field(sec_obj, "id", "sectionId", "section_id", "value")
                        sec_code = get_field(sec_obj, "code", "sectionCode", "name",
                                             "label", "text", default=sec_id)
                        sec_instructor = get_field(sec_obj, "instructor", "professorName",
                                                    "instructorName", default="")

                        try:
                            mat_data = fetch_materials(
                                sess, campus_id, term_id, course_id, sec_id,
                            )
                        except Exception as e:
                            print(f"\n  [WARN] fetch_materials {dept_code}/{course_code}/{sec_code}: {e}")
                            mat_data = {}

                        if not debug_dumped and mat_data:
                            debug_path = os.path.join(OUTPUT_DIR, "debug_materials_response.json")
                            with open(debug_path, "w", encoding="utf-8") as df:
                                json.dump(mat_data, df, indent=2)
                            print(f"\n    [DEBUG] First materials response saved to {debug_path}")
                            debug_dumped = True

                        rows = parse_materials_response(
                            mat_data, campus_id, term_id, term_name,
                            dept_code, course_id, sec_id,
                        )
                        for row in rows:
                            row["school_id"] = SCHOOL_ID
                            row["crawled_on"] = crawled_on
                            row["course_code"] = course_code
                            row["section"] = sec_code
                            row["section_instructor"] = sec_instructor or row.get("section_instructor", "")
                            if not row.get("course_title"):
                                row["course_title"] = course_name
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
        print("    The API structure may differ from expected. Review:")
        print(f"    - {os.path.join(OUTPUT_DIR, 'debug_bootstrap.html')}")
        print(f"    - {os.path.join(OUTPUT_DIR, 'debug_materials_response.json')}")

if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    scrape(fresh=fresh)
