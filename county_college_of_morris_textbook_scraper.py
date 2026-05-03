import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

BASE_URL = "https://bookstore.ccm.edu"
COLLEGE_URL = BASE_URL + "/college"
AJAX_URL = BASE_URL + "/timber/college/ajax"

SCHOOL_ID = "3061276"
SCHOOL_NAME = "county_college_of_morris"

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

DEFAULT_DELAY = 0.3

REQ_MAP = {
    "R":  "Required Material(s)",
    "O":  "Optional Material(s)",
    "C":  "Choose One",
    "CH": "Choose One",
    "P":  "Recommended Material(s)",
    "S":  "Supplementary",
    "CG": "Course Guide",
    "RB": "Required Bundle",
    "OB": "Optional Bundle",
    "RC": "Required Course",
    "OC": "Optional Course",
}

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
        "Accept": "text/html, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": COLLEGE_URL,
    })
    return session

def ajax_get(session, path, delay=DEFAULT_DELAY):
    time.sleep(delay)
    url = AJAX_URL + "?l=" + quote(path, safe="")
    resp = session.get(url)
    resp.raise_for_status()
    return resp.text

def init_session(session):
    resp = session.get(COLLEGE_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    terms = []
    for item in soup.select("div.item.type-college_term a.tcc-item-link"):
        url_attr = item.get("url", "")
        term_name = clean_term(item.get_text(strip=True))
        m = re.search(r"/college_term/(\d+)", url_attr)
        if m and term_name:
            terms.append((term_name, m.group(1)))
    return terms

def fetch_depts(session, term_id, delay=DEFAULT_DELAY):
    html = ajax_get(session, f"/college_term/{term_id}", delay)
    soup = BeautifulSoup(html, "html.parser")
    depts = []
    for item in soup.select("div.item.type-college_dept a.tcc-item-link"):
        url_attr = item.get("url", "")
        m = re.search(r"/college_dept/(\d+)", url_attr)
        if not m:
            continue
        dept_id = m.group(1)
        abbr = item.find("span", class_="abbreviation")
        name = item.find("span", class_="name")
        dept_code = abbr.get_text(strip=True) if abbr else ""
        dept_name = name.get_text(strip=True) if name else ""
        if dept_code:
            depts.append((dept_code, dept_name, dept_id))
    return depts

def fetch_courses(session, dept_id, delay=DEFAULT_DELAY):
    html = ajax_get(session, f"/college_dept/{dept_id}", delay)
    soup = BeautifulSoup(html, "html.parser")
    courses = []
    for item in soup.select("div.item.type-college_course a.tcc-item-link"):
        url_attr = item.get("url", "")
        m = re.search(r"/college_course/(\d+)", url_attr)
        if not m:
            continue
        course_id = m.group(1)
        text = item.get_text(strip=True)
        parts = text.split(" - ", 1)
        course_num = parts[0].strip() if parts else ""
        course_title = parts[1].strip() if len(parts) > 1 else ""
        if course_num:
            courses.append((course_num, course_title, course_id))
    return courses

def fetch_sections(session, course_id, delay=DEFAULT_DELAY):
    html = ajax_get(session, f"/college_course/{course_id}", delay)
    soup = BeautifulSoup(html, "html.parser")
    sections = []
    for item in soup.select("div.item.type-college_section a.tcc-item-link"):
        url_attr = item.get("url", "")
        m = re.search(r"/college_section/(\d+)", url_attr)
        if not m:
            continue
        section_id = m.group(1)
        text = item.get_text(strip=True)
        parts = text.split(" - ", 1)
        section_code = parts[0].strip() if parts else ""
        instructor = " ".join(parts[1].strip().rstrip(",").split()) if len(parts) > 1 else ""
        if section_code:
            sections.append((section_code, instructor, section_id))
    return sections

def parse_books_html(html, section_id):
    soup = BeautifulSoup(html, "html.parser")
    source_url = f"{BASE_URL}/college_section/{section_id}"
    books = []
    for req_div in soup.select("div.req-group"):
        req_letter = ""
        for cls in req_div.get("class", []):
            m = re.match(r"^req-group-([A-Z]+)$", cls)
            if m:
                req_letter = m.group(1)
                break
        adoption_code = REQ_MAP.get(req_letter, req_letter or "")

        for item_div in req_div.select("div.item.group"):
            title_span = item_div.find("span", class_="tcc-product-title")
            author_em = item_div.find("em", class_="author-data")
            sku_span = item_div.find("span", class_="tcc-sku-number")

            title = title_span.get_text(strip=True) if title_span else ""
            author = author_em.get_text(strip=True) if author_em else ""
            raw_isbn = sku_span.get_text(strip=True).strip("()").replace("-", "").strip() if sku_span else ""
            m_isbn = re.match(r"\d+", raw_isbn)
            isbn = m_isbn.group(0) if m_isbn else ""

            books.append({
                "source_url": source_url,
                "isbn": isbn,
                "title": title,
                "author": author,
                "material_adoption_code": adoption_code,
            })
    return books

def fetch_books(session, section_id, delay=DEFAULT_DELAY):
    html = ajax_get(session, f"/college_section/{section_id}", delay)
    return parse_books_html(html, section_id)

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
    terms = init_session(session)
    print(f"    Terms: {[t[0] for t in terms]}")

    if not terms:
        print("[!] No terms found.")
        return []

    all_rows = []
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    for term_name, term_id in terms:
        if term_filter and term_filter.lower() not in term_name.lower():
            print(f"[*] Skipping term: {term_name}")
            continue

        print(f"\n[*] Fetching departments for term: {term_name}...")
        depts = fetch_depts(session, term_id, delay)
        if max_depts:
            depts = depts[:max_depts]
        print(f"    {len(depts)} departments")

        for dept_code, dept_name, dept_id in tqdm(depts, desc=f"  {term_name}"):
            try:
                courses = fetch_courses(session, dept_id, delay)
            except Exception as exc:
                tqdm.write(f"  [WARN] {dept_code}: fetch_courses failed: {exc}")
                continue

            for course_num, course_title, course_id in courses:
                course_code = "|" + course_num

                try:
                    sections = fetch_sections(session, course_id, delay)
                except Exception as exc:
                    tqdm.write(f"  [WARN] {dept_code} {course_num}: fetch_sections failed: {exc}")
                    continue

                for section_code, instructor, section_id in sections:
                    section = "|" + section_code
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
                        "course_title": course_title,
                        "section": section,
                        "section_instructor": instructor,
                        "term": term_name,
                        "crawled_on": crawled_on,
                        "updated_on": crawled_on,
                    }

                    if not books:
                        row = {
                            **base,
                            "source_url": f"{BASE_URL}/college_section/{section_id}",
                            "isbn": "",
                            "title": "",
                            "author": "",
                            "material_adoption_code": "",
                        }
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
        description="Scrape textbook data from County College of Morris bookstore (Timber)."
    )
    parser.add_argument("--delay",       type=float, default=DEFAULT_DELAY,
                        help="Seconds between requests (default: 0.3)")
    parser.add_argument("--fresh",       action="store_true",
                        help="Delete existing CSV and rescrape from scratch")
    parser.add_argument("--max-depts",   type=int, default=None,
                        help="Limit departments per term (for sampling/testing)")
    parser.add_argument("--term-filter", default=None,
                        help="Only scrape terms containing this string (e.g. 'FALL')")
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
