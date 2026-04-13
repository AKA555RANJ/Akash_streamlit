import csv
import os
import re
import sys
import time
from datetime import datetime, timezone

import warnings

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from tqdm import tqdm

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

SCHOOL_NAME = "iowa_western_community_college"
SCHOOL_ID = "3020581"
BASE_URL = "https://www.iwcccollegestore.com"
CAMPUS_ID = "49"
TERM_ID = "363"
TERM_VALUE = f"{CAMPUS_ID}|{TERM_ID}"
TERM_NAME = "SPRING 2026"
FLARESOLVERR_URL = "http://localhost:8191/v1"
FLARESOLVERR_SESSION = "iwcc_scraper"

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

BATCH_SIZE = 15
REQUEST_DELAY = 0.5

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
    html, cookies, ua = flaresolverr_get(BASE_URL + "/buy_textbooks.asp")

    if "x-bni-fpc" not in cookies:
        print("[WARN] x-bni-fpc cookie not found — bot protection may not be bypassed")

    csrf_token = ""
    csrf_match = re.search(r'name="__CSRFToken"\s+value="([^"]+)"', html)
    if csrf_match:
        csrf_token = csrf_match.group(1)
        print(f"[*] CSRF token found: {csrf_token[:20]}...")
    else:
        print("[WARN] __CSRFToken not found in page HTML")

    sess = requests.Session()
    sess.cookies.update(cookies)
    sess.headers.update({
        "User-Agent": ua,
        "Referer": BASE_URL + "/buy_textbooks.asp",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "text/xml, application/xml, text/html, */*",
    })

    print(f"[*] Session ready. Cookies: {list(cookies.keys())}")
    return sess, csrf_token

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

def is_bot_blocked(text):
    if not text:
        return False
    lower = text[:2000].lower()
    return ("error.asp" in lower or "object moved" in lower or
            "just a moment" in lower or "challenge-platform" in lower)

def xml_get(sess, params, retries=3):
    url = BASE_URL + "/textbooks_xml.asp"
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, params=params, timeout=30)
            resp.raise_for_status()
            text = resp.text.strip()

            if is_bot_blocked(text):
                raise RuntimeError("Bot detection triggered")

            if "<!DOCTYPE" in text[:100] or "<html" in text[:200].lower():
                raise RuntimeError("Got HTML error page instead of XML")

            return BeautifulSoup(text, "html.parser")
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] XML API call failed (attempt {attempt + 1}): {e}")
                time.sleep(2 * (attempt + 1))
            else:
                raise
    return BeautifulSoup("", "html.parser")

def fetch_departments(sess):
    params = {"control": "campus", "campus": CAMPUS_ID, "term": TERM_ID}
    soup = xml_get(sess, params)
    departments = []
    for dept in soup.find_all("department"):
        departments.append({
            "dept_id": dept.get("id", ""),
            "dept_code": dept.get("abrev", ""),
            "dept_name": dept.get("name", ""),
        })
    return departments

def fetch_courses(sess, dept_id):
    params = {"control": "department", "dept": dept_id, "term": TERM_ID}
    soup = xml_get(sess, params)
    courses = []
    for course in soup.find_all("course"):
        courses.append({
            "course_id": course.get("id", ""),
            "course_name": course.get("name", ""),
        })
    return courses

def fetch_sections(sess, course_id):
    params = {"control": "course", "course": course_id, "term": TERM_ID}
    soup = xml_get(sess, params)
    sections = []
    for section in soup.find_all("section"):
        sections.append({
            "section_id": section.get("id", ""),
            "section_name": section.get("name", ""),
            "instructor": section.get("instructor", ""),
        })
    return sections

def fetch_textbooks(sess, section_ids, csrf_token):
    url = BASE_URL + "/textbook_express.asp?mode=2&step=2"
    data = {
        "sectionIds": ",".join(str(sid) for sid in section_ids),
        "selTerm": TERM_VALUE,
        "__CSRFToken": csrf_token,
        "tbe-block-mode": "0",
    }
    time.sleep(REQUEST_DELAY)
    resp = sess.post(url, data=data, timeout=60)
    resp.raise_for_status()
    text = resp.text
    if is_bot_blocked(text):
        raise RuntimeError("Bot detection on textbook_express page")
    return text

def parse_textbook_html(html, section_meta):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen_section_ids = set()

    all_h3s = soup.find_all("h3")
    section_headers = []
    for h3 in all_h3s:
        span = h3.find("span", id="course-bookdisplay-coursename")
        if span:
            section_headers.append(h3)

    for h3 in section_headers:
        dept_code = ""
        course_code = ""
        section_name = ""
        instructor = ""

        header_span = h3.find("span", id="course-bookdisplay-coursename")
        if header_span:
            header_text = header_span.get_text(strip=True)
            m = re.match(
                r"(.+?)\s*-\s*(\S+),\s*section\s+(\S+)\s*(?:\((.+?)\))?",
                header_text,
            )
            if m:
                dept_code = m.group(1).strip()
                course_code = "|" + m.group(2).strip()
                section_name = "|" + m.group(3).strip()
                instructor = m.group(4).strip() if m.group(4) else ""

        sec_key = f"{dept_code}_{course_code}_{section_name}"
        if sec_key in seen_section_ids:
            continue
        seen_section_ids.add(sec_key)

        meta = {}
        for sid, sm in section_meta.items():
            if sm["section"] == section_name and sm["dept_code"] == dept_code:
                meta = sm
                break

        table = h3.find_next_sibling("table", id=re.compile(r"^section-\d+"))
        if not table:
            table = h3.find_next("table", id=re.compile(r"^section-\d+"))

        error_div = h3.find_next_sibling("div", class_="error")
        if error_div and (not table or error_div.sourceline < table.sourceline if hasattr(error_div, 'sourceline') else True):
            results.append({
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": meta.get("course_title", ""),
                "section": section_name,
                "section_instructor": instructor,
                "term": TERM_NAME,
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": "This course does not require any course materials",
            })
            continue

        book_rows = table.find_all("tr", class_=re.compile(r"\bbook\b")) if table else []

        if not book_rows:
            results.append({
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": meta.get("course_title", ""),
                "section": section_name,
                "section_instructor": instructor,
                "term": TERM_NAME,
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": "This course does not require any course materials",
            })
            continue

        section_books = []
        for row in book_rows:
            title = ""
            author = ""
            isbn = ""
            adoption = ""

            title_el = row.find("span", class_="book-title")
            if title_el:
                title = title_el.get_text(strip=True)

            author_el = row.find("span", class_="book-author")
            if author_el:
                author = author_el.get_text(strip=True)

            isbn_el = row.find("span", class_="isbn")
            if isbn_el:
                isbn = isbn_el.get_text(strip=True).replace("-", "")

            req_el = row.find("p", class_="book-req")
            if req_el:
                adoption = req_el.get_text(strip=True).capitalize()

            if title and re.search(r"see instructor|not a book", title, re.I):
                continue

            if title or isbn:
                section_books.append({
                    "department_code": dept_code,
                    "course_code": course_code,
                    "course_title": meta.get("course_title", ""),
                    "section": section_name,
                    "section_instructor": instructor,
                    "term": TERM_NAME,
                    "isbn": isbn,
                    "title": title,
                    "author": author,
                    "material_adoption_code": adoption,
                })

        if section_books:
            results.extend(section_books)
        else:
            results.append({
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": meta.get("course_title", ""),
                "section": section_name,
                "section_instructor": instructor,
                "term": TERM_NAME,
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": "This course does not require any course materials",
            })

    if not results:
        page_text = soup.get_text(" ", strip=True).lower()
        no_materials = ("no course materials" in page_text or
                        "not require" in page_text or
                        "no textbook" in page_text or
                        "no books" in page_text)

        for sid, meta in section_meta.items():
            results.append({
                "department_code": meta["dept_code"],
                "course_code": meta["course_code"],
                "course_title": meta.get("course_title", ""),
                "section": meta["section"],
                "section_instructor": meta["instructor"],
                "term": TERM_NAME,
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": "This course does not require any course materials" if no_materials else "",
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

def normalize_course_code(course_name, dept_code):
    name = course_name.strip()
    if name.upper().startswith(dept_code.upper()):
        name = name[len(dept_code):].strip()
    num_match = re.search(r"[\d].*", name)
    if num_match:
        return "|" + num_match.group(0).strip()
    return "|" + name if name else ""

def normalize_section(section_name):
    name = section_name.strip()
    return "|" + name if name else ""

def clean_term(term_str):
    return re.sub(r'\s*\([^)]*\)', '', term_str).strip()

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_url = BASE_URL + "/"
    term_name = TERM_NAME

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_depts = get_scraped_departments(CSV_PATH)
    if done_depts:
        print(f"[*] {len(done_depts)} departments already scraped: {sorted(done_depts)}")
        print("[*] Will only scrape missing departments.")

    sess, csrf_token = create_session()

    print("[*] Fetching departments...")
    depts = fetch_departments(sess)
    print(f"    Found {len(depts)} departments")

    if not depts:
        print("[!] No departments found. Exiting.")
        return

    total_rows = 0
    all_expected_depts = set(d["dept_code"] for d in depts)
    debug_dumped = False

    for dept in tqdm(depts, desc="Departments"):
        dept_id = dept["dept_id"]
        dept_code = dept["dept_code"]
        dept_name = dept["dept_name"]

        if dept_code in done_depts:
            continue

        try:
            courses = fetch_courses(sess, dept_id)
        except Exception as e:
            print(f"\n  [ERROR] fetch_courses dept={dept_code}: {e}", flush=True)
            try:
                sess, csrf_token = refresh_session(sess)
                courses = fetch_courses(sess, dept_id)
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
            }], CSV_PATH)
            total_rows += 1
            continue

        all_section_ids = []
        section_meta = {}

        for course in courses:
            course_id = course["course_id"]
            course_name = course["course_name"]
            course_code = normalize_course_code(course_name, dept_code)

            try:
                sections = fetch_sections(sess, course_id)
            except Exception as e:
                print(f"\n  [ERROR] fetch_sections {dept_code} {course_name}: {e}", flush=True)
                continue

            for sec in sections:
                sid = sec["section_id"]
                all_section_ids.append(sid)
                section_meta[sid] = {
                    "dept_code": dept_code,
                    "course_code": course_code,
                    "course_title": "",
                    "section": normalize_section(sec["section_name"]),
                    "instructor": sec["instructor"],
                }

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
                    html = fetch_textbooks(sess, batch, csrf_token)

                    if not debug_dumped:
                        debug_path = os.path.join(OUTPUT_DIR, "debug_textbook_express.html")
                        os.makedirs(OUTPUT_DIR, exist_ok=True)
                        with open(debug_path, "w", encoding="utf-8") as df:
                            df.write(html)
                        print(f"\n    [DEBUG] First textbook HTML dumped to {debug_path}", flush=True)
                        debug_dumped = True

                    batch_meta = {sid: section_meta[sid] for sid in batch if sid in section_meta}
                    materials = parse_textbook_html(html, batch_meta)

                    rows = []
                    for row in materials:
                        row["source_url"] = source_url
                        row["school_id"] = SCHOOL_ID
                        row["crawled_on"] = crawled_on
                        rows.append(row)

                    if rows:
                        append_csv(rows, CSV_PATH)
                        dept_rows += len(rows)
                        total_rows += len(rows)

                    break

                except Exception as e:
                    print(f"\n  [!] Batch {batch_idx} attempt {attempt + 1} failed: {e}", flush=True)
                    if attempt < max_retries - 1:
                        sess, csrf_token = refresh_session(sess)
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
