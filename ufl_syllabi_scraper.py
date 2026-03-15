#!/usr/bin/env python3
"""
ufl_syllabi_scraper.py — Scrape 2026 course syllabi from University of Florida
(IPEDS 3012766) at https://ufl.simplesyllabus.com/en-US/syllabus-library

Two-phase approach:
  1. Use requests to enumerate all syllabi via the /api2/doc-library-search
     REST endpoint (paginated, 50 per page, ~1628 total for 2026)
  2. Use Playwright to render each syllabus SPA page and save as PDF

The SimpleSyllabus platform is an Angular SPA — syllabus content is rendered
client-side, so we must use a real browser to capture it.

Outputs PDF files + a 17-column CSV to:
  data/university_of_florida__3012766__syllabus/
"""

from __future__ import annotations

import csv
import os
import re
import time
from datetime import datetime, timezone

import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHOOL_ID = "3012766"
SITE_BASE = "https://ufl.simplesyllabus.com"
LIBRARY_URL = f"{SITE_BASE}/en-US/syllabus-library"
SEARCH_API = f"{SITE_BASE}/api2/doc-library-search"

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "university_of_florida__3012766__syllabus",
)
CSV_FILENAME = "university_of_florida__3012766__syllabus.csv"

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

YEAR_FILTER = "2026"
PAGE_SIZE = 50
DELAY = 0.5  # seconds between requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
}


# ---------------------------------------------------------------------------
# Phase 1: Enumerate all syllabi via REST API
# ---------------------------------------------------------------------------
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_search_page(session: requests.Session, page: int) -> dict:
    """Fetch one page from the doc-library-search API."""
    params = {
        "term_statuses[]": "current",
        "page": page,
    }
    resp = session.get(SEARCH_API, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def enumerate_syllabi(session: requests.Session) -> list[dict]:
    """Paginate through the search API and collect all syllabus items."""
    all_items = []
    page = 0

    # First page to get total
    data = fetch_search_page(session, 0)
    total = data["pagination"]["total"]
    items = data["items"]
    all_items.extend(items)
    print(f"  Total syllabi available: {total}")
    print(f"  Page 0: {len(items)} items")

    # Remaining pages
    num_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    for page in tqdm(range(1, num_pages), desc="  Fetching pages", unit="page"):
        data = fetch_search_page(session, page)
        page_items = data["items"]
        if not page_items:
            break
        all_items.extend(page_items)
        time.sleep(DELAY)

    # Filter to 2026 terms only
    filtered = [
        item for item in all_items
        if YEAR_FILTER in item.get("term_name", "")
    ]
    print(f"  After filtering to {YEAR_FILTER}: {len(filtered)} items (from {len(all_items)} total)")
    return filtered


def parse_title(title: str) -> tuple[str, str, str]:
    """Parse SimpleSyllabus title like 'ADV 3001 15772' into
    (department_code, course_code, section_code).

    Returns e.g. ('ADV', 'ADV-3001', '15772').
    Some titles have suffixes like 'DIG 4527C 11405'.
    """
    parts = title.strip().split()
    if len(parts) >= 3:
        dept = parts[0]
        course_num = parts[1]
        section = parts[2]
        # Handle extra parts (e.g., "HLP 6535 HHU THEM 17726")
        if len(parts) > 3:
            section = parts[-1]
        course_code = f"{dept}-{course_num}"
        return dept, course_code, section
    elif len(parts) == 2:
        return parts[0], f"{parts[0]}-{parts[1]}", ""
    else:
        return title, title, ""


# ---------------------------------------------------------------------------
# Phase 2: Download syllabi using Playwright
# ---------------------------------------------------------------------------
def download_syllabi_playwright(items: list[dict], crawled_on: str) -> list[dict]:
    """Use Playwright to render each syllabus page and save as PDF.

    Returns list of CSV row dicts.
    """
    from playwright.sync_api import sync_playwright

    rows: list[dict] = []
    downloaded = 0
    cached = 0
    errors = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
        )

        for item in tqdm(items, desc="Downloading syllabi", unit="syllabus"):
            code = item["code"]
            title = item.get("title", "")
            subtitle = item.get("subtitle", "")
            term_name = item.get("term_name", "")
            term_id = item.get("term_id", "")
            editors = item.get("editors", [])

            dept_code, course_code, section_code = parse_title(title)

            # Primary instructor (first editor)
            instructor = ""
            if editors:
                instructor = editors[0].get("full_name", "")

            # Build filename: {COURSE_CODE}__{first8chars_of_code}.pdf
            code_short = code[:8]
            safe_cc = re.sub(r'[<>:"/\\|?*\s]', "_", course_code)
            base_stem = f"{safe_cc}__{code_short}"
            filename = f"{base_stem}.pdf"
            filepath = os.path.join(OUTPUT_DIR, filename)

            # Resume: skip if already downloaded
            if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
                filesize = os.path.getsize(filepath)
                cached += 1
                rows.append(_build_row(
                    dept_code, course_code, section_code, subtitle,
                    instructor, term_name, term_id, code,
                    filename, "pdf", filesize, crawled_on, crawled_on,
                ))
                continue

            # Render syllabus page as PDF
            syllabus_url = f"{SITE_BASE}/en-US/doc/{code}/syllabus"
            try:
                page = context.new_page()
                page.goto(syllabus_url, wait_until="networkidle", timeout=30000)
                # Wait for Angular to render content
                try:
                    page.wait_for_selector(
                        "app-doc-viewer, .doc-content, .syllabus-content, main",
                        timeout=10000,
                    )
                except Exception:
                    pass
                # Small extra wait for dynamic content
                time.sleep(1)

                page.pdf(path=filepath, format="Letter", print_background=True)
                page.close()

                filesize = os.path.getsize(filepath)
                if filesize < 5000:
                    # Too small — likely an empty/error page
                    tqdm.write(f"  [WARN] {course_code}: PDF too small ({filesize} bytes), keeping anyway")

                now = datetime.now(timezone.utc).isoformat()
                downloaded += 1
                rows.append(_build_row(
                    dept_code, course_code, section_code, subtitle,
                    instructor, term_name, term_id, code,
                    filename, "pdf", filesize, crawled_on, now,
                ))

            except Exception as e:
                tqdm.write(f"  [ERROR] {course_code} ({code}): {e}")
                errors += 1
                try:
                    page.close()
                except Exception:
                    pass

        browser.close()

    print(f"\n  Downloaded: {downloaded}")
    print(f"  Cached:     {cached}")
    print(f"  Errors:     {errors}")
    return rows


def _build_row(
    dept_code: str, course_code: str, section_code: str, course_title: str,
    instructor: str, term_name: str, term_id: str, code: str,
    filename: str, file_format: str, filesize: int,
    crawled_on: str, downloaded_on: str,
) -> dict:
    """Build a CSV row dict."""
    return {
        "school_id": SCHOOL_ID,
        "term_code": term_id,
        "term": term_name,
        "department_code": dept_code,
        "department_name": "",
        "course_code": course_code,
        "course_titel": course_title,
        "section_code": section_code,
        "instructor": instructor,
        "syllabus_filename": filename,
        "syllabus_file_format": file_format,
        "syllabus_filepath_local": (
            f"../data/university_of_florida__{SCHOOL_ID}__syllabus/{filename}"
        ),
        "syllabus_filesize": str(filesize),
        "syllabus_file_source_url": f"{SITE_BASE}/en-US/doc/{code}/syllabus",
        "source_url": LIBRARY_URL,
        "crawled_on": crawled_on,
        "downloaded_on": downloaded_on,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    crawled_on = datetime.now(timezone.utc).isoformat()

    # Phase 1: Enumerate syllabi via REST API
    print("Phase 1: Enumerating syllabi via API ...\n")
    session = requests.Session()
    session.headers.update(HEADERS)

    items = enumerate_syllabi(session)
    if not items:
        print("No 2026 syllabi found. Exiting.")
        return

    # Show term breakdown
    term_counts: dict[str, int] = {}
    for item in items:
        t = item.get("term_name", "Unknown")
        term_counts[t] = term_counts.get(t, 0) + 1
    print("\n  Term breakdown:")
    for t, c in sorted(term_counts.items()):
        print(f"    {t}: {c}")

    # Phase 2: Download syllabi with Playwright
    print(f"\nPhase 2: Downloading {len(items)} syllabi with Playwright ...\n")
    rows = download_syllabi_playwright(items, crawled_on)

    # Sort by term, department, course
    rows.sort(key=lambda r: (r["term"], r["department_code"], r["course_code"]))

    # Write CSV
    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone! {len(rows)} syllabi processed")
    print(f"Output: {OUTPUT_DIR}")
    print(f"CSV:    {csv_path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
