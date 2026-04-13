import csv
import os
import re
import time
import argparse
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SCHOOL_ID = "3061287"
INDEX_URL = "https://www.rcsj.edu/syllabi/gloucester/course-syllabi"
BASE_URL = "https://www.rcsj.edu"

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "rowan_college_of_south_jersey_gloucester_campus__3061287__syllabus",
)
CSV_FILENAME = "rowan_college_of_south_jersey_gloucester_campus__3061287__syllabus.csv"

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

DELAY = 0.3

def normalize_code(raw: str) -> str:
    return raw.strip().replace(" ", "-")

def parse_department_code(code: str) -> str:
    m = re.match(r"([A-Z]+)", code)
    return m.group(1) if m else ""

def parse_index_page(session: requests.Session) -> list[dict]:
    resp = session.get(INDEX_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    entries = []
    current_dept_name = ""

    for el in soup.find_all(["strong", "a"]):
        if el.name == "strong":
            text = el.get_text(strip=True)
            m = re.match(r"[A-Z]{2,5}\s*[-–—]\s*(.+)", text)
            if m:
                current_dept_name = m.group(1).strip()
            continue

        href = el.get("href", "")
        if not href or not href.lower().endswith(".pdf"):
            continue

        link_text = el.get_text(strip=True)
        if not link_text:
            continue

        link_text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", link_text)
        link_text = link_text.replace("\xa0", " ").strip()

        m = re.match(r"([A-Z]{2,5}\s*\d{2,3}[A-Z]?)\s+(.*)", link_text)
        if not m:
            m2 = re.match(r"([A-Z]{2,5}\s*\d{2,3}[A-Z]?)\s*$", link_text)
            if m2:
                raw_code = m2.group(1)
                title = ""
            else:
                m3 = re.match(r"([A-Z]{2,5}\s+\d{2,3}(?:\s*,\s*\d{2,3})*)\s+(.*)", link_text)
                if m3:
                    raw_code = m3.group(1).split(",")[0].strip()
                    title = m3.group(2).strip()
                else:
                    print(f"  [WARN] Could not parse link text: {link_text!r}")
                    continue
        else:
            raw_code = m.group(1)
            raw_code = re.sub(r"([A-Z]+)(\d)", r"\1 \2", raw_code)
            title = m.group(2).strip()
            title = re.sub(r"\s*Gen\s*Ed\s*$", "", title, flags=re.IGNORECASE).strip()

        pdf_url = urljoin(BASE_URL, href)
        code = normalize_code(raw_code)
        dept_code = parse_department_code(code)

        entries.append({
            "raw_code": raw_code,
            "code": code,
            "title": title,
            "department_code": dept_code,
            "department_name": current_dept_name,
            "pdf_url": pdf_url,
        })

    print(f"Found {len(entries)} course syllabi on index page")
    return entries

def download_pdf(session: requests.Session, url: str, filepath: str) -> int:
    resp = session.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    with open(filepath, "wb") as f:
        f.write(resp.content)
    return len(resp.content)

def build_row(
    entry: dict,
    filename: str,
    filesize: int,
    crawled_on: str,
    downloaded_on: str = "",
) -> dict:
    return {
        "school_id": SCHOOL_ID,
        "term_code": "",
        "term": "",
        "department_code": entry["department_code"],
        "department_name": entry["department_name"],
        "course_code": entry["code"],
        "course_titel": entry["title"],
        "section_code": "",
        "instructor": "",
        "syllabus_filename": filename,
        "syllabus_file_format": "pdf",
        "syllabus_filepath_local": (
            f"../data/rowan_college_of_south_jersey_gloucester_campus__{SCHOOL_ID}__syllabus/{filename}"
        ),
        "syllabus_filesize": str(filesize),
        "syllabus_file_source_url": entry["pdf_url"],
        "source_url": INDEX_URL,
        "crawled_on": crawled_on,
        "downloaded_on": downloaded_on or crawled_on,
    }

def main():
    parser = argparse.ArgumentParser(
        description="Scrape RCSJ Gloucester syllabi"
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Only parse the index page; don't download PDFs",
    )
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    session = requests.Session()
    crawled_on = datetime.now(timezone.utc).isoformat()

    entries = parse_index_page(session)
    if not entries:
        print("No course entries found. Aborting.")
        return

    if args.no_download:
        print("--no-download: skipping PDF downloads")
        for e in entries:
            print(f"  {e['code']}: {e['title']}")
        return

    rows: list[dict] = []
    total = len(entries)
    for i, entry in enumerate(entries, 1):
        filename = f"{entry['code']}.pdf"
        filepath = os.path.join(OUTPUT_DIR, filename)

        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            filesize = os.path.getsize(filepath)
            print(f"  [{i}/{total}] {entry['code']} (cached)")
            rows.append(build_row(entry, filename, filesize, crawled_on))
            continue

        print(f"  [{i}/{total}] {entry['code']} (downloading)")
        try:
            filesize = download_pdf(session, entry["pdf_url"], filepath)
            now = datetime.now(timezone.utc).isoformat()
            rows.append(build_row(entry, filename, filesize, crawled_on, now))
        except Exception as e:
            print(f"  [ERROR] Failed to download {entry['code']}: {e}")

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
