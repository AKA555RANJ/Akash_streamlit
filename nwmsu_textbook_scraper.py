#!/usr/bin/env python3
"""
nwmsu_textbook_scraper.py — Scrape textbook data from
Northwest Missouri State University (Maryville, MO).

Their textbook lookup is a Banner system at ssbprod.nwmissouri.edu.
Plain HTML form POST — no Cloudflare, no authentication needed.

Usage:
    python nwmsu_textbook_scraper.py           # scrape only missing (term, dept) pairs
    python nwmsu_textbook_scraper.py --fresh   # delete CSV and scrape everything
"""

import csv
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHOOL_NAME = "nw_missouri_state_univ"
SCHOOL_ID = "3050213"
BASE_URL = "https://ssbprod.nwmissouri.edu/PROD/"
FORM_URL = BASE_URL + "nwtext.P_Showschedule"
POST_URL = BASE_URL + "nwtext.P_Displaydata"
SOURCE_URL = POST_URL

REQUEST_DELAY = 0.3

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

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

NO_MATERIALS_MSG = "This course does not require any course materials"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def http_get(session, url, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
            else:
                raise


def http_post(session, url, data, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = session.post(url, data=data, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
            else:
                raise


# ---------------------------------------------------------------------------
# Discovery: terms and departments
# ---------------------------------------------------------------------------
def fetch_terms_and_departments(session):
    """GET the form page, parse term and department dropdowns.

    Returns (terms, departments):
        terms: list of (term_code, term_name), e.g. [("202620", "Spring 2026")]
        departments: list of (dept_code, dept_name), e.g. [("ACCT", "Accounting/51")]
    Only active (non-Inactive) terms are returned.
    """
    html = http_get(session, FORM_URL)
    soup = BeautifulSoup(html, "html.parser")

    terms = []
    term_select = soup.find("select", {"name": "term_code"})
    if term_select:
        for opt in term_select.find_all("option"):
            val = opt.get("value", "").strip()
            text = opt.get_text(strip=True)
            if val and "(Inactive)" not in text:
                terms.append((val, text))

    departments = []
    dept_select = soup.find("select", {"name": "subj_code"})
    if dept_select:
        for opt in dept_select.find_all("option"):
            val = opt.get("value", "").strip()
            text = opt.get_text(strip=True)
            if val:
                departments.append((val, text))

    return terms, departments


# ---------------------------------------------------------------------------
# HTML parsing: extract section records from response
# ---------------------------------------------------------------------------
def parse_textbook_response(html, term_name, dept_code):
    """Parse the HTML table from nwtext.P_Displaydata.

    The HTML uses <tr bgcolor="SILVER"> to delimit records (no closing </tr>).
    Each record has a variable number of <td> cells:
      - 7 cells: no book (ends with "No textbook rental")
      - 8 cells: no book (OP campus section with Textbook Finder link)
      - 13 cells: has book data
      - Other counts: may be a header row or malformed — skip

    Returns list of row dicts ready for CSV.
    """
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = []

    # Split HTML by <tr to get individual record chunks
    chunks = re.split(r"<tr\b[^>]*>", html, flags=re.IGNORECASE)

    for chunk in chunks:
        # Extract all <td> cell contents from this chunk
        soup = BeautifulSoup(chunk, "html.parser")
        cells = soup.find_all("td")
        if not cells:
            continue

        cell_texts = [c.get_text(strip=True) for c in cells]
        n = len(cell_texts)

        # Skip header rows (contain "CRN" header)
        if n >= 7 and cell_texts[0] == "CRN":
            continue

        # Skip if first cell doesn't look like a CRN (numeric)
        if not cell_texts[0].isdigit():
            continue

        if n == 7:
            # No book: CRN, Camp, Crse#, Sec, Title, Instructor, "No textbook rental"
            rows.append({
                "source_url": SOURCE_URL,
                "school_id": SCHOOL_ID,
                "department_code": dept_code,
                "course_code": "|" + cell_texts[2],
                "course_title": cell_texts[4],
                "section": "|" + cell_texts[3],
                "section_instructor": cell_texts[5],
                "term": term_name,
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": NO_MATERIALS_MSG,
                "crawled_on": crawled_on,
                "updated_on": crawled_on,
            })
        elif n == 8:
            # OP section with Textbook Finder link: CRN, Camp, Crse#, Sec, Title, Instructor, "", "Textbook Finder"
            rows.append({
                "source_url": SOURCE_URL,
                "school_id": SCHOOL_ID,
                "department_code": dept_code,
                "course_code": "|" + cell_texts[2],
                "course_title": cell_texts[4],
                "section": "|" + cell_texts[3],
                "section_instructor": cell_texts[5],
                "term": term_name,
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": NO_MATERIALS_MSG,
                "crawled_on": crawled_on,
                "updated_on": crawled_on,
            })
        elif n == 13:
            # Has book: CRN, Camp, Crse#, Sec, Title, Instructor, Rental,
            #           BookTitle, Author, Publisher, Edition, ISBN, NumBooks
            rows.append({
                "source_url": SOURCE_URL,
                "school_id": SCHOOL_ID,
                "department_code": dept_code,
                "course_code": "|" + cell_texts[2],
                "course_title": cell_texts[4],
                "section": "|" + cell_texts[3],
                "section_instructor": cell_texts[5],
                "term": term_name,
                "isbn": cell_texts[11],
                "title": cell_texts[7],
                "author": cell_texts[8],
                "material_adoption_code": cell_texts[6] if cell_texts[6] else NO_MATERIALS_MSG,
                "crawled_on": crawled_on,
                "updated_on": crawled_on,
            })
        # else: skip rows with unexpected cell count (navigation, etc.)

    return rows


# ---------------------------------------------------------------------------
# Fetch one department's textbooks
# ---------------------------------------------------------------------------
def fetch_department_textbooks(session, term_code, term_name, dept_code):
    """POST for one (term, department) pair, parse results."""
    form_data = {
        "term_code": term_code,
        "subj_code": dept_code,
        "levl_code": "",
        "ptrm_code": "",
        "attr_code": "",
        "instr_pidm": "",
        "crn": "",
    }
    try:
        html = http_post(session, POST_URL, form_data)
    except Exception as e:
        tqdm.write(f"  [ERROR] {dept_code}/{term_name}: {e}")
        return []

    return parse_textbook_response(html, term_name, dept_code)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
def append_csv(rows, filepath):
    if not rows:
        return
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def get_scraped_departments(filepath):
    """Return set of (term, dept_code) already scraped."""
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    scraped = set()
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            term = row.get("term", "").strip()
            dept = row.get("department_code", "").strip()
            if term and dept:
                scraped.add((term, dept))
    return scraped


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------
def scrape(fresh=False):
    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    already_done = get_scraped_departments(CSV_PATH)
    if already_done:
        print(f"[*] {len(already_done)} (term, dept) pairs already scraped, will skip them.")

    session = requests.Session()

    print("[*] Fetching terms and departments...")
    terms, departments = fetch_terms_and_departments(session)
    print(f"[*] Found {len(terms)} active terms, {len(departments)} departments.")

    if not terms or not departments:
        print("[!] No terms or departments found. Exiting.")
        return

    total_rows = 0
    total_pairs = len(terms) * len(departments)
    skipped = 0

    with tqdm(total=total_pairs, desc="Scraping") as pbar:
        for term_code, term_name in terms:
            for dept_code, dept_name in departments:
                pbar.set_postfix_str(f"{term_name} / {dept_code}")

                if (term_name, dept_code) in already_done:
                    pbar.update(1)
                    skipped += 1
                    continue

                rows = fetch_department_textbooks(session, term_code, term_name, dept_code)
                if rows:
                    append_csv(rows, CSV_PATH)
                    total_rows += len(rows)

                pbar.update(1)

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"Total rows written this run: {total_rows}")
    print(f"Pairs skipped (already done): {skipped}")
    print(f"CSV: {CSV_PATH}")


if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    scrape(fresh=fresh)
