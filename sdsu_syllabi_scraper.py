#!/usr/bin/env python3
"""
sdsu_syllabi_scraper.py — Scrape 2026 course syllabi from San Diego State University
(IPEDS 2996074) at https://digitalcollections.sdsu.edu/sdsu-syllabus

Three-step approach:
  1. Solve Anubis bot-protection PoW challenge
  2. Collect UUIDs from the filtered listing page for each 2026 semester
  3. For each UUID: fetch metadata JSON, download pages via IIIF, reconstruct PDF

The S3 bucket blocks direct downloads, so we use the Cantaloupe IIIF image
server to fetch individual pages and combine them into PDFs via Pillow.

Outputs PDF files + a 17-column CSV to:
  data/san_diego_state_university__2996074__syllabus/
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote as urlquote

import requests
from bs4 import BeautifulSoup
from PIL import Image
from tenacity import retry, stop_after_attempt, wait_exponential

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHOOL_ID = "2996074"
BASE_URL = "https://digitalcollections.sdsu.edu"
LISTING_URL = f"{BASE_URL}/sdsu-syllabus"
IIIF_BASE = f"{BASE_URL}/cantaloupe/iiif/2"

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "san_diego_state_university__2996074__syllabus",
)
CSV_FILENAME = "san_diego_state_university__2996074__syllabus.csv"

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

# Semesters to check for 2026
SEMESTERS = [
    ("2026 Spring", "S26"),
    ("2026 Winter", "W26"),
    ("2026 Summer", "SU26"),
    ("2026 Fall", "F26"),
]

DELAY = 0.3  # seconds between requests


# ---------------------------------------------------------------------------
# Anubis PoW solver — bypass bot-protection challenge
# ---------------------------------------------------------------------------
def solve_anubis(session: requests.Session) -> None:
    """Solve the Anubis proof-of-work challenge to obtain an auth cookie."""
    print("Solving Anubis bot-protection challenge ...")
    resp = session.get(BASE_URL + "/sdsu-syllabus", timeout=30)
    if resp.status_code != 401:
        print(f"  No challenge needed (status {resp.status_code})")
        return

    soup = BeautifulSoup(resp.text, "lxml")
    challenge_el = soup.find(id="anubis_challenge")
    if not challenge_el:
        raise RuntimeError("Could not find Anubis challenge in page")

    challenge_data = json.loads(challenge_el.get_text())
    challenge = challenge_data["challenge"]
    difficulty = challenge_data["rules"]["difficulty"]
    print(f"  Challenge: {challenge[:16]}... difficulty={difficulty}")

    start = time.time()
    nonce = 0
    while True:
        digest = hashlib.sha256((challenge + str(nonce)).encode()).hexdigest()
        if digest[:difficulty] == "0" * difficulty:
            break
        nonce += 1

    elapsed_ms = int((time.time() - start) * 1000)
    print(f"  Solved! nonce={nonce}, hash={digest[:16]}..., took {elapsed_ms}ms")

    pass_url = (
        f"{BASE_URL}/.within.website/x/cmd/anubis/api/pass-challenge"
        f"?response={digest}&nonce={nonce}"
        f"&redir={BASE_URL}/sdsu-syllabus"
        f"&elapsedTime={elapsed_ms}"
    )
    resp = session.get(pass_url, timeout=30, allow_redirects=False)
    if "within.website-x-cmd-anubis-auth" in session.cookies.get_dict():
        print("  Auth cookie obtained successfully")
    else:
        print(f"  Warning: cookie may not be set (status {resp.status_code})")


# ---------------------------------------------------------------------------
# Step 1: Collect UUIDs from listing pages
# ---------------------------------------------------------------------------
def collect_uuids(session: requests.Session) -> list[tuple[str, str, str]]:
    """Collect (uuid, semester_label, term_code) from filtered listing pages."""
    all_items = []

    for semester_label, term_code in SEMESTERS:
        page = 0
        while True:
            semester_encoded = semester_label.replace(" ", "%20")
            url = f"{LISTING_URL}?f[0]=date_valid_semester:{semester_encoded}"
            if page > 0:
                url += f"&page={page}"

            print(f"  Fetching {semester_label} page {page} ...")
            resp = session.get(url, timeout=30)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "lxml")
            uuid_links = soup.find_all("a", href=re.compile(r"^/do/[0-9a-f\-]{36}$"))

            if not uuid_links:
                if page == 0:
                    print(f"    No results for {semester_label}")
                break

            uuids_on_page = set()
            for link in uuid_links:
                uuid = link["href"].split("/do/")[1]
                uuids_on_page.add(uuid)

            for uuid in uuids_on_page:
                all_items.append((uuid, semester_label, term_code))

            print(f"    Found {len(uuids_on_page)} items on page {page}")

            next_link = soup.find("a", rel="next")
            if not next_link:
                break
            page += 1
            time.sleep(DELAY)

        time.sleep(DELAY)

    # Deduplicate by UUID
    seen = set()
    unique = []
    for item in all_items:
        if item[0] not in seen:
            seen.add(item[0])
            unique.append(item)

    print(f"\nTotal unique UUIDs: {len(unique)}")
    return unique


# ---------------------------------------------------------------------------
# Step 2: Fetch metadata
# ---------------------------------------------------------------------------
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_metadata(session: requests.Session, uuid: str) -> dict:
    """Fetch JSON metadata for a single item."""
    url = f"{BASE_URL}/do/{uuid}?_format=json"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def extract_entry(json_data: dict, uuid: str, semester_label: str, term_code: str) -> dict | None:
    """Extract metadata fields from the JSON response."""
    try:
        meta = json_data["field_descriptive_metadata"][0]["value"]
    except (KeyError, IndexError, TypeError):
        print(f"    WARNING: No metadata for {uuid}")
        return None

    # S3 URL (used as source URL reference, not for download)
    try:
        s3_url = json_data["field_file_drop"][0]["url"]
    except (KeyError, IndexError, TypeError):
        s3_url = ""

    # Extract the S3 path for IIIF identifier
    # URL format: .../media/161/application-filename.pdf?VersionId=...
    # IIIF id: 161%2Fapplication-filename.pdf
    iiif_id = ""
    if s3_url:
        m = re.search(r"/media/([0-9a-fA-F]+/[^?]+)", s3_url)
        if m:
            iiif_id = urlquote(m.group(1), safe="")

    # Course code from partnumber (e.g., "CHEM 100" → "CHEM-100")
    partnumber = meta.get("partnumber", "")
    if isinstance(partnumber, list):
        partnumber = partnumber[0] if partnumber else ""
    course_code = re.sub(r"\s+", "-", partnumber.strip()) if partnumber else ""

    # Department code from partnumber prefix
    dept_code = partnumber.split()[0] if partnumber and " " in partnumber else partnumber

    # Department name
    department = meta.get("department", [])
    dept_name = department[0] if isinstance(department, list) and department else ""

    # Course title
    course_title = meta.get("label", "")

    # Instructor
    instructor = ""
    creator_lod = meta.get("creator_lod", [])
    if isinstance(creator_lod, list) and creator_lod:
        instructor = creator_lod[0].get("name_label", "")

    # Section code
    section_code = ""

    # Page count from metadata
    extent = meta.get("physical_description_extent", "")
    page_count = 0
    if extent:
        m = re.search(r"(\d+)\s*page", extent)
        if m:
            page_count = int(m.group(1))

    # Term from metadata
    date_valid = meta.get("date_valid_semester", semester_label)

    return {
        "uuid": uuid,
        "term_code": term_code,
        "term": date_valid,
        "dept_code": dept_code,
        "department_name": dept_name,
        "course_code": course_code,
        "course_title": course_title,
        "section_code": section_code,
        "instructor": instructor,
        "pdf_url": s3_url,
        "iiif_id": iiif_id,
        "page_count": page_count,
        "source_url": f"{BASE_URL}/do/{uuid}",
    }


# ---------------------------------------------------------------------------
# Step 3: Download via IIIF and reconstruct PDF
# ---------------------------------------------------------------------------
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def download_iiif_page(session: requests.Session, iiif_id: str, page_num: int) -> Image.Image:
    """Download a single page as JPEG via IIIF. Returns a PIL Image."""
    url = f"{IIIF_BASE}/{iiif_id}/full/full/0/default.jpg?page={page_num}"
    resp = session.get(url, timeout=60)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def download_as_pdf(session: requests.Session, iiif_id: str, page_count: int,
                    filepath: str) -> int:
    """Download all pages via IIIF and save as a PDF. Returns filesize."""
    pages = []
    for pg in range(1, page_count + 1):
        img = download_iiif_page(session, iiif_id, pg)
        pages.append(img)
        time.sleep(0.1)  # be gentle

    if not pages:
        raise RuntimeError("No pages downloaded")

    # Save as PDF
    pages[0].save(filepath, "PDF", save_all=True, append_images=pages[1:])
    return os.path.getsize(filepath)


def get_page_count(session: requests.Session, iiif_id: str, metadata_count: int) -> int:
    """Determine actual page count. Use metadata if available, else probe."""
    if metadata_count > 0:
        return metadata_count

    # Probe pages until we get a 404
    count = 0
    for pg in range(1, 200):
        url = f"{IIIF_BASE}/{iiif_id}/info.json?page={pg}"
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            break
        count = pg
        time.sleep(0.05)
    return count if count > 0 else 1


def build_row(
    entry: dict, filename: str, file_format: str, filesize: int,
    crawled_on: str, downloaded_on: str = "",
) -> dict:
    """Build a CSV row dict."""
    return {
        "school_id": SCHOOL_ID,
        "term_code": entry.get("term_code", ""),
        "term": entry.get("term", ""),
        "department_code": entry.get("dept_code", ""),
        "department_name": entry.get("department_name", ""),
        "course_code": entry.get("course_code", ""),
        "course_titel": entry.get("course_title", ""),
        "section_code": entry.get("section_code", ""),
        "instructor": entry.get("instructor", ""),
        "syllabus_filename": filename,
        "syllabus_file_format": file_format,
        "syllabus_filepath_local": (
            f"../data/san_diego_state_university__{SCHOOL_ID}__syllabus/{filename}"
        ),
        "syllabus_filesize": str(filesize),
        "syllabus_file_source_url": entry.get("pdf_url", ""),
        "source_url": entry.get("source_url", ""),
        "crawled_on": crawled_on,
        "downloaded_on": downloaded_on or crawled_on,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
    })
    crawled_on = datetime.now(timezone.utc).isoformat()

    # Solve Anubis bot-protection challenge
    solve_anubis(session)

    # Step 1: Collect UUIDs
    print("\nStep 1: Collecting UUIDs from listing pages ...\n")
    uuid_items = collect_uuids(session)

    if not uuid_items:
        print("No syllabi found for 2026. Exiting.")
        return

    # Step 2: Fetch metadata + download PDFs via IIIF
    print("\nStep 2: Fetching metadata and downloading PDFs via IIIF ...\n")
    rows: list[dict] = []
    downloaded = 0
    cached = 0
    errors = 0
    total = len(uuid_items)

    for i, (uuid, semester_label, term_code) in enumerate(uuid_items, 1):
        # Fetch metadata
        try:
            json_data = fetch_metadata(session, uuid)
        except Exception as e:
            print(f"  [{i}/{total}] ERROR fetching metadata for {uuid}: {e}")
            errors += 1
            continue

        entry = extract_entry(json_data, uuid, semester_label, term_code)
        if not entry or not entry["iiif_id"]:
            print(f"  [{i}/{total}] ERROR: no IIIF ID for {uuid}")
            errors += 1
            continue

        # Build filename: {course_code}__{uuid_first8}.pdf
        uuid_short = uuid[:8]
        cc = entry["course_code"] if entry["course_code"] else "UNKNOWN"
        base_stem = f"{cc}__{uuid_short}"
        base_stem = re.sub(r'[<>:"/\\|?*]', "_", base_stem)
        filename = base_stem + ".pdf"

        # Check for cached file
        filepath = os.path.join(OUTPUT_DIR, filename)
        if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
            filesize = os.path.getsize(filepath)
            cached += 1
            rows.append(build_row(entry, filename, "pdf", filesize, crawled_on))
            print(f"  [{i}/{total}] Cached: {filename}")
            continue

        # Download via IIIF
        try:
            page_count = get_page_count(session, entry["iiif_id"], entry["page_count"])
            print(f"  [{i}/{total}] Downloading {cc} ({page_count} pages) ...")
            filesize = download_as_pdf(session, entry["iiif_id"], page_count, filepath)
            now = datetime.now(timezone.utc).isoformat()
            rows.append(build_row(entry, filename, "pdf", filesize, crawled_on, now))
            downloaded += 1
            print(f"  [{i}/{total}] Saved: {filename} ({filesize:,} bytes)")
        except Exception as e:
            print(f"  [{i}/{total}] ERROR downloading {cc}: {e}")
            errors += 1

        time.sleep(DELAY)

    # Sort by term, department, course
    rows.sort(key=lambda r: (r["term_code"], r["department_code"], r["course_code"]))

    # Write CSV
    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone! {len(rows)} syllabi processed")
    print(f"  Downloaded: {downloaded}")
    print(f"  Cached:     {cached}")
    print(f"  Errors:     {errors}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"CSV:    {csv_path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
