import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

BASE_URL = "https://campusstore.palmer.edu"
COURSE_SEARCH_URL = BASE_URL + "/course-search"
OPTIONS_URL = BASE_URL + "/course-search/options"
BOOKS_URL = BASE_URL + "/course-search/books"

# Store 1 = PCC DAVENPORT (OPEID 3020622, Davenport IA)
STORE_ID = "1"
STORE_NAME = "PCC DAVENPORT"

SCHOOL_ID = "3020622"
SCHOOL_NAME = "palmer_college_of_chiropractic"

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

DEFAULT_DELAY = 0.5

_TERM_SUFFIX_RE = re.compile(
    r"\s*\((?:Order Now|Pre-?Order|Preorder|Coming Soon)[^)]*\)\s*$",
    re.IGNORECASE,
)

def clean_term(term):
    return _TERM_SUFFIX_RE.sub("", (term or "").strip())

def make_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": COURSE_SEARCH_URL,
    })
    # Prime session cookies
    session.get(COURSE_SEARCH_URL)
    return session

def options_post(session, store, term=None, dept=None, course=None, section=None, type_="Term", delay=DEFAULT_DELAY):
    time.sleep(delay)
    data = {
        "data[Store]": store,
        "data[Term]": term or "",
        "data[Department]": dept or "",
        "data[Course]": course or "",
        "data[Section]": section or "",
        "data[Type]": type_,
    }
    resp = session.post(OPTIONS_URL, data=data)
    resp.raise_for_status()
    return resp.json()

def fetch_books(session, store_id, store_name, term_id, term_name, dept_id, dept_name, course_id, course_name, section_id, section_name, delay=DEFAULT_DELAY):
    time.sleep(delay)
    courses_json = json.dumps([{
        "Store":      {"Id": store_id,  "Name": store_name},
        "Term":       {"Id": term_id,   "Name": term_name},
        "Department": {"Id": dept_id,   "Name": dept_name},
        "Course":     {"Id": course_id, "Name": course_name},
        "Section":    {"Id": section_id,"Name": section_name},
    }])
    resp = session.post(BOOKS_URL, data={"coursesJson": courses_json})
    resp.raise_for_status()
    return resp.json()

def parse_adoption(required_flag):
    val = (required_flag or "").strip().upper()
    if val in ("YES", "Y", "REQUIRED", "R"):
        return "Required Material(s)"
    if val in ("NO", "N", "OPTIONAL", "O"):
        return "Optional Material(s)"
    return val or ""

def get_scraped_keys(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return {
            (r.get("term", ""), r.get("department_code", ""), r.get("course_code", ""), r.get("section", ""))
            for r in csv.DictReader(f)
        }

def append_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    new_file = not os.path.exists(filepath) or os.path.getsize(filepath) == 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)

def scrape(delay=DEFAULT_DELAY, csv_path=None, fresh=False, term_filter=None):
    if csv_path and fresh and os.path.exists(csv_path):
        os.remove(csv_path)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys = set()
    if csv_path:
        done_keys = get_scraped_keys(csv_path)
        if done_keys:
            print(f"[*] {len(done_keys)} section/term combos already scraped — resuming.")

    session = make_session()
    print("[*] Initializing session...")

    # Fetch terms
    terms_raw = options_post(session, STORE_ID, type_="Term", delay=delay)
    terms = [(clean_term(v), k) for k, v in terms_raw.items()]
    print(f"    Terms: {[t[0] for t in terms]}")

    if not terms:
        print("[!] No terms found — bookstore may not have populated data yet.")
        return []

    all_rows = []
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    for term_name, term_id in terms:
        if term_filter and term_filter.lower() not in term_name.lower():
            print(f"[*] Skipping term: {term_name}")
            continue

        print(f"\n[*] Fetching departments for term: {term_name}...")
        depts_raw = options_post(session, STORE_ID, term=term_id, type_="Department", delay=delay)
        depts = [(v, k) for k, v in depts_raw.items()]
        print(f"    {len(depts)} departments")

        if not depts:
            print(f"    [!] No departments — term '{term_name}' has no course data loaded yet.")
            continue

        for dept_name, dept_id in tqdm(depts, desc=f"  {term_name}"):
            dept_code = dept_id.split("-")[0] if "-" in dept_id else dept_id

            try:
                courses_raw = options_post(session, STORE_ID, term=term_id, dept=dept_id, type_="Course", delay=delay)
            except Exception as exc:
                tqdm.write(f"  [WARN] {dept_code}: fetch_courses failed: {exc}")
                continue

            for course_name_raw, course_id in courses_raw.items():
                # course_name_raw is like "51903 - Gross Anatomy I"
                parts = course_name_raw.split(" - ", 1)
                course_num = parts[0].strip()
                course_title = parts[1].strip() if len(parts) > 1 else ""
                course_code = "|" + course_num

                try:
                    sections_raw = options_post(session, STORE_ID, term=term_id, dept=dept_id, course=course_id, type_="Section", delay=delay)
                except Exception as exc:
                    tqdm.write(f"  [WARN] {dept_code} {course_num}: fetch_sections failed: {exc}")
                    continue

                for section_name_raw, section_id in sections_raw.items():
                    parts_s = section_name_raw.split(" - ", 1)
                    section_code = "|" + parts_s[0].strip()
                    instructor = " ".join(parts_s[1].strip().rstrip(",").split()) if len(parts_s) > 1 else ""

                    key = (term_name, dept_code, course_code, section_code)
                    if key in done_keys:
                        continue

                    source_url = f"{COURSE_SEARCH_URL}?store={STORE_ID}&term={term_id}&dept={dept_id}&course={course_id}&section={section_id}"

                    try:
                        result = fetch_books(
                            session,
                            STORE_ID, STORE_NAME,
                            term_id, term_name,
                            dept_id, dept_name,
                            course_id, course_name_raw,
                            section_id, section_name_raw,
                            delay=delay,
                        )
                    except Exception as exc:
                        tqdm.write(f"  [WARN] section {section_id}: {exc}")
                        result = []

                    base = {
                        "school_id": SCHOOL_ID,
                        "department_code": dept_code,
                        "course_code": course_code,
                        "course_title": course_title,
                        "section": section_code,
                        "section_instructor": instructor,
                        "term": term_name,
                        "crawled_on": crawled_on,
                        "updated_on": crawled_on,
                    }

                    books = []
                    for entry in (result or []):
                        for book in entry.get("Books", []):
                            isbn_raw = book.get("Isbn") or book.get("Sku") or ""
                            isbn = re.sub(r"[^0-9]", "", isbn_raw)
                            books.append({
                                "source_url": source_url,
                                "isbn": isbn,
                                "title": book.get("Title", ""),
                                "author": book.get("Author", ""),
                                "material_adoption_code": parse_adoption(book.get("Required", "")),
                            })

                    if not books:
                        row = {**base, "source_url": source_url, "isbn": "", "title": "", "author": "", "material_adoption_code": ""}
                        all_rows.append(row)
                        if csv_path:
                            append_csv([row], csv_path)
                    else:
                        rows = [{**base, **b} for b in books]
                        all_rows.extend(rows)
                        if csv_path:
                            append_csv(rows, csv_path)

    return all_rows

def main():
    parser = argparse.ArgumentParser(
        description="Scrape textbook data from Palmer College of Chiropractic bookstore (Campus Web Store)."
    )
    parser.add_argument("--delay",       type=float, default=DEFAULT_DELAY,
                        help="Seconds between requests (default: 0.5)")
    parser.add_argument("--fresh",       action="store_true",
                        help="Delete existing CSV and rescrape from scratch")
    parser.add_argument("--term-filter", default=None,
                        help="Only scrape terms containing this string (e.g. 'SPRING')")
    args = parser.parse_args()

    output_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data",
        f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
    )
    csv_path = os.path.join(output_dir, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")
    print(f"[*] Output: {csv_path}")

    rows = scrape(
        delay=args.delay,
        csv_path=csv_path,
        fresh=args.fresh,
        term_filter=args.term_filter,
    )

    if rows or os.path.exists(csv_path):
        total = (sum(1 for _ in open(csv_path, encoding="utf-8")) - 1) if os.path.exists(csv_path) else len(rows)
        print(f"\n[+] Done — {total} total rows in {csv_path}")
        print(f"    New rows this run : {len(rows)}")
        print(f"    Rows with ISBN    : {sum(1 for r in rows if r.get('isbn'))}")
        print(f"    Rows without ISBN : {sum(1 for r in rows if not r.get('isbn'))}")
        print(f"    Unique ISBNs      : {len({r['isbn'] for r in rows if r.get('isbn')})}")
    else:
        print("[!] No data collected — bookstore may not have populated course adoptions yet.")

if __name__ == "__main__":
    main()
