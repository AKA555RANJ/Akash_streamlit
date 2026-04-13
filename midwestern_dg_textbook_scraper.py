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

SCHOOL_NAME = "midwestern_university_downers_grove"
SCHOOL_ID = "3023764"
BASE_URL = "https://midwestern.ecampus.com"
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
    "updated_on",
]

BATCH_SIZE = 15
REQUEST_DELAY = 0.5

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")

FLARESOLVERR_SESSION = "midwestern_dg_ecampus_scraper"

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

def discover_semesters(html):
    semesters = []
    soup = BeautifulSoup(html, "html.parser")

    for select in soup.find_all("select"):
        select_id = (select.get("id") or "").lower()
        select_name = (select.get("name") or "").lower()
        if "semester" in select_id or "term" in select_id or "semester" in select_name:
            for opt in select.find_all("option"):
                val = (opt.get("value") or "").strip()
                text = opt.get_text(strip=True)
                if val and val != "0" and text and "select" not in text.lower():
                    semesters.append((val, text))

    if not semesters:
        for script in soup.find_all("script"):
            script_text = script.string or ""
            for m in re.finditer(r'semesterProperties\[(\d+)\]\s*=\s*\{([^}]+)\}', script_text):
                sid = m.group(1)
                props = m.group(2)
                name_match = re.search(r'name\s*:\s*["\']([^"\']+)', props)
                name = name_match.group(1) if name_match else f"Semester {sid}"
                semesters.append((sid, name))

    if not semesters:
        for opt in soup.find_all("option"):
            val = (opt.get("value") or "").strip()
            text = opt.get_text(strip=True)
            if val and val.isdigit() and len(val) >= 5 and text:
                semesters.append((val, text))

    if not semesters:
        for m in re.finditer(r'value="(\d{5,7})"[^>]*>([^<]+)', html):
            val, text = m.group(1), m.group(2).strip()
            if text and "select" not in text.lower():
                semesters.append((val, text))

    return semesters

def create_session():
    print("[*] Bootstrapping session via FlareSolverr...")
    flaresolverr_create_session()
    html, cookies, ua = flaresolverr_get(BASE_URL + "/shop-by-course")

    sess = requests.Session()
    sess.cookies.update(cookies)
    sess.headers.update({
        "User-Agent": ua,
        "Referer": BASE_URL + "/shop-by-course",
        "Accept": "application/json, text/html, */*",
    })

    print(f"[*] Session ready. Cookies: {list(cookies.keys())}")
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

API_URL = BASE_URL + "/include/get-course-levels-options"

def is_cloudflare_block(text):
    if not text:
        return False
    lower = text[:1000].lower()
    return ("just a moment" in lower or "challenge-platform" in lower or
            "<title>attention" in lower)

def api_get(sess, params, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(API_URL, params=params, timeout=30)
            resp.raise_for_status()
            text = resp.text.strip()

            if is_cloudflare_block(text):
                raise RuntimeError("Cloudflare challenge detected")

            data = json.loads(text)
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] API call failed (attempt {attempt + 1}): {e}")
                time.sleep(2 * (attempt + 1))
            else:
                raise
    return []

def fetch_departments(sess, semester_id):
    params = {"format": "json", "s": semester_id, "startlevel": "1"}
    return api_get(sess, params)

def fetch_courses(sess, semester_id, dept_id):
    params = {"format": "json", "s": semester_id, "startlevel": "2", "c1": dept_id}
    return api_get(sess, params)

def fetch_sections(sess, semester_id, dept_id, course_id):
    params = {
        "format": "json", "s": semester_id, "startlevel": "3",
        "c1": dept_id, "c2": course_id,
    }
    return api_get(sess, params)

def fetch_course_list(sess, section_ids):
    ids_str = "|".join(str(sid) for sid in section_ids)
    url = f"{BASE_URL}/course-list?sbc=1&c={ids_str}"
    time.sleep(REQUEST_DELAY)
    resp = sess.get(url, timeout=60)
    resp.raise_for_status()
    text = resp.text
    if is_cloudflare_block(text):
        raise RuntimeError("Cloudflare challenge on course-list page")
    return text

def parse_course_list(html, term_fallback="SPRING TERM 2026"):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    wrappers = soup.find_all("div", class_="course-wrapper")
    for wrapper in wrappers:
        dept_code = ""
        course_num = ""
        section_code = ""
        term = ""

        levels12 = wrapper.find("span", class_="levels1-2")
        if levels12:
            text = levels12.get_text(strip=True)
            parts = text.split(None, 1)
            dept_code = parts[0] if parts else text
            course_num = parts[1] if len(parts) > 1 else ""

        levels34 = wrapper.find("span", class_="levels3-4")
        if levels34:
            section_code = "|" + levels34.get_text(strip=True)

        semester_span = wrapper.find("span", class_="semester")
        if semester_span:
            term = semester_span.get_text(strip=True).upper()

        course_code = f"|{course_num}" if course_num else ""

        course_title = ""
        instructor = ""
        name_inst = wrapper.find("div", class_="course-name-inst")
        if name_inst:
            inst_span = name_inst.find("span", class_="course-inst")
            if inst_span:
                instructor = inst_span.get_text(strip=True).lstrip("- ").strip()
                inst_span.decompose()
            course_title = name_inst.get_text(strip=True)

        book_divs = wrapper.find_all("div", class_="course-book")

        if not book_divs:
            no_text_div = wrapper.find("div", class_="no-text")
            wrapper_text = wrapper.get_text(" ", strip=True).lower()
            if ("no course materials" in wrapper_text or
                    "not require" in wrapper_text or
                    "no textbook" in wrapper_text):
                adoption = "This course does not require any course materials"
            elif no_text_div or "still being determined" in wrapper_text:
                adoption = "This course does not require any course materials"
            else:
                adoption = "This course does not require any course materials"
            results.append({
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": course_title,
                "section": section_code,
                "section_instructor": instructor,
                "term": term or term_fallback,
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": adoption,
            })
            continue

        for book_div in book_divs:
            adoption = ""
            req_input = book_div.find("input", id=re.compile(r"^cbitreqm-"))
            if req_input:
                adoption = (req_input.get("value", "") or "").capitalize()
            if not adoption:
                imp_div = book_div.find("div", class_="importance")
                if imp_div:
                    adoption = imp_div.get_text(strip=True).capitalize()

            isbn = ""
            isbn_div = book_div.find("div", class_="isbn")
            if isbn_div:
                isbn_match = re.search(r"(\d[\d-]{8,})", isbn_div.get_text())
                if isbn_match:
                    isbn = isbn_match.group(1).replace("-", "").strip()
            if not isbn:
                isbn_el = book_div.find(attrs={"isbnupc": True})
                if isbn_el:
                    isbn = (isbn_el.get("isbnupc", "") or "").replace("-", "").strip()

            title = ""
            title_div = book_div.find("div", class_="title")
            if title_div:
                h3 = title_div.find("h3")
                if h3:
                    title = h3.get_text(strip=True)

            author = ""
            author_div = book_div.find("div", class_="author")
            if author_div:
                author = author_div.get_text(strip=True)

            results.append({
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": course_title,
                "section": section_code,
                "section_instructor": instructor,
                "term": term or term_fallback,
                "isbn": isbn,
                "title": title,
                "author": author,
                "material_adoption_code": adoption,
            })

    return results

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
            if dept:
                scraped.add(dept)
    return scraped

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    source_url = BASE_URL + "/"

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_depts = get_scraped_departments(CSV_PATH)
    if done_depts:
        print(f"[*] {len(done_depts)} departments already scraped: {sorted(done_depts)}")
        print("[*] Will only scrape missing departments.")

    sess, bootstrap_html = create_session()

    semesters = discover_semesters(bootstrap_html)
    if semesters:
        print(f"[*] Available semesters:")
        for sid, sname in semesters:
            print(f"    {sid}: {sname}")
    else:
        print("[!] Could not auto-discover semester IDs from page HTML.")
        print("    Dumping bootstrap HTML for manual inspection...")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        debug_path = os.path.join(OUTPUT_DIR, "debug_bootstrap.html")
        with open(debug_path, "w", encoding="utf-8") as df:
            df.write(bootstrap_html)
        print(f"    Saved to: {debug_path}")
        print("    Please inspect the HTML, find the semester ID, and set SEMESTER_ID below.")
        return

    semester_id = None
    term_name = None
    for sid, sname in semesters:
        if "spring" in sname.lower() and "2026" in sname:
            semester_id = sid
            term_name = sname.upper()
            break
    if not semester_id:
        semester_id, term_name = semesters[-1]
        term_name = term_name.upper()

    print(f"[*] Using semester: {semester_id} ({term_name})")

    print("[*] Fetching departments...")
    all_depts = fetch_departments(sess, semester_id)
    print(f"    Found {len(all_depts)} departments (all campuses)")

    depts = [d for d in all_depts if d["id"].endswith("D") or (not d["id"].endswith("G"))]
    print(f"    Filtered to {len(depts)} Downers Grove departments (suffix 'D' + shared)")

    if not depts:
        print("[!] No departments found. Exiting.")
        return

    total_rows = 0
    all_expected_depts = set(d["id"] for d in depts)
    debug_dumped = False

    for dept in tqdm(depts, desc="Departments"):
        dept_code = dept["id"]

        if dept_code in done_depts:
            continue

        try:
            courses = fetch_courses(sess, semester_id, dept_code)
        except Exception as e:
            print(f"\n  [ERROR] fetch_courses dept={dept_code}: {e}", flush=True)
            try:
                sess, _ = refresh_session(sess)
                courses = fetch_courses(sess, semester_id, dept_code)
            except Exception as e2:
                print(f"  [ERROR] Retry failed for dept={dept_code}: {e2}", flush=True)
                continue

        if not courses:
            append_csv([{
                "source_url": source_url,
                "school_id": SCHOOL_ID,
                "department_code": dept_code,
                "course_code": "",
                "course_title": "",
                "section": "",
                "section_instructor": "",
                "term": term_name,
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": "No courses found for this department",
                "crawled_on": crawled_on,
                "updated_on": crawled_on,
            }], CSV_PATH)
            total_rows += 1
            continue

        all_section_ids = []
        for course in courses:
            course_num = course["id"]
            try:
                sections = fetch_sections(sess, semester_id, dept_code, course_num)
            except Exception as e:
                print(f"\n  [ERROR] fetch_sections {dept_code} {course_num}: {e}", flush=True)
                continue

            for sec in sections:
                all_section_ids.append(sec["id"])

        if not all_section_ids:
            continue

        batches = [
            all_section_ids[i:i + BATCH_SIZE]
            for i in range(0, len(all_section_ids), BATCH_SIZE)
        ]

        dept_rows = 0
        for batch_idx, batch in enumerate(batches):
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    html = fetch_course_list(sess, batch)

                    if not debug_dumped:
                        debug_path = os.path.join(OUTPUT_DIR, "debug_course_list.html")
                        os.makedirs(OUTPUT_DIR, exist_ok=True)
                        with open(debug_path, "w", encoding="utf-8") as df:
                            df.write(html)
                        print(f"\n    [DEBUG] First course-list HTML dumped to {debug_path}", flush=True)
                        debug_dumped = True

                    materials = parse_course_list(html, term_fallback=term_name)

                    rows = []
                    for row in materials:
                        row["source_url"] = source_url
                        row["school_id"] = SCHOOL_ID
                        row["crawled_on"] = crawled_on
                        row["updated_on"] = crawled_on
                        rows.append(row)

                    if rows:
                        append_csv(rows, CSV_PATH)
                        dept_rows += len(rows)
                        total_rows += len(rows)

                    break

                except Exception as e:
                    print(f"\n  [!] Batch {batch_idx} attempt {attempt + 1} failed: {e}", flush=True)
                    if attempt < max_retries - 1:
                        sess, _ = refresh_session(sess)
                    else:
                        print(f"  [!] SKIPPING batch {batch_idx} for dept={dept_code}", flush=True)

        tqdm.write(f"    [{dept_code}] +{dept_rows} rows (total: {total_rows})")

    flaresolverr_destroy_session()

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"Total rows written: {total_rows}")
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
