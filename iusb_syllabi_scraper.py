#!/usr/bin/env python3
"""
iusb_syllabi_scraper.py — Scrape course syllabi from Indiana University South Bend
(IPEDS 3029187) at https://syllabi.iu.edu/

The site uses a JSON REST API (FOSE framework). We search for all South Bend
Campus sections in Spring 2026 (srcdb=4262), fetch detail pages for syllabus
links, then download Canvas-hosted syllabi as HTML.

Outputs HTML files + a 17-column CSV to:
  data/indiana_university_south_bend__3029187__syllabus/
"""

import csv
import os
import re
import time
import argparse
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHOOL_ID = "3029187"
SOURCE_URL = "https://syllabi.iu.edu/"
API_URL = "https://syllabi.iu.edu/api/?page=fose&route="
SRCDB = "4262"  # Spring 2026
TERM = "Spring 2026"

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "indiana_university_south_bend__3029187__syllabus",
)
CSV_FILENAME = "indiana_university_south_bend__3029187__syllabus.csv"

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
    "Accept": "application/json, text/html, */*",
    "Content-Type": "application/json",
    "Origin": "https://syllabi.iu.edu",
    "Referer": "https://syllabi.iu.edu/",
}

DELAY = 0.5  # seconds between requests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def normalize_code(raw: str) -> str:
    """'AHLT-C 150' → 'AHLT-C-150'"""
    return raw.strip().replace(" ", "-")


def parse_department_code(code: str) -> str:
    """'AHLT-C-150' → 'AHLT-C', 'BUS-A-201' → 'BUS-A', 'ENG-W-131' → 'ENG-W'

    IU uses compound department codes like BUS-A, ENG-W, etc.
    The department is everything before the last numeric segment.
    """
    m = re.match(r"(.+?)-\d+", code)
    return m.group(1) if m else code


def parse_instructor(html: str) -> str:
    """Extract instructor name from instructordetail_html."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    # The HTML typically contains the instructor name in a <a> or plain text
    text = soup.get_text(separator=" ", strip=True)
    # Clean up extra whitespace
    return re.sub(r"\s+", " ", text).strip()


def extract_syllabus_url(html: str) -> str | None:
    """Extract the Canvas syllabus URL from external_syllabi_links HTML."""
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    link = soup.find("a", href=True)
    if link:
        return link["href"]
    return None


# ---------------------------------------------------------------------------
# API Functions
# ---------------------------------------------------------------------------
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def search_sections(session: requests.Session) -> list[dict]:
    """Search for all South Bend Campus sections in the given term."""
    payload = {
        "other": {"srcdb": SRCDB},
        "criteria": [
            {"field": "alias", "value": "*"},
            {"field": "campus", "value": "South Bend Campus"},
        ],
    }
    resp = session.post(
        API_URL + "search",
        json=payload,
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    print(f"Found {len(results)} sections from search API")
    return results


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_section_detail(session: requests.Session, code: str, crn: str) -> dict:
    """Fetch detail for a single section, returning the JSON response."""
    payload = {
        "group": f"code:{code}",
        "key": f"crn:{crn}",
        "srcdb": SRCDB,
        "matched": f"crn:{crn}",
    }
    resp = session.post(
        API_URL + "details",
        json=payload,
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


CANVAS_BASE = "https://iu.instructure.com"


def _canvas_download_url(url: str) -> str:
    """Transform a Canvas file preview URL into a direct download URL.

    '/courses/ID/files/FID?verifier=X&wrap=1'
    → 'https://iu.instructure.com/courses/ID/files/FID/download?verifier=X'
    """
    from urllib.parse import urlparse, parse_qs, urlencode

    parsed = urlparse(url)
    path = parsed.path  # e.g. /courses/123/files/456

    # Insert /download before query string
    if "/download" not in path:
        path = path.rstrip("/") + "/download"

    # Remove wrap=1 from query params, keep verifier
    params = parse_qs(parsed.query)
    params.pop("wrap", None)
    clean_query = urlencode({k: v[0] for k, v in params.items()})

    scheme = parsed.scheme or "https"
    netloc = parsed.netloc or "iu.instructure.com"
    return f"{scheme}://{netloc}{path}?{clean_query}"


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=5))
def _download_url(session: requests.Session, url: str, filepath: str) -> int:
    """Download a URL to filepath. Returns filesize in bytes."""
    # Transform Canvas file URLs to direct download URLs
    if "instructure.com" in url or url.startswith("/courses/"):
        url = _canvas_download_url(url)

    dl_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "*/*",
    }
    resp = session.get(url, headers=dl_headers, timeout=(5, 15), allow_redirects=True)
    # Bail out if we got redirected to SSO login (requires auth, can't download)
    if "idp.login" in resp.url or "login.iu.edu" in resp.url:
        raise RuntimeError(f"Redirected to SSO login: {resp.url}")
    resp.raise_for_status()
    with open(filepath, "wb") as f:
        f.write(resp.content)
    return len(resp.content)


def download_syllabus(session: requests.Session, url: str, filepath: str) -> tuple[int, str, str]:
    """Download a Canvas syllabus page and extract the syllabus content.

    Returns (filesize, actual_filepath, file_format).
    filesize=0 means no content found.
    """
    dl_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml",
    }

    resp = session.get(url, headers=dl_headers, timeout=(5, 15), allow_redirects=True)
    # Bail out if redirected to SSO login
    if "idp.login" in resp.url or "login.iu.edu" in resp.url:
        return 0, filepath, "html"
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")

    # If it's a PDF, save directly
    if "application/pdf" in content_type or url.lower().endswith(".pdf"):
        pdf_path = re.sub(r"\.html$", ".pdf", filepath)
        with open(pdf_path, "wb") as f:
            f.write(resp.content)
        return len(resp.content), pdf_path, "pdf"

    # Otherwise treat as HTML — extract syllabus div
    html = resp.text
    soup = BeautifulSoup(html, "lxml")

    # Try to find the Canvas syllabus content div
    syllabus_div = soup.find("div", id="course_syllabus")

    if syllabus_div:
        # Check if the div has substantial inline text or only file links
        text_content = syllabus_div.get_text(strip=True)
        file_links = syllabus_div.find_all(
            "a", class_="instructure_file_link", href=True
        )

        if len(text_content) < 80 and file_links:
            # The syllabus is a file attachment — download the first file link
            link = file_links[0]
            href = link["href"]
            file_url = href if href.startswith("http") else CANVAS_BASE + href
            title = link.get("title", "")

            # Determine extension from title or URL
            ext = "pdf"  # default
            for e in ("pdf", "docx", "doc", "xlsx", "pptx"):
                if title.lower().endswith(f".{e}") or file_url.lower().endswith(f".{e}"):
                    ext = e
                    break

            file_path = re.sub(r"\.html$", f".{ext}", filepath)
            try:
                size = _download_url(session, file_url, file_path)
                # Verify the actual file type matches extension
                with open(file_path, "rb") as fcheck:
                    magic = fcheck.read(4)
                if ext == "pdf" and magic[:2] == b"PK":
                    # Actually a docx/zip, rename
                    new_path = re.sub(r"\.pdf$", ".docx", file_path)
                    os.rename(file_path, new_path)
                    file_path = new_path
                    ext = "docx"
                return size, file_path, ext
            except Exception as e:
                tqdm.write(f"    [WARN] Could not download linked file: {e}")
                # Fall through to save HTML as-is

        # Only save if div has substantial inline content
        if len(text_content) >= 80:
            content = str(syllabus_div)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return os.path.getsize(filepath), filepath, "html"

    # Fall back to full body
    body = soup.find("body")
    if body and len(body.get_text(strip=True)) > 50:
        content = str(body)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return os.path.getsize(filepath), filepath, "html"

    return 0, filepath, "html"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Scrape IU South Bend syllabi from syllabi.iu.edu"
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Only search sections; don't fetch details or download syllabi",
    )
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    session = requests.Session()
    crawled_on = datetime.now(timezone.utc).isoformat()

    # Step 1: Search for all sections
    sections = search_sections(session)
    if not sections:
        print("No sections found. Aborting.")
        return

    if args.no_download:
        print("--no-download: skipping detail fetches and downloads")
        for s in sections:
            code = normalize_code(s.get("code", ""))
            title = s.get("title", "")
            crn = s.get("crn", "")
            print(f"  {code} (CRN {crn}): {title}")
        return

    # Step 2: For each section, get details and download syllabus
    rows: list[dict] = []
    skipped = 0
    errors = 0
    total = len(sections)

    for section in tqdm(sections, desc="Processing sections", unit="section"):
        raw_code = section.get("code", "")
        crn = section.get("crn", "")
        title = section.get("title", "")
        section_code = section.get("no", "")
        code = normalize_code(raw_code)
        dept_code = parse_department_code(code)

        base_name = f"{code}__{crn}"
        filepath = os.path.join(OUTPUT_DIR, f"{base_name}.html")

        # Resume: skip if already downloaded (check any extension)
        existing = None
        for ext in ("html", "pdf", "docx", "doc"):
            candidate = os.path.join(OUTPUT_DIR, f"{base_name}.{ext}")
            if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
                existing = (candidate, ext)
                break

        if existing:
            ex_path, ex_ext = existing
            filesize = os.path.getsize(ex_path)
            ex_filename = os.path.basename(ex_path)
            rows.append({
                "school_id": SCHOOL_ID,
                "term_code": SRCDB,
                "term": TERM,
                "department_code": dept_code,
                "department_name": "",
                "course_code": code,
                "course_titel": title,
                "section_code": section_code,
                "instructor": "",
                "syllabus_filename": ex_filename,
                "syllabus_file_format": ex_ext,
                "syllabus_filepath_local": f"../data/indiana_university_south_bend__{SCHOOL_ID}__syllabus/{ex_filename}",
                "syllabus_filesize": str(filesize),
                "syllabus_file_source_url": "",
                "source_url": SOURCE_URL,
                "crawled_on": crawled_on,
                "downloaded_on": crawled_on,
            })
            continue

        # Fetch section detail
        try:
            detail = get_section_detail(session, raw_code, crn)
        except Exception as e:
            tqdm.write(f"  [ERROR] Detail fetch failed for {code} CRN {crn}: {e}")
            errors += 1
            time.sleep(DELAY)
            continue

        instructor = parse_instructor(detail.get("instructordetail_html", ""))
        syllabus_url = extract_syllabus_url(detail.get("external_syllabi_links", ""))

        if not syllabus_url:
            skipped += 1
            time.sleep(DELAY)
            continue

        # Download syllabus — returns (filesize, actual_filepath, file_format)
        try:
            filesize, actual_path, file_format = download_syllabus(session, syllabus_url, filepath)
        except Exception as e:
            tqdm.write(f"  [ERROR] Download failed for {code} CRN {crn}: {e}")
            errors += 1
            time.sleep(DELAY)
            continue

        if filesize == 0:
            tqdm.write(f"  [WARN] No syllabus content for {code} CRN {crn}")
            skipped += 1
            # Clean up empty file if created
            if os.path.exists(filepath):
                os.remove(filepath)
            time.sleep(DELAY)
            continue

        filename = os.path.basename(actual_path)
        now = datetime.now(timezone.utc).isoformat()
        rows.append({
            "school_id": SCHOOL_ID,
            "term_code": SRCDB,
            "term": TERM,
            "department_code": dept_code,
            "department_name": "",
            "course_code": code,
            "course_titel": title,
            "section_code": section_code,
            "instructor": instructor,
            "syllabus_filename": filename,
            "syllabus_file_format": file_format,
            "syllabus_filepath_local": f"../data/indiana_university_south_bend__{SCHOOL_ID}__syllabus/{filename}",
            "syllabus_filesize": str(filesize),
            "syllabus_file_source_url": syllabus_url,
            "source_url": SOURCE_URL,
            "crawled_on": crawled_on,
            "downloaded_on": now,
        })

        time.sleep(DELAY)

    # Step 3: Write CSV
    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone! {len(rows)} syllabi saved to {OUTPUT_DIR}")
    print(f"  Skipped (no syllabus): {skipped}")
    print(f"  Errors: {errors}")
    print(f"CSV: {csv_path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
