#!/usr/bin/env python3
"""
iupui_syllabi_scraper.py — Scrape course syllabi from Indiana University-Purdue
University-Indianapolis (IPEDS 3029192) at https://syllabi.iu.edu/

The site uses a JSON REST API (FOSE framework). We search for all Indianapolis
Campus sections in Spring 2026 (srcdb=4262), fetch detail pages for syllabus
links, then download Canvas-hosted syllabi as HTML.

Outputs HTML files + a 18-column CSV to:
  data/indiana_university_purdue_university_indianapolis__3029192__syllabus/
"""

import csv
import hashlib
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
SCHOOL_ID = "3029192"
SOURCE_URL = "https://syllabi.iu.edu/"
API_URL = "https://syllabi.iu.edu/api/?page=fose&route="
SRCDB = "4262"  # Spring 2026
TERM = "Spring 2026"

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "indiana_university_purdue_university_indianapolis__3029192__syllabus",
)
CSV_FILENAME = "indiana_university_purdue_university_indianapolis__3029192__syllabus.csv"

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


def file_md5(filepath: str) -> str:
    """Compute MD5 hex digest of a file."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# API Functions
# ---------------------------------------------------------------------------
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def search_sections(session: requests.Session, campus_filter: str = "Indianapolis Campus") -> list[dict]:
    """Search for all sections matching the campus filter in the given term."""
    criteria = [{"field": "alias", "value": "*"}]
    if campus_filter:
        criteria.append({"field": "campus", "value": campus_filter})
    payload = {
        "other": {"srcdb": SRCDB},
        "criteria": criteria,
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
    print(f"Found {len(results)} sections from search API (campus={campus_filter!r})")
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
def _download_url(session: requests.Session, url: str, filepath: str) -> tuple[int, str]:
    """Download a URL to filepath. Returns (filesize, skip_reason).

    skip_reason is '' on success, 'sso_auth_required' if redirected to SSO.
    """
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
        return 0, "sso_auth_required"
    resp.raise_for_status()
    with open(filepath, "wb") as f:
        f.write(resp.content)
    return len(resp.content), ""


def download_syllabus(session: requests.Session, url: str, filepath: str) -> tuple[int, str, str, str]:
    """Download a Canvas syllabus page and extract the syllabus content.

    Returns (filesize, actual_filepath, file_format, skip_reason).
    filesize=0 means no content found; skip_reason explains why.
    """
    dl_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml",
    }

    resp = session.get(url, headers=dl_headers, timeout=(5, 15), allow_redirects=True)
    # Bail out if redirected to SSO login
    if "idp.login" in resp.url or "login.iu.edu" in resp.url:
        return 0, filepath, "html", "sso_auth_required"
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")

    # If it's a PDF, save directly
    if "application/pdf" in content_type or url.lower().endswith(".pdf"):
        pdf_path = re.sub(r"\.html$", ".pdf", filepath)
        with open(pdf_path, "wb") as f:
            f.write(resp.content)
        return len(resp.content), pdf_path, "pdf", ""

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
                size, skip = _download_url(session, file_url, file_path)
                if skip:
                    return 0, file_path, ext, skip
                # Verify the actual file type matches extension
                with open(file_path, "rb") as fcheck:
                    magic = fcheck.read(4)
                if ext == "pdf" and magic[:2] == b"PK":
                    # Actually a docx/zip, rename
                    new_path = re.sub(r"\.pdf$", ".docx", file_path)
                    os.rename(file_path, new_path)
                    file_path = new_path
                    ext = "docx"
                return size, file_path, ext, ""
            except Exception as e:
                tqdm.write(f"    [WARN] Could not download linked file: {e}")
                # Fall through to save HTML as-is

        # Only save if div has substantial inline content
        if len(text_content) >= 80:
            content = str(syllabus_div)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return os.path.getsize(filepath), filepath, "html", ""

    # Fall back to full body
    body = soup.find("body")
    if body and len(body.get_text(strip=True)) > 50:
        content = str(body)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return os.path.getsize(filepath), filepath, "html", ""

    return 0, filepath, "html", "no_content"


# ---------------------------------------------------------------------------
# Probe mode
# ---------------------------------------------------------------------------
def run_probe(session: requests.Session, targets: list[str]):
    """Diagnostic mode: check specific CODE:CRN pairs against the API.

    Each target is "COURSE_CODE:CRN", e.g. "AHLT-C 150:17751".
    """
    print("=== PROBE MODE ===\n")

    # Parse targets
    parsed = []
    for t in targets:
        if ":" not in t:
            print(f"[ERROR] Invalid probe target (expected CODE:CRN): {t!r}")
            continue
        code, crn = t.rsplit(":", 1)
        parsed.append((code.strip(), crn.strip()))

    if not parsed:
        print("No valid targets to probe.")
        return

    # Step 1: Search with Indianapolis Campus filter
    print("--- Searching with campus='Indianapolis Campus' ---")
    sb_results = search_sections(session, campus_filter="Indianapolis Campus")
    sb_crns = {r.get("crn", ""): r for r in sb_results}

    # Step 2: Search without campus filter (broader)
    print("\n--- Searching without campus filter ---")
    all_results = search_sections(session, campus_filter="")
    all_crns = {r.get("crn", ""): r for r in all_results}

    for code, crn in parsed:
        print(f"\n{'='*60}")
        print(f"Probing: {code} (CRN {crn})")
        print(f"{'='*60}")

        # Check in Indianapolis results
        if crn in sb_crns:
            r = sb_crns[crn]
            print(f"  FOUND in Indianapolis search: code={r.get('code')!r}, title={r.get('title')!r}")
        else:
            print(f"  NOT FOUND in Indianapolis search results")

        # Check in all-campus results
        if crn in all_crns:
            r = all_crns[crn]
            campus_val = r.get("campus", "(no campus field)")
            print(f"  FOUND in all-campus search: code={r.get('code')!r}, title={r.get('title')!r}, campus={campus_val!r}")
        else:
            print(f"  NOT FOUND in all-campus search results either")
            print(f"  → This CRN does not exist in srcdb={SRCDB}")
            continue

        # Fetch detail
        raw_code = all_crns[crn].get("code", code)
        print(f"\n  Fetching detail for code={raw_code!r}, crn={crn} ...")
        try:
            detail = get_section_detail(session, raw_code, crn)
        except Exception as e:
            print(f"  [ERROR] Detail fetch failed: {e}")
            continue

        ext_links = detail.get("external_syllabi_links", "")
        print(f"  external_syllabi_links: {ext_links!r}")

        syllabus_url = extract_syllabus_url(ext_links)
        if not syllabus_url:
            print(f"  → No syllabus link found in detail response")
            continue

        print(f"  Syllabus URL: {syllabus_url}")

        # Attempt download to temp location
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            filesize, actual_path, fmt, skip_reason = download_syllabus(session, syllabus_url, tmp_path)
            if skip_reason:
                print(f"  → Download skipped: {skip_reason}")
            elif filesize == 0:
                print(f"  → Download returned 0 bytes (no content)")
            else:
                print(f"  → Downloaded OK: {filesize} bytes, format={fmt}")
                if os.path.exists(actual_path):
                    md5 = file_md5(actual_path)
                    print(f"  → MD5: {md5}")
        except Exception as e:
            print(f"  → Download error: {e}")
        finally:
            # Clean up temp files
            for p in (tmp_path, tmp_path.replace(".html", ".pdf"),
                       tmp_path.replace(".html", ".docx")):
                if os.path.exists(p):
                    os.remove(p)

        time.sleep(DELAY)

    print(f"\n{'='*60}")
    print("Probe complete.")


# ---------------------------------------------------------------------------
# Dedup mode
# ---------------------------------------------------------------------------
def run_dedup():
    """Scan output directory, find duplicate files by content hash, keep canonical copy."""
    print("=== DEDUP MODE ===\n")

    if not os.path.isdir(OUTPUT_DIR):
        print(f"Output directory not found: {OUTPUT_DIR}")
        return

    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)

    # Hash all syllabus files (exclude the CSV itself)
    hash_to_files: dict[str, list[str]] = {}
    for fname in sorted(os.listdir(OUTPUT_DIR)):
        if fname == CSV_FILENAME or fname.startswith("."):
            continue
        fpath = os.path.join(OUTPUT_DIR, fname)
        if not os.path.isfile(fpath) or os.path.getsize(fpath) == 0:
            continue
        md5 = file_md5(fpath)
        hash_to_files.setdefault(md5, []).append(fname)

    # Find duplicate groups
    dup_groups = {h: files for h, files in hash_to_files.items() if len(files) > 1}
    if not dup_groups:
        print("No duplicate files found.")
        return

    # Build rename map: duplicate filename → canonical filename
    rename_map: dict[str, str] = {}
    removed_count = 0
    for md5, files in dup_groups.items():
        canonical = files[0]  # alphabetically first (list is sorted)
        print(f"\n  MD5 {md5}: {len(files)} identical files")
        print(f"    Canonical: {canonical}")
        for dup in files[1:]:
            print(f"    Removing:  {dup}")
            dup_path = os.path.join(OUTPUT_DIR, dup)
            os.remove(dup_path)
            rename_map[dup] = canonical
            removed_count += 1

    print(f"\nRemoved {removed_count} duplicate files.")

    # Rewrite CSV if it exists
    if not os.path.exists(csv_path):
        print("No CSV file found to update.")
        return

    rows = []
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or SCHEMA_FIELDS
        for row in reader:
            fname = row.get("syllabus_filename", "")
            if fname in rename_map:
                canonical = rename_map[fname]
                row["syllabus_filename"] = canonical
                row["syllabus_filepath_local"] = (
                    f"../data/indiana_university_purdue_university_indianapolis__{SCHOOL_ID}__syllabus/{canonical}"
                )
                # Update filesize to canonical file's size
                canonical_path = os.path.join(OUTPUT_DIR, canonical)
                if os.path.exists(canonical_path):
                    row["syllabus_filesize"] = str(os.path.getsize(canonical_path))
            rows.append(row)

    # Ensure skip_reason is in fieldnames for rewrite
    if "skip_reason" not in fieldnames:
        fieldnames = list(fieldnames) + ["skip_reason"]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"CSV updated: {csv_path} ({len(rows)} rows)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Scrape IUPUI syllabi from syllabi.iu.edu"
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Only search sections; don't fetch details or download syllabi",
    )
    parser.add_argument(
        "--probe",
        nargs="+",
        metavar="CODE:CRN",
        help=(
            "Diagnostic mode: check specific course/CRN pairs. "
            'E.g. --probe "AHLT-C 150:17751" "AHLT-M 190:35281"'
        ),
    )
    parser.add_argument(
        "--dedup",
        action="store_true",
        help="Standalone dedup mode: scan output dir, remove duplicate files, update CSV",
    )
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Dedup mode: no network needed
    if args.dedup:
        run_dedup()
        return

    session = requests.Session()

    # Probe mode
    if args.probe:
        run_probe(session, args.probe)
        return

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
    deduped = 0
    content_hashes: dict[str, str] = {}  # md5 → canonical filename

    for section in tqdm(sections, desc="Processing sections", unit="section"):
        raw_code = section.get("code", "")
        crn = section.get("crn", "")
        title = section.get("title", "")
        section_code = section.get("no", "")
        code = normalize_code(raw_code)
        dept_code = parse_department_code(code)

        base_name = f"{code}__{crn}"
        filepath = os.path.join(OUTPUT_DIR, f"{base_name}.html")

        # Common row fields
        row_base = {
            "school_id": SCHOOL_ID,
            "term_code": SRCDB,
            "term": TERM,
            "department_code": dept_code,
            "department_name": "",
            "course_code": code,
            "course_titel": title,
            "section_code": section_code,
            "source_url": SOURCE_URL,
            "crawled_on": crawled_on,
        }

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

            # Hash existing file for dedup
            md5 = file_md5(ex_path)
            skip_reason = ""
            if md5 in content_hashes:
                canonical = content_hashes[md5]
                tqdm.write(f"  [DEDUP] {ex_filename} == {canonical} (MD5 {md5})")
                os.remove(ex_path)
                ex_filename = canonical
                deduped += 1
            else:
                content_hashes[md5] = ex_filename

            rows.append({
                **row_base,
                "instructor": "",
                "syllabus_filename": ex_filename,
                "syllabus_file_format": ex_ext,
                "syllabus_filepath_local": f"../data/indiana_university_purdue_university_indianapolis__{SCHOOL_ID}__syllabus/{ex_filename}",
                "syllabus_filesize": str(filesize),
                "syllabus_file_source_url": "",
                "downloaded_on": crawled_on,
                "skip_reason": skip_reason,
            })
            continue

        # Fetch section detail
        try:
            detail = get_section_detail(session, raw_code, crn)
        except Exception as e:
            tqdm.write(f"  [ERROR] Detail fetch failed for {code} CRN {crn}: {e}")
            errors += 1
            rows.append({
                **row_base,
                "instructor": "",
                "syllabus_filename": "",
                "syllabus_file_format": "",
                "syllabus_filepath_local": "",
                "syllabus_filesize": "0",
                "syllabus_file_source_url": "",
                "downloaded_on": "",
                "skip_reason": f"detail_fetch_error: {e}",
            })
            time.sleep(DELAY)
            continue

        instructor = parse_instructor(detail.get("instructordetail_html", ""))
        syllabus_url = extract_syllabus_url(detail.get("external_syllabi_links", ""))

        if not syllabus_url:
            skipped += 1
            tqdm.write(f"  [SKIP] {code} CRN {crn}: no syllabus link")
            rows.append({
                **row_base,
                "instructor": instructor,
                "syllabus_filename": "",
                "syllabus_file_format": "",
                "syllabus_filepath_local": "",
                "syllabus_filesize": "0",
                "syllabus_file_source_url": "",
                "downloaded_on": "",
                "skip_reason": "no_syllabus_link",
            })
            time.sleep(DELAY)
            continue

        # Download syllabus
        try:
            filesize, actual_path, file_format, skip_reason = download_syllabus(session, syllabus_url, filepath)
        except Exception as e:
            tqdm.write(f"  [ERROR] Download failed for {code} CRN {crn}: {e}")
            errors += 1
            rows.append({
                **row_base,
                "instructor": instructor,
                "syllabus_filename": "",
                "syllabus_file_format": "",
                "syllabus_filepath_local": "",
                "syllabus_filesize": "0",
                "syllabus_file_source_url": syllabus_url,
                "downloaded_on": "",
                "skip_reason": f"download_error: {e}",
            })
            time.sleep(DELAY)
            continue

        if filesize == 0 or skip_reason:
            reason = skip_reason or "no_content"
            tqdm.write(f"  [SKIP] {code} CRN {crn}: {reason}")
            skipped += 1
            # Clean up empty file if created
            if os.path.exists(filepath):
                os.remove(filepath)
            rows.append({
                **row_base,
                "instructor": instructor,
                "syllabus_filename": "",
                "syllabus_file_format": "",
                "syllabus_filepath_local": "",
                "syllabus_filesize": "0",
                "syllabus_file_source_url": syllabus_url,
                "downloaded_on": "",
                "skip_reason": reason,
            })
            time.sleep(DELAY)
            continue

        # Successful download — check for dedup
        filename = os.path.basename(actual_path)
        md5 = file_md5(actual_path)

        if md5 in content_hashes:
            canonical = content_hashes[md5]
            tqdm.write(f"  [DEDUP] {filename} == {canonical} (MD5 {md5})")
            os.remove(actual_path)
            filename = canonical
            deduped += 1
        else:
            content_hashes[md5] = filename

        now = datetime.now(timezone.utc).isoformat()
        rows.append({
            **row_base,
            "instructor": instructor,
            "syllabus_filename": filename,
            "syllabus_file_format": file_format,
            "syllabus_filepath_local": f"../data/indiana_university_purdue_university_indianapolis__{SCHOOL_ID}__syllabus/{filename}",
            "syllabus_filesize": str(filesize),
            "syllabus_file_source_url": syllabus_url,
            "downloaded_on": now,
            "skip_reason": "",
        })

        time.sleep(DELAY)

    # Step 3: Write CSV
    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    downloaded = sum(1 for r in rows if r["syllabus_filename"] and not r["skip_reason"])
    print(f"\nDone! {len(rows)} total sections processed")
    print(f"  Downloaded: {downloaded}")
    print(f"  Skipped (no syllabus / auth): {skipped}")
    print(f"  Deduplicated: {deduped}")
    print(f"  Errors: {errors}")
    print(f"CSV: {csv_path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
