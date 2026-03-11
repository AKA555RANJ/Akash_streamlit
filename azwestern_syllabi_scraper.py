#!/usr/bin/env python3
"""
azwestern_syllabi_scraper.py — Scrape course syllabi from Arizona Western College
at https://www.azwestern.edu/syllabi

Simple paginated site: GET ?page=0..N, each page has ~20 entries with direct PDF
links. Outputs PDF files + a CSV with 17-column schema to:
  data/arizona_western_college__2990700__syllabus/
"""

import csv
import os
import re
import time
import argparse
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHOOL_ID = "2990700"
BASE_URL = "https://www.azwestern.edu/syllabi"

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "arizona_western_college__2990700__syllabus",
)
CSV_FILENAME = "arizona_western_college__2990700__syllabus.csv"

SCHEMA_FIELDS = [
    "school_id",
    "term_code",
    "term",
    "department_code",
    "department_name",
    "course_code",
    "course_titel",
    "section_code",
    "instructor",
    "syllabus_filename",
    "syllabus_file_format",
    "syllabus_filepath_local",
    "syllabus_filesize",
    "syllabus_file_source_url",
    "source_url",
    "crawled_on",
    "downloaded_on",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

DELAY = 0.3  # seconds between requests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_department(code: str) -> str:
    """'ACC-100' → 'ACC'"""
    m = re.match(r"([A-Z]+)", code)
    return m.group(1) if m else ""


def safe_filename(course_code: str) -> str:
    """Sanitize course code for use as a filename."""
    return re.sub(r"[^\w\-]", "_", course_code)


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------
def scrape_all_pages(session: requests.Session) -> list[dict]:
    """Paginate through all pages and extract syllabus entries."""
    entries = []
    page = 0

    while True:
        url = f"{BASE_URL}?page={page}" if page > 0 else BASE_URL
        print(f"Fetching page {page} ... ", end="", flush=True)
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        page_entries = parse_page(soup, page)

        if not page_entries:
            print("no entries (stopping)")
            break

        entries.extend(page_entries)
        print(f"{len(page_entries)} entries (total: {len(entries)})")

        # Check for "Load More" link to determine if there's a next page
        load_more = soup.find("a", string=re.compile(r"Load\s*More", re.IGNORECASE))
        if not load_more:
            break

        page += 1
        time.sleep(DELAY)

    return entries


def parse_page(soup: BeautifulSoup, page: int) -> list[dict]:
    """Parse a single page and return list of entry dicts with code, title, pdf_url.

    Each entry is a <tr> with:
      - td with <a href="*.pdf"> (download icon)
      - td with <strong><a>Title</a></strong> and <span class="badge">CODE</span>
      - td with <p>description</p>
    """
    entries = []

    for row in soup.find_all("tr"):
        # Find PDF link in the row
        pdf_link = row.find("a", href=re.compile(
            r"/sites/default/files/documents/syllabi/.*\.pdf", re.IGNORECASE
        ))
        if not pdf_link:
            continue

        href = pdf_link["href"]
        pdf_url = href if href.startswith("http") else f"https://www.azwestern.edu{href}"

        # Title: <strong><a>Title</a></strong>
        title = ""
        strong = row.find("strong")
        if strong:
            title_link = strong.find("a")
            title = title_link.get_text(strip=True) if title_link else strong.get_text(strip=True)

        # Course code: <span class="badge ...">CODE</span>
        code = ""
        badge = row.find("span", class_="badge")
        if badge:
            code = badge.get_text(strip=True)

        if not code:
            print(f"  [WARN] Could not parse course code from row with link: {href}")
            continue

        # Normalize: ensure dash between prefix and number
        if re.match(r"^[A-Z]{2,4}\d", code):
            code = re.sub(r"^([A-Z]+)(\d)", r"\1-\2", code)

        entries.append({
            "code": code,
            "title": title,
            "pdf_url": pdf_url,
            "page": page,
        })

    return entries


def download_and_build_rows(
    session: requests.Session,
    entries: list[dict],
    crawled_on: str,
    no_download: bool = False,
) -> list[dict]:
    """Download PDFs and build CSV rows."""
    rows = []
    seen_codes: dict[str, int] = {}
    total = len(entries)

    for i, entry in enumerate(entries, 1):
        code = entry["code"]

        # Handle duplicate course codes
        if code in seen_codes:
            seen_codes[code] += 1
            filename = f"{safe_filename(code)}_{seen_codes[code]}.pdf"
        else:
            seen_codes[code] = 0
            filename = f"{safe_filename(code)}.pdf"

        filepath = os.path.join(OUTPUT_DIR, filename)

        # Resume: skip if already downloaded
        already_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
        label = "cached" if already_exists else "downloading"
        print(f"  [{i}/{total}] {code} ({label})")

        downloaded_on = ""
        if not no_download and not already_exists:
            try:
                resp = session.get(entry["pdf_url"], headers=HEADERS, timeout=60)
                resp.raise_for_status()
                with open(filepath, "wb") as f:
                    f.write(resp.content)
                downloaded_on = datetime.now(timezone.utc).isoformat()
                time.sleep(DELAY)
            except requests.RequestException as e:
                print(f"    [ERROR] Failed to download {code}: {e}")
                continue
        elif already_exists:
            downloaded_on = crawled_on

        if no_download:
            filesize = 0
        else:
            filesize = os.path.getsize(filepath) if os.path.exists(filepath) else 0

        rows.append({
            "school_id": SCHOOL_ID,
            "term_code": "",
            "term": "",
            "department_code": parse_department(code),
            "department_name": "",
            "course_code": code,
            "course_titel": entry["title"],
            "section_code": "",
            "instructor": "",
            "syllabus_filename": filename,
            "syllabus_file_format": "pdf",
            "syllabus_filepath_local": f"../data/arizona_western_college__{SCHOOL_ID}__syllabus/{filename}",
            "syllabus_filesize": str(filesize),
            "syllabus_file_source_url": entry["pdf_url"],
            "source_url": BASE_URL,
            "crawled_on": crawled_on,
            "downloaded_on": downloaded_on or crawled_on,
        })

    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Scrape Arizona Western College syllabi"
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Only crawl pages and list entries; don't download PDFs",
    )
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    session = requests.Session()
    crawled_on = datetime.now(timezone.utc).isoformat()

    # Step 1: scrape all pages
    print("=== Scraping syllabi listing pages ===")
    entries = scrape_all_pages(session)
    if not entries:
        print("No entries found. Aborting.")
        return

    print(f"\nFound {len(entries)} syllabi total\n")

    # Step 2: download PDFs and build CSV rows
    print("=== Downloading PDFs ===")
    rows = download_and_build_rows(session, entries, crawled_on, args.no_download)

    # Step 3: write CSV
    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone! {len(rows)} syllabi saved to {OUTPUT_DIR}")
    print(f"CSV: {csv_path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
