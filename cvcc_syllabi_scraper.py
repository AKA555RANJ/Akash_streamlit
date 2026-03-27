#!/usr/bin/env python3

import csv
import os
import re
import time
import argparse
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

SCHOOL_ID = "3106110"
INDEX_URL = "https://www.cvcccoursedocs.com/CourseDocIndex.php"
DETAIL_URL = "https://www.cvcccoursedocs.com/CourseDocIndexDisplay.php"

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "central_virginia_community_college__3106110__syllabus",
)
CSV_FILENAME = "central_virginia_community_college__3106110__syllabus.csv"

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
    "Referer": INDEX_URL,
}

DELAY = 0.5

def normalize_code(raw: str) -> str:
    return raw.strip().replace(" ", "-")

def parse_department(code: str) -> str:
    m = re.match(r"([A-Z]+)", code)
    return m.group(1) if m else ""

def parse_title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for h2 in soup.find_all("h2"):
        text = h2.get_text(strip=True)
        m = re.match(r"[A-Z]{2,4}\s+\d{3}\s*:\s*(.+)", text)
        if m:
            title = m.group(1).strip()
            title = re.sub(r"\s*\([^)]*\)\s*$", "", title)
            return title.strip()
    return ""

def get_course_codes(session: requests.Session) -> list[str]:
    resp = session.get(INDEX_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    inputs = soup.find_all("input", attrs={"name": "CD"})
    codes = [inp["value"] for inp in inputs if inp.get("value")]
    print(f"Found {len(codes)} course codes on index page")
    return codes

def scrape_course(session: requests.Session, raw_code: str, crawled_on: str) -> dict | None:
    code = normalize_code(raw_code)
    filename = f"{code}.html"
    filepath = os.path.join(OUTPUT_DIR, filename)

    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()
        filesize = os.path.getsize(filepath)
        title = parse_title(html)
        return _build_row(code, raw_code, title, filename, filepath, filesize, crawled_on)

    resp = session.post(
        DETAIL_URL,
        data={"CD": raw_code},
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    html = resp.text

    if "Not Acceptable" in html or len(html) < 200:
        print(f"  [WARN] Skipping {code}: got error or empty response")
        return None

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    filesize = os.path.getsize(filepath)
    title = parse_title(html)
    now = datetime.now(timezone.utc).isoformat()

    return _build_row(code, raw_code, title, filename, filepath, filesize, crawled_on, now)

def _build_row(
    code: str,
    raw_code: str,
    title: str,
    filename: str,
    filepath: str,
    filesize: int,
    crawled_on: str,
    downloaded_on: str = "",
) -> dict:
    return {
        "school_id": SCHOOL_ID,
        "term_code": "",
        "term": "",
        "department_code": parse_department(code),
        "department_name": "",
        "course_code": code,
        "course_titel": title,
        "section_code": "",
        "instructor": "",
        "syllabus_filename": filename,
        "syllabus_file_format": "html",
        "syllabus_filepath_local": f"../data/central_virginia_community_college__{SCHOOL_ID}__syllabus/{filename}",
        "syllabus_filesize": str(filesize),
        "syllabus_file_source_url": DETAIL_URL,
        "source_url": INDEX_URL,
        "crawled_on": crawled_on,
        "downloaded_on": downloaded_on or crawled_on,
    }

def main():
    parser = argparse.ArgumentParser(description="Scrape CVCC master course syllabi")
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Only parse the index page; don't download detail pages",
    )
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    session = requests.Session()
    crawled_on = datetime.now(timezone.utc).isoformat()

    course_codes = get_course_codes(session)
    if not course_codes:
        print("No course codes found. Aborting.")
        return

    if args.no_download:
        print("--no-download: skipping detail page downloads")
        for c in course_codes:
            print(f"  {c}")
        return

    rows: list[dict] = []
    total = len(course_codes)
    for i, raw_code in enumerate(course_codes, 1):
        code = normalize_code(raw_code)
        already_exists = os.path.exists(os.path.join(OUTPUT_DIR, f"{code}.html"))
        label = "cached" if already_exists else "downloading"
        print(f"  [{i}/{total}] {code} ({label})")

        row = scrape_course(session, raw_code, crawled_on)
        if row:
            rows.append(row)

        if not already_exists:
            time.sleep(DELAY)

    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone! {len(rows)} syllabi saved to {OUTPUT_DIR}")
    print(f"CSV: {csv_path} ({len(rows)} rows)")

if __name__ == "__main__":
    main()
