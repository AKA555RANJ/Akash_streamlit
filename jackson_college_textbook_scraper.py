import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

SOURCE_URL = "https://www.jccmi.edu/campus-life/jets-store/textbooks/"
SCHOOL_ID  = "3042592"
SCHOOL_NAME = "jackson_college"

CSV_FIELDS = [
    "source_url", "school_id", "department_code", "course_code", "course_title",
    "section", "section_instructor", "term", "isbn", "title", "author",
    "material_adoption_code", "crawled_on", "updated_on",
]

_TERM_HEADING_RE = re.compile(
    r'((?:spring|summer|fall|winter)\s+\d{4})\s+textbooks?',
    re.IGNORECASE,
)

def make_session():
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*",
    })
    return sess

def detect_term(soup):
    for el in soup.find_all(['h1','h2','h3','h4','p','strong']):
        txt = el.get_text(strip=True)
        m = _TERM_HEADING_RE.search(txt)
        if m:
            return m.group(1).upper()
    return "UNKNOWN TERM"

def clean_isbn(raw):
    return re.sub(r'[^0-9X]', '', (raw or '').upper().replace('-', ''))

def clean_code(raw):
    return ('|' + raw.strip()) if raw.strip() else ''

def scrape(session, csv_path=None, fresh=False):
    if csv_path and fresh and os.path.exists(csv_path):
        os.remove(csv_path)
        print("[*] Fresh run — deleted existing CSV.")

    print(f"[*] Fetching {SOURCE_URL} ...")
    resp = session.get(SOURCE_URL, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    term = detect_term(soup)
    print(f"    Term detected: {term}")

    table = soup.find('table')
    if not table:
        print("[!] No table found on page.")
        return []

    rows_html = table.find_all('tr')
    print(f"    Table rows: {len(rows_html) - 1} data rows")

    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    all_rows = []

    for tr in rows_html[1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
        if len(cells) < 9:
            continue

        dept       = cells[0].strip()
        course_num = cells[1].strip()
        section    = cells[2].strip()
        course_title = cells[3].strip()
        content_type = cells[4].strip()
        isbn_raw   = cells[5].strip()
        book_title = cells[6].strip()
        author     = cells[8].strip() if len(cells) > 8 else ""

        if not dept and not course_num:
            continue

        isbn = clean_isbn(isbn_raw)

        row = {
            "source_url":           SOURCE_URL,
            "school_id":            SCHOOL_ID,
            "department_code":      dept,
            "course_code":          clean_code(course_num),
            "course_title":         course_title,
            "section":              clean_code(section),
            "section_instructor":   "",
            "term":                 term,
            "isbn":                 isbn,
            "title":                book_title,
            "author":               author,
            "material_adoption_code": content_type,
            "crawled_on":           crawled_on,
            "updated_on":           crawled_on,
        }
        all_rows.append(row)

    if csv_path:
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        new_file = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
        with open(csv_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerows(all_rows)

    return all_rows

def main():
    parser = argparse.ArgumentParser(
        description="Scrape textbook data from Jackson College (BibliU/HTML table)."
    )
    parser.add_argument("--fresh", action="store_true",
                        help="Delete existing CSV and rescrape from scratch")
    args = parser.parse_args()

    output_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data", f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
    )
    csv_path = os.path.join(output_dir, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")
    print(f"[*] Output: {csv_path}")

    sess = make_session()
    rows = scrape(sess, csv_path=csv_path, fresh=args.fresh)

    print(f"\n[+] Done — {len(rows)} rows written to {csv_path}")
    print(f"    Rows with ISBN    : {sum(1 for r in rows if r.get('isbn'))}")
    print(f"    Rows without ISBN : {sum(1 for r in rows if not r.get('isbn'))}")
    print(f"    Unique ISBNs      : {len({r['isbn'] for r in rows if r.get('isbn')})}")

if __name__ == "__main__":
    main()
