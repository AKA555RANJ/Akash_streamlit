import csv
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

SCHOOL_NAME = "saint_louis_community_college"
SCHOOL_ID = "3050288"
BASE_URL = "https://stlcc.textbookx.com"
BROWSE_URL = BASE_URL + "/institutional/index.php?action=browse"
DEPTS_URL = BASE_URL + "/tools/ajax/misc_ajax.php/getDepartmentsAndCourses/{id}"
BOOKS_URL = BASE_URL + "/institutional/tool.php?action=books&cid={cid}&jsonRequest=true"

REQUEST_DELAY = 0.5

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

ADOPTION_MAP = {
    "req": "Required",
    "opt": "Optional",
    "rec": "Recommended",
    "ch": "Choice",
    "not_using_books": "Not Using Books",
    "oer_materials": "OER Materials",
    "non_bookstore_materials": "Non-Bookstore Materials",
}

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")

def make_session():
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "X-Requested-With": "XMLHttpRequest",
        "Referer": BROWSE_URL,
    })
    return sess

def discover_terms(sess):
    resp = sess.get(BROWSE_URL, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    term_select = soup.find("select", {"id": "npm-tree-term-selector"})
    if not term_select:
        raise RuntimeError("Could not find npm-tree-term-selector on browse page")

    terms = []
    for opt in term_select.find_all("option"):
        val = (opt.get("value") or "").strip()
        text = opt.get_text(strip=True)
        if not val or "2026" not in text:
            continue
        term_name = clean_term(text).upper()
        terms.append({"term_id": val, "term_name": term_name})

    if not terms:
        available = [o.get_text(strip=True) for o in term_select.find_all("option")]
        raise RuntimeError(f"No 2026 terms found. Available: {available}")

    print(f"[*] Found {len(terms)} 2026 term(s): {[t['term_name'] for t in terms]}")
    return terms

def get_children(sess, node_id, level, retries=3):
    url = DEPTS_URL.format(id=node_id)
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            r = sess.post(url, data={"department_level": level, "is_saved_courses": "true"}, timeout=20)
            r.raise_for_status()
            data = r.json()
            return data.get("departments", []), data.get("courses", [])
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] get_children id={node_id} level={level} attempt {attempt+1}: {e}", flush=True)
                time.sleep(2 * (attempt + 1))
            else:
                raise

def get_books(sess, course_id, retries=4):
    url = BOOKS_URL.format(cid=course_id)
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            r = sess.get(url, timeout=20)
            if r.status_code == 403:
                return None
            if r.status_code == 429:
                wait = 60 * (attempt + 1)
                print(f"  [WARN] 429 rate-limited — sleeping {wait}s (attempt {attempt+1})", flush=True)
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            return data.get("course_data", {})
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] get_books cid={course_id} attempt {attempt+1}: {e}", flush=True)
                time.sleep(5 * (attempt + 1))
            else:
                print(f"  [ERROR] get_books cid={course_id} gave up: {e}", flush=True)
                return {}
    return {}

def parse_course_code(code_str):
    parts = code_str.strip().split(None, 1)
    if len(parts) == 2:
        return parts[0], "|" + parts[1]
    return code_str, ""

def clean_term(term_str):
    return re.sub(r'\s*\([^)]*\)', '', term_str or "").strip()

def fmt_section(section_str):
    s = (section_str or "").strip()
    return "|" + s if s else ""

def adoption_label(book_type):
    return ADOPTION_MAP.get((book_type or "").lower(), (book_type or "").capitalize())

def clean_text(value):
    if not value:
        return value
    return value.replace("\ufffd", "").strip()

def build_rows(course_data_map, crawled_on):
    rows = []
    for cid, entry in course_data_map.items():
        if not cid:
            continue
        course = entry.get("course", {})
        books = entry.get("books", [])

        code_str = course.get("code", "")
        dept_code, course_code = parse_course_code(code_str)
        course_title = clean_text(course.get("name", ""))
        section = fmt_section(course.get("section", ""))
        instructor = clean_text(course.get("fullname", ""))
        term_name = clean_term(course.get("term_name", "")).upper()
        books_required = course.get("books_required", True)

        if not books:
            msg = course.get("no_books_required_reason") or "This course does not require any course materials"
            rows.append({
                "source_url": BROWSE_URL,
                "school_id": SCHOOL_ID,
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": course_title,
                "section": section,
                "section_instructor": instructor,
                "term": term_name,
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": msg if not books_required else "This course does not require any course materials",
                "crawled_on": crawled_on,
                "updated_on": crawled_on,
            })
        else:
            for book in books:
                isbn = (book.get("isbn") or "").replace("-", "").strip()
                rows.append({
                    "source_url": BROWSE_URL,
                    "school_id": SCHOOL_ID,
                    "department_code": dept_code,
                    "course_code": course_code,
                    "course_title": course_title,
                    "section": section,
                    "section_instructor": instructor,
                    "term": term_name,
                    "isbn": isbn,
                    "title": clean_text(book.get("title", "")),
                    "author": clean_text(book.get("author", "")),
                    "material_adoption_code": adoption_label(book.get("book_type", "")),
                    "crawled_on": crawled_on,
                    "updated_on": crawled_on,
                })
    return rows

def append_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

def get_scraped_course_ids(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()

    scraped = set()
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (
                row.get("term", "").strip(),
                row.get("department_code", "").strip(),
                row.get("course_code", "").strip(),
                row.get("section", "").strip(),
            )
            if any(key):
                scraped.add(key)
    return scraped

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys = get_scraped_course_ids(CSV_PATH)
    if done_keys:
        print(f"[*] {len(done_keys)} (term, dept, course, section) combos already scraped.")

    sess = make_session()

    print("[*] Fetching 2026 terms from browse page...")
    terms = discover_terms(sess)

    grand_total = 0
    debug_dumped = False

    for term in terms:
        term_id = term["term_id"]
        term_name = term["term_name"]

        print(f"\n{'='*60}")
        print(f"TERM: {term_name}  (id={term_id})")
        print(f"{'='*60}")

        campuses, _ = get_children(sess, term_id, level=1)
        print(f"[*] {len(campuses)} campus(es): {[c['name'] for c in campuses]}")

        term_total = 0
        last_navigated_dept_id = None

        for campus in tqdm(campuses, desc=f"Campuses [{term_name}]"):
            campus_id = campus["id"]
            campus_name = campus["name"]

            depts, _ = get_children(sess, campus_id, level=2)
            if not depts:
                continue

            for dept in tqdm(depts, desc=f"  Depts [{campus_name}]", leave=False):
                dept_id = dept["id"]
                dept_display = dept["name"]

                try:
                    _, courses = get_children(sess, dept_id, level=3)
                    last_navigated_dept_id = dept_id
                except Exception as e:
                    print(f"\n  [ERROR] get_children dept={dept_display}: {e}", flush=True)
                    continue

                if not courses:
                    continue

                for course in courses:
                    course_id = str(course.get("id") or course.get("user_name") or "")
                    if not course_id:
                        continue

                    code_str_pre = course.get("code", "")
                    dept_code_pre, course_code_pre = parse_course_code(code_str_pre)
                    section_pre = fmt_section(course.get("section", ""))
                    if (term_name, dept_code_pre, course_code_pre, section_pre) in done_keys:
                        continue

                    try:
                        course_data = get_books(sess, course_id)
                    except Exception as e:
                        print(f"\n  [ERROR] get_books course_id={course_id}: {e}", flush=True)
                        continue

                    if course_data is None:

                        try:
                            if last_navigated_dept_id != dept_id:
                                get_children(sess, dept_id, level=3)
                                last_navigated_dept_id = dept_id
                                time.sleep(1.0)
                            course_data = get_books(sess, course_id)
                        except Exception:
                            course_data = None

                    if course_data is None or not course_data:
                        continue

                    rows = build_rows(course_data, crawled_on)

                    if not debug_dumped and rows:
                        import json
                        debug_path = os.path.join(OUTPUT_DIR, "debug_first_course.json")
                        os.makedirs(OUTPUT_DIR, exist_ok=True)
                        with open(debug_path, "w", encoding="utf-8") as df:
                            json.dump(course_data, df, indent=2)
                        print(f"\n    [DEBUG] First course JSON dumped to {debug_path}", flush=True)
                        debug_dumped = True

                    if rows:
                        append_csv(rows, CSV_PATH)
                        term_total += len(rows)
                        grand_total += len(rows)
                        for row in rows:
                            key = (row["term"], row["department_code"], row["course_code"], row["section"])
                            done_keys.add(key)

        print(f"\n[*] Term {term_name}: {term_total} rows written.")

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"Total rows written: {grand_total}")
    print(f"CSV: {CSV_PATH}")

if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    scrape(fresh=fresh)
