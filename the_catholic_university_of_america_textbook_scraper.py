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

SCHOOL_NAME = "the_catholic_university_of_america"
SCHOOL_ID   = "2984208"
BASE_URL    = "https://catholic.ecampus.com"
FLARESOLVERR_URL     = "http://localhost:8191/v1"
FLARESOLVERR_SESSION = "catholic_ecampus_scraper"

SEMESTERS = [
    ("148720", "SPRING 2026"),
    ("149064", "SUMMER 2026"),
    ("149086", "FALL 2026"),
]

CSV_FIELDS = [
    "source_url", "school_id", "department_code", "course_code", "course_title",
    "section", "section_instructor", "term", "isbn", "title", "author",
    "material_adoption_code", "crawled_on", "updated_on",
]

BATCH_SIZE    = 15
REQUEST_DELAY = 0.5

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data", f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")

def flaresolverr_create_session():
    try:
        requests.post(FLARESOLVERR_URL, json={"cmd": "sessions.destroy", "session": FLARESOLVERR_SESSION}, timeout=10)
    except Exception:
        pass
    requests.post(FLARESOLVERR_URL, json={"cmd": "sessions.create", "session": FLARESOLVERR_SESSION}, timeout=120).raise_for_status()

def flaresolverr_destroy_session():
    try:
        requests.post(FLARESOLVERR_URL, json={"cmd": "sessions.destroy", "session": FLARESOLVERR_SESSION}, timeout=10)
    except Exception:
        pass

def flaresolverr_get(url, max_timeout=60000):
    resp = requests.post(FLARESOLVERR_URL, json={
        "cmd": "request.get", "url": url,
        "session": FLARESOLVERR_SESSION, "maxTimeout": max_timeout,
    }, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"FlareSolverr error: {data}")
    sol = data["solution"]
    cookies = {c["name"]: c["value"] for c in sol.get("cookies", []) if c.get("name")}
    return sol.get("response", ""), cookies, sol.get("userAgent", "")

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
    return sess

def refresh_session(sess):
    print("[*] Refreshing session...", flush=True)
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
    return "just a moment" in lower or "challenge-platform" in lower or "<title>attention" in lower

def api_get(sess, params, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(API_URL, params=params, timeout=30)
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            text = resp.text.strip()
            if is_cloudflare_block(text):
                raise RuntimeError("Cloudflare challenge detected")
            data = json.loads(text)
            return data if isinstance(data, list) else []
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] API call failed (attempt {attempt + 1}): {e}")
                time.sleep(2 * (attempt + 1))
            else:
                raise
    return []

def fetch_departments(sess, semester_id):
    return api_get(sess, {"format": "json", "s": semester_id, "startlevel": "1"})

def fetch_courses(sess, semester_id, dept_id):
    return api_get(sess, {"format": "json", "s": semester_id, "startlevel": "2", "c1": dept_id})

def fetch_sections(sess, semester_id, dept_id, course_id):
    return api_get(sess, {"format": "json", "s": semester_id, "startlevel": "3", "c1": dept_id, "c2": course_id})

def fetch_course_list(sess, section_ids):
    ids_str = "|".join(str(sid) for sid in section_ids)
    url = f"{BASE_URL}/course-list?sbc=1&c={ids_str}"
    time.sleep(REQUEST_DELAY)
    resp = sess.get(url, timeout=60)
    resp.raise_for_status()
    resp.encoding = 'utf-8'
    text = resp.text
    if is_cloudflare_block(text):
        raise RuntimeError("Cloudflare challenge on course-list page")
    return text

def parse_course_list(html, fallback_term=""):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for wrapper in soup.find_all("div", class_="course-wrapper"):
        dept_code, course_num, section_code, term = "", "", "", ""
        levels12 = wrapper.find("span", class_="levels1-2")
        if levels12:
            parts = levels12.get_text(strip=True).split(None, 1)
            dept_code  = parts[0] if parts else ""
            course_num = parts[1] if len(parts) > 1 else ""
        levels34 = wrapper.find("span", class_="levels3-4")
        if levels34:
            section_code = levels34.get_text(strip=True)
        semester_span = wrapper.find("span", class_="semester")
        if semester_span:
            term = semester_span.get_text(strip=True).upper()
        course_code = "|" + course_num.strip() if course_num.strip() else ""
        section_code = "|" + section_code if section_code else ""
        course_title = ""
        instructor   = ""
        name_inst = wrapper.find("div", class_="course-name-inst")
        if name_inst:
            inst_span = name_inst.find("span", class_="course-inst")
            if inst_span:
                instructor = " ".join(inst_span.get_text(strip=True).lstrip("- ").split())
                inst_span.decompose()
            course_title = name_inst.get_text(strip=True)
        book_divs = wrapper.find_all("div", class_="course-book")
        if not book_divs:
            wrapper_text = wrapper.get_text(" ", strip=True).lower()
            if any(k in wrapper_text for k in ("no course materials", "not require", "no textbook")):
                adoption = "This course does not require any course materials"
            else:
                adoption = ""
            results.append({"department_code": dept_code, "course_code": course_code,
                             "course_title": course_title, "section": section_code,
                             "section_instructor": instructor, "term": term or fallback_term,
                             "isbn": "", "title": "", "author": "", "material_adoption_code": adoption})
            continue
        adoption_map = {
            "required": "Required Material(s)", "recommended": "Recommended Material(s)",
            "optional": "Optional Material(s)", "suggested": "Suggested Material(s)",
            "choice": "Choose One",
        }
        for book_div in book_divs:
            adoption = ""
            req_input = book_div.find("input", id=re.compile(r"^cbitreqm-"))
            if req_input:
                raw = (req_input.get("value", "") or "").strip().lower()
                adoption = adoption_map.get(raw, raw.capitalize())
            if not adoption:
                imp_div = book_div.find("div", class_="importance")
                if imp_div:
                    raw = imp_div.get_text(strip=True).strip().lower()
                    adoption = adoption_map.get(raw, raw.capitalize())
            isbn = ""
            isbn_div = book_div.find("div", class_="isbn")
            if isbn_div:
                m = re.search(r"(\d[\d-]{8,})", isbn_div.get_text())
                if m:
                    isbn = m.group(1).replace("-", "").strip()
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
            results.append({"department_code": dept_code, "course_code": course_code,
                             "course_title": course_title, "section": section_code,
                             "section_instructor": instructor, "term": term or fallback_term,
                             "isbn": isbn, "title": title, "author": author,
                             "material_adoption_code": adoption})
    return results

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
        return {(r.get("term","").strip(), r.get("department_code","").strip())
                for r in csv.DictReader(f)}

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys = get_scraped_keys(CSV_PATH)
    if done_keys:
        print(f"[*] {len(done_keys)} (term, dept) combos already scraped — resuming.")

    sess = create_session()
    total_rows = 0

    for semester_id, term_name in SEMESTERS:
        print(f"\n[*] Term: {term_name} (semester_id={semester_id})")
        depts = fetch_departments(sess, semester_id)
        print(f"    Found {len(depts)} departments")
        if not depts:
            print("    No departments — skipping term.")
            continue

        debug_dumped = False
        for dept in tqdm(depts, desc=f"  {term_name}"):
            dept_code = dept["id"]
            if (term_name, dept_code) in done_keys:
                continue

            try:
                courses = fetch_courses(sess, semester_id, dept_code)
            except Exception as e:
                tqdm.write(f"\n  [ERROR] fetch_courses {dept_code}: {e}")
                try:
                    sess = refresh_session(sess)
                    courses = fetch_courses(sess, semester_id, dept_code)
                except Exception as e2:
                    tqdm.write(f"  [ERROR] Retry failed for {dept_code}: {e2}")
                    continue

            if not courses:
                append_csv([{
                    "source_url": BASE_URL + "/", "school_id": SCHOOL_ID,
                    "department_code": dept_code, "course_code": "", "course_title": "",
                    "section": "", "section_instructor": "", "term": term_name,
                    "isbn": "", "title": "", "author": "",
                    "material_adoption_code": "No courses found for this department",
                    "crawled_on": crawled_on, "updated_on": crawled_on,
                }], CSV_PATH)
                total_rows += 1
                continue

            all_section_ids = []
            for course in courses:
                course_num = course["id"]
                try:
                    sections = fetch_sections(sess, semester_id, dept_code, course_num)
                except Exception as e:
                    tqdm.write(f"\n  [ERROR] fetch_sections {dept_code} {course_num}: {e}")
                    continue
                for sec in sections:
                    all_section_ids.append(sec["id"])

            if not all_section_ids:
                continue

            batches = [all_section_ids[i:i+BATCH_SIZE] for i in range(0, len(all_section_ids), BATCH_SIZE)]
            dept_rows = 0
            for batch_idx, batch in enumerate(batches):
                source_url = f"{BASE_URL}/course-list?sbc=1&c={'|'.join(str(s) for s in batch)}"
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        html = fetch_course_list(sess, batch)

                        if is_cloudflare_block(html):
                            raise RuntimeError("Cloudflare block on course-list")

                        if not debug_dumped and html:
                            debug_path = os.path.join(OUTPUT_DIR, "debug_course_list.html")
                            os.makedirs(OUTPUT_DIR, exist_ok=True)
                            with open(debug_path, "w", encoding="utf-8") as df:
                                df.write(html)
                            debug_dumped = True

                        materials = parse_course_list(html, fallback_term=term_name)
                        rows = []
                        for row in materials:
                            row["source_url"]  = BASE_URL + "/shop-by-course"
                            row["school_id"]   = SCHOOL_ID
                            row["crawled_on"]  = crawled_on
                            row["updated_on"]  = crawled_on
                            rows.append(row)

                        if rows:
                            append_csv(rows, CSV_PATH)
                            dept_rows  += len(rows)
                            total_rows += len(rows)
                        break

                    except Exception as e:
                        tqdm.write(f"\n  [!] Batch {batch_idx} attempt {attempt + 1} failed: {e}")
                        if attempt < max_retries - 1:
                            sess = refresh_session(sess)
                        else:
                            tqdm.write(f"  [!] SKIPPING batch {batch_idx} for dept={dept_code}")

            if dept_rows:
                tqdm.write(f"    [{dept_code}] +{dept_rows} rows (total: {total_rows})")

    flaresolverr_destroy_session()
    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE — {total_rows} rows written")
    print(f"CSV: {CSV_PATH}")

if __name__ == "__main__":
    scrape(fresh="--fresh" in sys.argv)
