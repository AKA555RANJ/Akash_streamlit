import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

BASE_URL = "https://www.bookstore.sdccd.edu/miramar"
LISTING_URL = BASE_URL + "/buy_courselisting.asp"
XML_URL = BASE_URL + "/textbooks_xml.asp"

SCHOOL_ID = "2996031"
SCHOOL_NAME = "san_diego_miramar_college"

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

# term name from page: "MIRAMAR - MIRAMAR SPRING 2026" → "MIRAMAR SPRING 2026"
def clean_term(raw):
    raw = (raw or "").strip()
    if " - " in raw:
        raw = raw.split(" - ", 1)[1].strip()
    return raw

def make_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*",
        "Referer": LISTING_URL,
    })
    session.get(LISTING_URL)
    return session

def xml_get(session, params, delay=DEFAULT_DELAY):
    time.sleep(delay)
    resp = session.get(XML_URL, params=params)
    resp.raise_for_status()
    return ET.fromstring(resp.text)

def fetch_terms(session):
    resp = session.get(LISTING_URL)
    resp.raise_for_status()
    # Parse terms from <option value="12|342">MIRAMAR - MIRAMAR SPRING 2026</option>
    terms = []
    for m in re.finditer(r'<option[^>]+value="(\d+)\|(\d+)"[^>]*>([^<]+)</option>', resp.text):
        campus_id, term_id, raw_name = m.group(1), m.group(2), m.group(3)
        if campus_id == "0":
            continue
        terms.append((clean_term(raw_name), campus_id, term_id))
    return terms

def fetch_depts(session, campus_id, term_id, delay=DEFAULT_DELAY):
    root = xml_get(session, {"control": "campus", "campus": campus_id, "term": term_id}, delay)
    return [(d.get("abrev", ""), d.get("name", ""), d.get("id", "")) for d in root]

def fetch_courses(session, dept_id, term_id, delay=DEFAULT_DELAY):
    root = xml_get(session, {"control": "department", "dept": dept_id, "term": term_id}, delay)
    return [(c.get("name", ""), c.get("id", "")) for c in root]

def fetch_sections(session, course_id, term_id, delay=DEFAULT_DELAY):
    root = xml_get(session, {"control": "course", "course": course_id, "term": term_id}, delay)
    return [(s.get("name", ""), s.get("instructor", ""), s.get("id", "")) for s in root]

def parse_books_html(html, section_id):
    soup = BeautifulSoup(html, "html.parser")
    books = []
    for tr in soup.select("tr.book-container"):
        classes = tr.get("class", [])
        if "course-required" in classes:
            adoption = "Required Material(s)"
        elif "course-optional" in classes:
            adoption = "Optional Material(s)"
        else:
            req_p = tr.find("p", class_="book-req")
            req_text = req_p.get_text(strip=True).lower() if req_p else ""
            if "required" in req_text:
                adoption = "Required Material(s)"
            elif "optional" in req_text:
                adoption = "Optional Material(s)"
            else:
                adoption = req_text.capitalize() if req_text else ""

        title_span = tr.find("span", class_="book-title")
        author_span = tr.find("span", class_="book-author")
        isbn_input = tr.find("input", class_="product-field-isbn")
        isbn_span = tr.find("span", class_="isbn")

        title = title_span.get_text(strip=True) if title_span else ""
        author = author_span.get_text(strip=True) if author_span else ""

        # Prefer hidden input value, fallback to span text
        raw_isbn = ""
        if isbn_input and isbn_input.get("value"):
            raw_isbn = isbn_input["value"]
        elif isbn_span:
            raw_isbn = isbn_span.get_text(strip=True)

        # Normalize: keep digits and X (ISBN-10 check digit)
        isbn = re.sub(r"[^0-9Xx]", "", raw_isbn).upper()

        if title:
            books.append({
                "source_url": f"{BASE_URL}/textbooks_xml.asp?control=section&section={section_id}",
                "isbn": isbn,
                "title": title,
                "author": author,
                "material_adoption_code": adoption,
            })
    return books

def fetch_books(session, section_id, delay=DEFAULT_DELAY):
    time.sleep(delay)
    resp = session.get(XML_URL, params={"control": "section", "section": section_id})
    resp.raise_for_status()
    return parse_books_html(resp.text, section_id)

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

def scrape(delay=DEFAULT_DELAY, csv_path=None, fresh=False, max_depts=None, term_filter=None):
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
    terms = fetch_terms(session)
    print(f"    Terms: {[t[0] for t in terms]}")

    if not terms:
        print("[!] No terms found.")
        return []

    all_rows = []
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    for term_name, campus_id, term_id in terms:
        if term_filter and term_filter.lower() not in term_name.lower():
            print(f"[*] Skipping term: {term_name}")
            continue

        print(f"\n[*] Fetching departments for term: {term_name}...")
        depts = fetch_depts(session, campus_id, term_id, delay)
        if max_depts:
            depts = depts[:max_depts]
        print(f"    {len(depts)} departments")

        for dept_code, dept_name, dept_id in tqdm(depts, desc=f"  {term_name}"):
            try:
                courses = fetch_courses(session, dept_id, term_id, delay)
            except Exception as exc:
                tqdm.write(f"  [WARN] {dept_code}: fetch_courses failed: {exc}")
                continue

            for course_num, course_id in courses:
                course_code = "|" + course_num

                try:
                    sections = fetch_sections(session, course_id, term_id, delay)
                except Exception as exc:
                    tqdm.write(f"  [WARN] {dept_code} {course_num}: fetch_sections failed: {exc}")
                    continue

                for section_name, instructor, section_id in sections:
                    section = "|" + section_name
                    instructor_clean = re.sub(r",(?!\s)", ", ", instructor).rstrip(",").strip()
                    key = (term_name, dept_code, course_code, section)
                    if key in done_keys:
                        continue

                    try:
                        books = fetch_books(session, section_id, delay)
                    except Exception as exc:
                        tqdm.write(f"  [WARN] section {section_id}: {exc}")
                        books = []

                    base = {
                        "school_id": SCHOOL_ID,
                        "department_code": dept_code,
                        "course_code": course_code,
                        "course_title": "",
                        "section": section,
                        "section_instructor": instructor_clean,
                        "term": term_name,
                        "crawled_on": crawled_on,
                        "updated_on": crawled_on,
                    }

                    src_url = f"{BASE_URL}/textbooks_xml.asp?control=section&section={section_id}"
                    if not books:
                        row = {**base, "source_url": src_url, "isbn": "", "title": "", "author": "", "material_adoption_code": ""}
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
        description="Scrape textbook data from San Diego Miramar College bookstore."
    )
    parser.add_argument("--delay",       type=float, default=DEFAULT_DELAY,
                        help="Seconds between requests (default: 0.5)")
    parser.add_argument("--fresh",       action="store_true",
                        help="Delete existing CSV and rescrape from scratch")
    parser.add_argument("--max-depts",   type=int, default=None,
                        help="Limit departments per term (for sampling/testing)")
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
        max_depts=args.max_depts,
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
        print("[!] No data collected.")

if __name__ == "__main__":
    main()
