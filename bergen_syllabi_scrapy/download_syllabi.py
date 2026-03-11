#!/usr/bin/env python3

import argparse
import csv
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock

import requests
from playwright.sync_api import sync_playwright


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "Data", "bergen_community_college__3061268__syllabus")
CSV_FILENAME = "bergen_community_college__3061268__syllabus.csv"
CSV_PATH = os.path.join(DATA_DIR, CSV_FILENAME)

LF_BASE = "https://lf.bergen.edu/WebLink"
BROWSE_URL = f"{LF_BASE}/Browse.aspx?id=1&dbid=0&repo=BergenPublic"
SEARCH_API_URL = f"{LF_BASE}/SearchService.aspx/GetSearchListing"
FILE_DOWNLOAD_URL = f"{LF_BASE}/ElectronicFile.aspx"

SEARCH_TEMPLATE = (
    '{{[Syllabus]:[Course_Code]="{course_code}"}}'
    ' & {{LF:LookIn="\\Syllabus"}}'
)

SCHEMA_FIELDS = [
    "school_id", "term_code", "term", "department_code", "department_name",
    "course_code", "course_titel", "section_code", "instructor",
    "syllabus_filename", "syllabus_file_format", "syllabus_filepath_local",
    "syllabus_filesize", "syllabus_file_source_url", "source_url",
    "crawled_on", "downloaded_on",
]

log = logging.getLogger("download_syllabi")


def get_weblink_session_cookie() -> str:
    """Launch headless Chromium, visit Browse.aspx, return WebLinkSession cookie value."""
    log.info("Launching Playwright to obtain WebLinkSession cookie...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(BROWSE_URL, wait_until="networkidle", timeout=30000)
        cookies = context.cookies()
        browser.close()

    for c in cookies:
        if c["name"] == "WebLinkSession":
            log.info("WebLinkSession cookie obtained successfully")
            return c["value"]

    raise RuntimeError(
        "Could not obtain WebLinkSession cookie. "
        "The Laserfiche site may be down or have changed its auth flow."
    )


def build_session(cookie_value: str) -> requests.Session:
    """Build a requests.Session with the WebLinkSession cookie set."""
    s = requests.Session()
    s.cookies.set("WebLinkSession", cookie_value, domain="lf.bergen.edu", path="/")
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/json; charset=utf-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{LF_BASE}/Search.aspx",
        "Origin": "https://lf.bergen.edu",
    })
    return s


def search_course(session: requests.Session, course_code: str) -> list[dict] | None:
    payload = {
        "repoName": "BergenPublic",
        "searchSyn": SEARCH_TEMPLATE.format(course_code=course_code),
        "searchUuid": None,
        "sortColumn": "",
        "startIdx": 0,
        "endIdx": 20,
        "getNewListing": True,
        "sortOrder": 2,
        "displayInGridView": False,
    }
    try:
        resp = session.post(SEARCH_API_URL, json=payload, timeout=30)
        if resp.status_code in (401, 403):
            log.warning(f"Auth error ({resp.status_code}) for {course_code}")
            return None
        resp.raise_for_status()
        data = resp.json()
        inner = data.get("data") or data.get("d") or data
        if isinstance(inner, str):
            inner = json.loads(inner)
        if isinstance(inner, dict):
            return inner.get("results") or inner.get("Results") or []
        if isinstance(inner, list):
            return inner
        return []
    except Exception as e:
        log.error(f"Search failed for {course_code}: {e}")
        return None


def download_file(session: requests.Session, entry_id: int, course_code: str,
                  ext: str, output_dir: str) -> dict | None:
    url = f"{FILE_DOWNLOAD_URL}?docid={entry_id}&dbid=0&repo=BergenPublic"
    try:
        resp = session.get(url, timeout=60, stream=True)
        if resp.status_code in (401, 403):
            log.warning(f"Auth error downloading {course_code} (entry {entry_id})")
            return None
        resp.raise_for_status()

        if not ext:
            ct = resp.headers.get("Content-Type", "").lower()
            if "pdf" in ct:
                ext = "pdf"
            elif "word" in ct or "msword" in ct:
                ext = "docx"
            else:
                ext = "pdf"

        filename = f"{course_code}.{ext}"
        filepath = os.path.join(output_dir, filename)

        size = 0
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                size += len(chunk)

        # Validate the file is actually a PDF (not an HTML error page)
        with open(filepath, "rb") as f:
            head = f.read(8)
        if not head.startswith(b"%PDF"):
            log.warning(f"{course_code}: downloaded file is not a valid PDF ({size:,} bytes), removing")
            os.remove(filepath)
            return None

        log.info(f"Downloaded {filename} ({size:,} bytes)")
        return {
            "filename": filename,
            "ext": ext,
            "filepath": filepath,
            "size": size,
            "source_url": url,
        }
    except Exception as e:
        log.error(f"Download failed for {course_code} (entry {entry_id}): {e}")
        return None


def read_courses(csv_path: str) -> list[dict]:
    """Read the existing catalog CSV into a list of row dicts."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def write_csv(rows: list[dict], csv_path: str):
    """Write updated rows to CSV."""
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in SCHEMA_FIELDS})


def process_course(session: requests.Session, row: dict, output_dir: str,
                   delay: float, lock: Lock, stats: dict) -> dict:
    course_code = row.get("course_code", "").strip()
    if not course_code:
        return row

    time.sleep(delay)

    results = search_course(session, course_code)

    if results is None:

        row["_auth_failed"] = True
        with lock:
            stats["auth_failures"] += 1
        return row

    if not results:
        with lock:
            stats["no_results"] += 1
        log.debug(f"{course_code}: no Laserfiche results")
        return row


    result = results[0]
    entry_id = result.get("entryId") or result.get("EntryId") or result.get("id")
    extension = result.get("extension") or result.get("Extension") or ""
    extension = extension.lstrip(".").lower()

    if not entry_id:
        log.warning(f"{course_code}: result has no entryId")
        with lock:
            stats["no_results"] += 1
        return row

    dl = download_file(session, entry_id, course_code, extension, output_dir)
    if dl:
        row["syllabus_filename"] = dl["filename"]
        row["syllabus_file_format"] = dl["ext"]
        row["syllabus_filepath_local"] = dl["filepath"]
        row["syllabus_filesize"] = str(dl["size"])
        row["syllabus_file_source_url"] = dl["source_url"]
        row["downloaded_on"] = datetime.now(timezone.utc).isoformat()
        with lock:
            stats["downloaded"] += 1
    else:
        with lock:
            stats["download_failed"] += 1

    return row


def main():
    parser = argparse.ArgumentParser(description="Download Bergen CC syllabi from Laserfiche")
    parser.add_argument("--limit", type=int, default=0, help="Max courses to process (0=all)")
    parser.add_argument("--workers", type=int, default=4, help="Parallel download workers")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between API calls (seconds)")
    parser.add_argument("--resume", action="store_true", help="Skip courses with existing files")
    parser.add_argument("--depts", type=str, default="", help="Comma-separated dept filter (e.g. ACC,ENG)")
    parser.add_argument("--csv", type=str, default=CSV_PATH, help="Path to input CSV")
    parser.add_argument("--output-dir", type=str, default=DATA_DIR, help="Output directory for files")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

 
    if not os.path.exists(args.csv):
        log.error(f"CSV not found: {args.csv}")
        log.error("Run the Scrapy spider first: scrapy crawl bergen_syllabi")
        return 1

    rows = read_courses(args.csv)
    log.info(f"Loaded {len(rows)} courses from CSV")


    if args.depts:
        dept_filter = {d.strip().upper() for d in args.depts.split(",") if d.strip()}
        rows = [r for r in rows if r.get("department_code", "").upper() in dept_filter]
        log.info(f"Filtered to {len(rows)} courses in departments: {dept_filter}")

    if args.limit:
        rows = rows[:args.limit]
        log.info(f"Limited to {args.limit} courses")


    os.makedirs(args.output_dir, exist_ok=True)
    if args.resume:
        rows_to_process = []
        rows_done = []
        for r in rows:
            fname = r.get("syllabus_filename", "").strip()
            if fname and os.path.exists(os.path.join(args.output_dir, fname)):
                rows_done.append(r)
            else:
                rows_to_process.append(r)
        log.info(f"Resume: skipping {len(rows_done)} already-downloaded, {len(rows_to_process)} remaining")
    else:
        rows_to_process = rows
        rows_done = []

    if not rows_to_process:
        log.info("Nothing to process")
        return 0


    cookie_value = get_weblink_session_cookie()


    session = build_session(cookie_value)

    stats = {
        "downloaded": 0,
        "no_results": 0,
        "download_failed": 0,
        "auth_failures": 0,
    }
    lock = Lock()
    updated_rows = [None] * len(rows_to_process)
    auth_failed_indices: set[int] = set()

    max_retries = 2
    retry_count = 0

    def run_batch(indices):
        nonlocal session, cookie_value, retry_count
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {}
            for idx in indices:
                row = rows_to_process[idx]
                fut = executor.submit(process_course, session, row, args.output_dir, args.delay, lock, stats)
                futures[fut] = idx

            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    updated_rows[idx] = fut.result()
                except Exception as e:
                    log.error(f"Error processing index {idx}: {e}")
                    updated_rows[idx] = rows_to_process[idx]

        auth_failed_indices.clear()
        for idx in indices:
            row = updated_rows[idx]
            if row and row.pop("_auth_failed", False):
                auth_failed_indices.add(idx)


    all_indices = list(range(len(rows_to_process)))
    run_batch(all_indices)


    while auth_failed_indices and retry_count < max_retries:
        retry_count += 1
        log.warning(f"Retrying {len(auth_failed_indices)} possible auth failures (attempt {retry_count}/{max_retries})")
        stats["auth_failures"] = 0

        cookie_value = get_weblink_session_cookie()
        session = build_session(cookie_value)

        run_batch(list(auth_failed_indices))


    all_rows = read_courses(args.csv)
    processed_map = {}
    for row in (rows_done + [r for r in updated_rows if r]):
        cc = row.get("course_code", "")
        if cc:
            processed_map[cc] = row

    for i, row in enumerate(all_rows):
        cc = row.get("course_code", "")
        if cc in processed_map:
            all_rows[i] = processed_map[cc]


    write_csv(all_rows, args.csv)
    log.info(f"Updated CSV: {args.csv}")

    # Summary
    log.info("=" * 50)
    log.info(f"Downloaded:      {stats['downloaded']}")
    log.info(f"No results:      {stats['no_results']}")
    log.info(f"Download failed: {stats['download_failed']}")
    log.info(f"Auth failures:   {stats['auth_failures']}")
    log.info("=" * 50)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
