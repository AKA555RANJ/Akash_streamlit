#!/usr/bin/env python3
import csv
import os
import re
import time
import argparse
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SCHOOL_ID = "3083372"
SOURCE_URL = "https://my.cedarcrest.edu/ics/staticpages/syllabilist.aspx"

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "cedar_crest_college__3083372__syllabus",
)
CSV_FILENAME = "cedar_crest_college__3083372__syllabus.csv"

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

TERMS_2025_2026 = {
    "202510": "Fall 2025",
    "202520": "Winter 2026",
    "202530": "Spring 2026",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

DOWNLOAD_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "*/*",
    "Referer": SOURCE_URL,
}

DELAY = 0.3

def parse_course_code_cell(raw: str) -> dict:

    parts = raw.split()
    result = {
        "dept_code": "",
        "course_number": "",
        "section_code": "",
        "course_type": "",
    }
    if len(parts) >= 1:
        result["dept_code"] = parts[0]
    if len(parts) >= 2:
        result["course_number"] = parts[1]
    if len(parts) >= 3:
        result["section_code"] = parts[2]
    if len(parts) >= 4:
        result["course_type"] = parts[3]
    return result

def get_file_format(url: str) -> str:

    lower = url.lower()
    if lower.endswith(".pdf"):
        return "pdf"
    elif lower.endswith(".docx"):
        return "docx"
    elif lower.endswith(".doc"):
        return "doc"
    return ""

def filename_from_url(url: str) -> str:

    return url.rsplit("/", 1)[-1]

def get_viewstate(session: requests.Session) -> dict:

    resp = session.get(SOURCE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    fields = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        tag = soup.find("input", {"name": name})
        if tag:
            fields[name] = tag.get("value", "")
    return fields

def scrape_term(session: requests.Session, term_code: str, hidden_fields: dict) -> list[dict]:

    data = dict(hidden_fields)
    data["ddlTerm"] = term_code
    data["btnSubmit"] = "Submit"

    resp = session.post(SOURCE_URL, data=data, headers=HEADERS, timeout=60)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table", class_="InfoNet")
    if not table:
        print(f"  [WARN] No InfoNet table found for term {term_code}")
        return []

    entries = []
    for row in table.find_all("tr", class_=re.compile(r"InfoNet(Item|Alt)")):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        link = cells[0].find("a", href=True)
        if not link:
            continue

        raw_code = link.get_text(strip=True)
        href = link["href"]
        syllabus_url = urljoin(SOURCE_URL, href)

        title = cells[1].get_text(strip=True) if len(cells) > 1 else ""

        instructor = cells[2].get_text(strip=True) if len(cells) > 2 else ""

        file_format = get_file_format(syllabus_url)
        if not file_format:

            print(f"  [SKIP] No valid extension for: {syllabus_url}")
            continue

        parsed = parse_course_code_cell(raw_code)

        entries.append({
            "raw_code": raw_code,
            "dept_code": parsed["dept_code"],
            "course_number": parsed["course_number"],
            "section_code": parsed["section_code"],
            "course_type": parsed["course_type"],
            "title": title,
            "instructor": instructor,
            "syllabus_url": syllabus_url,
            "file_format": file_format,
            "filename": filename_from_url(syllabus_url),
        })

    return entries

def scrape_all_terms(session: requests.Session) -> list[tuple[str, str, dict]]:

    all_entries = []

    for term_code, term_name in TERMS_2025_2026.items():
        print(f"\n=== {term_name} ({term_code}) ===")

        hidden_fields = get_viewstate(session)
        time.sleep(DELAY)

        entries = scrape_term(session, term_code, hidden_fields)
        print(f"  Found {len(entries)} entries")

        for entry in entries:
            all_entries.append((term_code, term_name, entry))

    return all_entries

def download_and_build_rows(
    session: requests.Session,
    all_entries: list[tuple[str, str, dict]],
    crawled_on: str,
    no_download: bool = False,
) -> list[dict]:

    rows = []
    downloaded_urls: dict[str, str] = {}
    total = len(all_entries)

    for i, (term_code, term_name, entry) in enumerate(all_entries, 1):
        url = entry["syllabus_url"]
        filename = entry["filename"]
        filepath = os.path.join(OUTPUT_DIR, filename)

        dept_code = entry["dept_code"]
        course_code = f"{dept_code}-{entry['course_number']}" if entry["course_number"] else dept_code

        already_downloaded = url in downloaded_urls
        already_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0

        if already_downloaded:
            label = "dedup"
        elif already_exists:
            label = "cached"
        else:
            label = "downloading"

        print(f"  [{i}/{total}] {entry['raw_code']} ({label})")

        downloaded_on = ""
        if not no_download and not already_downloaded and not already_exists:
            try:
                resp = session.get(url, headers=DOWNLOAD_HEADERS, timeout=60)
                resp.raise_for_status()
                with open(filepath, "wb") as f:
                    f.write(resp.content)
                downloaded_on = datetime.now(timezone.utc).isoformat()
                time.sleep(DELAY)
            except requests.RequestException as e:
                print(f"    [ERROR] Failed to download: {e}")
                continue

        downloaded_urls[url] = filename

        if already_exists or already_downloaded:
            downloaded_on = crawled_on

        if no_download:
            filesize = 0
        else:
            filesize = os.path.getsize(filepath) if os.path.exists(filepath) else 0

        rows.append({
            "school_id": SCHOOL_ID,
            "term_code": term_code,
            "term": term_name,
            "department_code": dept_code,
            "department_name": "",
            "course_code": course_code,
            "course_titel": entry["title"],
            "section_code": entry["section_code"],
            "instructor": entry["instructor"],
            "syllabus_filename": filename,
            "syllabus_file_format": entry["file_format"],
            "syllabus_filepath_local": f"../data/cedar_crest_college__{SCHOOL_ID}__syllabus/{filename}",
            "syllabus_filesize": str(filesize),
            "syllabus_file_source_url": url,
            "source_url": SOURCE_URL,
            "crawled_on": crawled_on,
            "downloaded_on": downloaded_on or crawled_on,
        })

    return rows

def main():
    parser = argparse.ArgumentParser(
        description="Scrape Cedar Crest College syllabi"
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Only crawl pages and list entries; don't download files",
    )
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    session = requests.Session()
    crawled_on = datetime.now(timezone.utc).isoformat()

    print("=== Scraping Cedar Crest College syllabi ===")
    all_entries = scrape_all_terms(session)
    if not all_entries:
        print("No entries found. Aborting.")
        return

    print(f"\nFound {len(all_entries)} total entries across all terms\n")

    print("=== Downloading files ===")
    rows = download_and_build_rows(session, all_entries, crawled_on, args.no_download)

    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone! {len(rows)} syllabi saved to {OUTPUT_DIR}")
    print(f"CSV: {csv_path} ({len(rows)} rows)")

if __name__ == "__main__":
    main()
