#!/usr/bin/env python3
"""
gsu_perimeter_syllabi_scraper.py — Scrape course syllabi from Georgia State
University - Perimeter College (IPEDS 3017988) at https://cdn.gsu.edu/syllabi/

The site is an Angular SPA backed by static JSON files on a CDN. All course
metadata lives in per-term JSON files, and syllabus PDFs are directly
downloadable from the CDN.

Outputs PDF files + an 18-column CSV to:
  data/georgia_state_university_perimeter_college__3017988__syllabus/
"""

import csv
import os
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHOOL_ID = "3017988"
SOURCE_URL = "https://cdn.gsu.edu/syllabi/"
TERMS_URL = "https://cdn.gsu.edu/static/syllabi-public/terms.json"
TERM_DATA_URL = "https://cdn.gsu.edu/static/syllabi-public/{term_value}.json"
PDF_BASE_URL = "https://cdn.gsu.edu/static/syllabi-public/files/"
COLLEGE_FILTER = "Perimeter College"
YEAR_PREFIX = "2026"

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "georgia_state_university_perimeter_college__3017988__syllabus",
)
CSV_FILENAME = "georgia_state_university_perimeter_college__3017988__syllabus.csv"

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
    "skip_reason",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*",
}

MAX_WORKERS = 8  # concurrent PDF downloads


# ---------------------------------------------------------------------------
# API Functions
# ---------------------------------------------------------------------------
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_terms(session: requests.Session) -> list[dict]:
    """Fetch the list of available terms from the CDN."""
    resp = session.get(TERMS_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("terms", data) if isinstance(data, dict) else data


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_term_data(session: requests.Session, term_value: str) -> dict:
    """Fetch course data for a specific term."""
    url = TERM_DATA_URL.format(term_value=term_value)
    resp = session.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def download_pdf(session: requests.Session, url: str, filepath: str) -> tuple[int, str]:
    """Download a PDF. Returns (filesize, skip_reason)."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=(5, 30))
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
        return len(resp.content), ""
    except Exception as e:
        return 0, f"download_error: {e}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Scrape GSU Perimeter College syllabi from cdn.gsu.edu"
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Only fetch metadata; don't download PDFs",
    )
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    session = requests.Session()
    crawled_on = datetime.now(timezone.utc).isoformat()

    # Step 1: Fetch terms and filter to 2026
    print("Fetching terms...")
    all_terms = fetch_terms(session)
    terms_2026 = [t for t in all_terms if str(t.get("value", "")).startswith(YEAR_PREFIX)]
    print(f"Found {len(terms_2026)} terms for {YEAR_PREFIX}: "
          f"{[t['name'] for t in terms_2026]}")

    if not terms_2026:
        print("No 2026 terms found. Aborting.")
        return

    # Step 2: Fetch course data for each term and filter to Perimeter College
    all_courses: list[dict] = []  # (course_dict, term_code, term_name)

    for term in terms_2026:
        term_value = str(term["value"])
        term_name = term["name"]
        print(f"\nFetching courses for {term_name} ({term_value})...")
        term_data = fetch_term_data(session, term_value)
        courses = term_data.get("courses", [])
        print(f"  Total courses in term: {len(courses)}")

        # Filter: Perimeter College + has syllabus
        filtered = [
            c for c in courses
            if c.get("collegeName") == COLLEGE_FILTER
            and c.get("syllabus")
        ]
        print(f"  Perimeter College with syllabus: {len(filtered)}")

        for c in filtered:
            all_courses.append((c, term_value, term_name))

    print(f"\nTotal syllabi to process: {len(all_courses)}")

    if args.no_download:
        print("\n--no-download: listing courses only")
        for c, term_code, term_name in all_courses:
            subj = c.get("subjectCode", "")
            num = c.get("courseNumber", "")
            crn = c.get("crn", "")
            title = c.get("courseTitle", "")
            print(f"  [{term_code}] {subj}-{num} CRN {crn}: {title}")
        print(f"\nTotal: {len(all_courses)} syllabi across {len(terms_2026)} terms")
        return

    # Step 3: Build download tasks
    download_tasks: list[tuple[str, str, dict]] = []  # (url, filepath, row)
    rows: list[dict] = []

    for course, term_code, term_name in all_courses:
        subj = course.get("subjectCode", "")
        num = course.get("courseNumber", "")
        crn = str(course.get("crn", ""))
        title = course.get("courseTitle", "")
        dept_code = subj
        dept_name = course.get("departmentName", "")
        course_code = f"{subj}-{num}"
        syllabus_path = course.get("syllabus", "")
        instructor_email = course.get("instructorEmail", "")

        filename = f"{course_code}__{crn}.pdf"
        filepath = os.path.join(OUTPUT_DIR, filename)
        pdf_url = PDF_BASE_URL + syllabus_path

        row = {
            "school_id": SCHOOL_ID,
            "term_code": term_code,
            "term": term_name,
            "department_code": dept_code,
            "department_name": dept_name,
            "course_code": course_code,
            "course_titel": title,
            "section_code": crn,
            "instructor": instructor_email,
            "syllabus_filename": filename,
            "syllabus_file_format": "pdf",
            "syllabus_filepath_local": (
                f"../data/georgia_state_university_perimeter_college__{SCHOOL_ID}__syllabus/{filename}"
            ),
            "syllabus_filesize": "",
            "syllabus_file_source_url": pdf_url,
            "source_url": SOURCE_URL,
            "crawled_on": crawled_on,
            "downloaded_on": "",
            "skip_reason": "",
        }

        # Resume: skip already-downloaded files
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            row["syllabus_filesize"] = str(os.path.getsize(filepath))
            row["downloaded_on"] = crawled_on
            rows.append(row)
            continue

        download_tasks.append((pdf_url, filepath, row))

    already = len(all_courses) - len(download_tasks)
    if already:
        print(f"Resuming: {already} already downloaded, {len(download_tasks)} remaining")

    # Step 4: Download PDFs concurrently
    errors = 0
    if download_tasks:
        print(f"\nDownloading {len(download_tasks)} PDFs (workers={MAX_WORKERS})...")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for pdf_url, filepath, row in download_tasks:
                fut = executor.submit(download_pdf, session, pdf_url, filepath)
                futures[fut] = (pdf_url, filepath, row)

            for fut in tqdm(as_completed(futures), total=len(futures),
                            desc="Downloading", unit="pdf"):
                pdf_url, filepath, row = futures[fut]
                filesize, skip_reason = fut.result()
                now = datetime.now(timezone.utc).isoformat()

                if skip_reason:
                    tqdm.write(f"  [ERROR] {os.path.basename(filepath)}: {skip_reason}")
                    row["syllabus_filesize"] = "0"
                    row["skip_reason"] = skip_reason
                    errors += 1
                else:
                    row["syllabus_filesize"] = str(filesize)
                    row["downloaded_on"] = now

                rows.append(row)

    # Step 5: Write CSV (sort by term_code, course_code, section_code)
    rows.sort(key=lambda r: (r["term_code"], r["course_code"], r["section_code"]))

    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    downloaded = sum(1 for r in rows if r["syllabus_filesize"] and r["syllabus_filesize"] != "0" and not r["skip_reason"])
    print(f"\nDone! {len(rows)} total courses processed")
    print(f"  Downloaded: {downloaded}")
    print(f"  Errors: {errors}")
    print(f"CSV: {csv_path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
