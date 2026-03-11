#!/usr/bin/env python3
"""
bnc_textbook_scraper.py — Scrape textbook/course material information from
BNC Virtual (bncvirtual.com) for any institution hosted on the platform.

Usage:
    python bnc_textbook_scraper.py --url https://bncvirtual.com/bsol
    python bnc_textbook_scraper.py --fvcusno 11414
    python bnc_textbook_scraper.py --fvcusno 11414 --school-id 12345

Uses curl_cffi to bypass Cloudflare protection.
"""

import argparse
import csv
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://bncvirtual.com"
CHOOSE_COURSES_URL = BASE_URL + "/vb_buy2.php?FVCUSNO={fvcusno}&ACTION=chooseCourses"
COURSE_SEARCH_URL = BASE_URL + "/vb_crs_srch.php?CSID={csid}&FVCUSNO={fvcusno}"
CHOOSE_ADOPTIONS_URL = (
    BASE_URL + "/vb_buy2.php?ACTION=chooseAdoptions&CSID={csid}&FVCUSNO={fvcusno}&VCHI=1"
)

CSV_FIELDS = [
    "source_url",
    "school_id",
    "department_code",
    "course_code",
    "course_title",
    "section",
    "section_instructor",
    "term",
    "isbn",
    "title",
    "author",
    "material_adoption_code",
    "crawled_on",
]

DEFAULT_BATCH_SIZE = 25
DEFAULT_DELAY = 0.5


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
def make_session() -> cffi_requests.Session:
    """Create a curl_cffi session with Chrome TLS fingerprint."""
    return cffi_requests.Session(impersonate="chrome")


# ---------------------------------------------------------------------------
# URL / FVCUSNO resolution
# ---------------------------------------------------------------------------
def resolve_fvcusno(url: str | None, fvcusno: str | None) -> str:
    """Return the FVCUSNO value from a URL or direct argument."""
    if fvcusno:
        return fvcusno
    if url:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "FVCUSNO" in qs:
            return qs["FVCUSNO"][0]
        # URL like /bsol — need to follow redirect to discover FVCUSNO
        # We'll handle this in init_session
        return url
    raise ValueError("Either --url or --fvcusno must be provided")


def discover_fvcusno(session: cffi_requests.Session, url: str) -> str:
    """Follow a short-URL (e.g. /bsol) to discover the FVCUSNO."""
    if url.isdigit():
        return url
    if not url.startswith("http"):
        url = BASE_URL + "/" + url.lstrip("/")
    resp = session.get(url, allow_redirects=True)
    resp.raise_for_status()
    # Check final URL for FVCUSNO
    final_qs = parse_qs(urlparse(str(resp.url)).query)
    if "FVCUSNO" in final_qs:
        return final_qs["FVCUSNO"][0]
    # Search the HTML for FVCUSNO
    m = re.search(r"FVCUSNO[=:][\s'\"]*(\d+)", resp.text)
    if m:
        return m.group(1)
    raise ValueError(f"Could not discover FVCUSNO from {url}")


# ---------------------------------------------------------------------------
# Step 1: Initialize session — extract CSID, terms, departments
# ---------------------------------------------------------------------------
def init_session(session: cffi_requests.Session, fvcusno: str) -> dict:
    """
    GET the chooseCourses page and extract:
      - CSID (session ID)
      - List of (term_id, term_name) tuples
      - List of (dept_id, dept_name, dept_enckey) tuples
    """
    url = CHOOSE_COURSES_URL.format(fvcusno=fvcusno)
    resp = session.get(url)
    resp.raise_for_status()
    html = resp.text

    # Extract CSID
    m = re.search(r"var\s+CSID\s*=\s*'([^']+)'", html)
    if not m:
        raise RuntimeError("Could not extract CSID from chooseCourses page")
    csid = m.group(1)

    # Extract terms from selectTerm() calls
    # Pattern: selectTerm($(this).attr('data-row'),'70108', 'Spring 2026', '...')
    term_matches = re.findall(
        r"selectTerm\([^,]*,\s*'(\d+)',\s*'([^']+)'", html
    )
    # Deduplicate preserving order
    seen = set()
    terms = []
    for tid, tname in term_matches:
        if tid not in seen:
            seen.add(tid)
            terms.append((tid, tname))

    # Extract departments from selectDept() calls
    # Pattern: selectDept($(this).attr('data-row'), '2173021', 'Name', undefined, 'ENCKEY')
    dept_matches = re.findall(
        r"selectDept\([^,]*,\s*'([^']+)',\s*'([^']+)',\s*[^,]*,\s*'([^']*)'",
        html,
    )
    seen_depts = set()
    depts = []
    for did, dname, denc in dept_matches:
        if did not in seen_depts:
            seen_depts.add(did)
            depts.append((did, dname, denc))

    return {
        "csid": csid,
        "fvcusno": fvcusno,
        "terms": terms,
        "depts": depts,
    }


# ---------------------------------------------------------------------------
# Step 2: Fetch courses for a term/dept combination
# ---------------------------------------------------------------------------
def fetch_courses(
    session: cffi_requests.Session,
    csid: str,
    fvcusno: str,
    term_id: str,
    dept_id: str,
    dept_enckey: str,
    delay: float,
) -> list[dict]:
    """
    POST to vb_crs_srch.php to get course list for a term/dept.
    Returns list of dicts with COURSE_ENC, COURSE_DESC, DATE_DESC, etc.
    """
    url = COURSE_SEARCH_URL.format(csid=csid, fvcusno=fvcusno)
    data = {
        "FvTerm": term_id,
        "FvDept": dept_enckey,
        "R": "1",
    }
    time.sleep(delay)
    resp = session.post(url, data=data)
    resp.raise_for_status()

    try:
        result = resp.json()
    except Exception:
        print(f"  [WARN] Non-JSON response for term={term_id}, dept={dept_id}")
        return []

    courses = []
    if "success" in result:
        for dept_key, dept_courses in result["success"].items():
            if isinstance(dept_courses, list):
                courses.extend(dept_courses)
            elif isinstance(dept_courses, dict):
                for course in dept_courses.values():
                    if isinstance(course, dict):
                        courses.append(course)
    return courses


# ---------------------------------------------------------------------------
# Step 3: Batch fetch textbook adoptions
# ---------------------------------------------------------------------------
def fetch_adoptions(
    session: cffi_requests.Session,
    csid: str,
    fvcusno: str,
    course_keys: list[str],
    delay: float,
) -> str:
    """
    POST to chooseAdoptions with a batch of encrypted course keys.
    Returns the HTML response.
    """
    url = CHOOSE_ADOPTIONS_URL.format(csid=csid, fvcusno=fvcusno)
    data = {"fvCourseKeyList": ",".join(course_keys)}
    time.sleep(delay)
    resp = session.post(url, data=data)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Step 4: Parse textbook details from adoption HTML
# ---------------------------------------------------------------------------
def clean_isbn(cell_html: str) -> str:
    """Strip hidden bogus spans from ISBN cell HTML and remove hyphens."""
    soup = BeautifulSoup(cell_html, "html.parser")
    # Remove spans with display:none
    for span in soup.find_all("span", style=re.compile(r"display:\s*none")):
        span.decompose()
    text = soup.get_text(strip=True)
    return text.replace("-", "").strip()


def parse_adoption_html(html: str, fvcusno: str, school_id: str) -> list[dict]:
    """
    Parse the chooseAdoptions HTML page and return a list of CSV-row dicts.
    Each course-material combination is one row.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    crawled_on = datetime.now(timezone.utc).isoformat()

    # Find all hidden inputs that describe courses: supsort_c_desc_N
    # Pattern: name="supsort_c_desc_1" value="LAW501 TORTS |div| 01/03/2026 - 04/18/2026"
    course_inputs = soup.find_all(
        "input", attrs={"name": re.compile(r"^supsort_c_desc_\d+$")}
    )
    dept_inputs = soup.find_all(
        "input", attrs={"name": re.compile(r"^supsort_d_desc_\d+$")}
    )

    # Build a map: index → (dept_info, course_info)
    dept_map = {}
    for inp in dept_inputs:
        name = inp.get("name", "")
        m = re.search(r"_(\d+)$", name)
        if m:
            dept_map[m.group(1)] = inp.get("value", "")

    course_map = {}
    for inp in course_inputs:
        name = inp.get("name", "")
        m = re.search(r"_(\d+)$", name)
        if m:
            course_map[m.group(1)] = inp.get("value", "")

    # Find all course header divs
    course_headers = soup.find_all("div", class_="cmCourseHeader")

    for i, header in enumerate(course_headers):
        idx = str(i + 1)

        # Parse department info: "Spring 2026 |div| Birmingham School of Law"
        dept_str = dept_map.get(idx, "")
        parts = [p.strip() for p in dept_str.split("|div|")]
        term_name = parts[0] if len(parts) > 0 else ""
        department_name = parts[1] if len(parts) > 1 else ""

        # Parse course info: "LAW501 TORTS |div| 01/03/2026 - 04/18/2026"
        course_str = course_map.get(idx, "")
        cparts = [p.strip() for p in course_str.split("|div|")]
        course_desc = cparts[0] if len(cparts) > 0 else ""

        # Split course_desc into code and title
        # e.g. "LAW501 TORTS" → dept_code="LAW", course_code="501", title="TORTS"
        # or "ACCT101 INTRO ACCOUNTING" → dept_code="ACCT", course_code="101", title="INTRO ACCOUNTING"
        dept_code, course_code, course_title = parse_course_desc(
            course_desc, department_name
        )

        # Build source URL for this specific course lookup
        source_url = CHOOSE_COURSES_URL.format(fvcusno=fvcusno)

        # Find textbooks within this course's section
        # The course header is followed by textbook divs until the next course header
        # Navigate to the parent container to find textbook entries
        container = header.find_parent("div", class_=re.compile(r"cmCourseListItem|row"))
        if container is None:
            container = header.parent

        # Find all textbook entries (col-sm-8 blocks with book info)
        book_blocks = find_textbook_blocks(header)

        if not book_blocks:
            # No textbooks for this course — emit one row with empty fields
            rows.append({
                "source_url": source_url,
                "school_id": school_id,
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": course_title,
                "section": "",
                "section_instructor": "",
                "term": term_name,
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": "",
                "crawled_on": crawled_on,
            })
        else:
            for book in book_blocks:
                rows.append({
                    "source_url": source_url,
                    "school_id": school_id,
                    "department_code": dept_code,
                    "course_code": course_code,
                    "course_title": course_title,
                    "section": "",
                    "section_instructor": "",
                    "term": term_name,
                    "isbn": book.get("isbn", ""),
                    "title": book.get("title", ""),
                    "author": book.get("author", ""),
                    "material_adoption_code": book.get("adoption_code", ""),
                    "crawled_on": crawled_on,
                })

    return rows


def parse_course_desc(course_desc: str, department_name: str) -> tuple[str, str, str]:
    """
    Parse a course description like "LAW501 TORTS" into
    (department_code, course_code, course_title).

    Splits on the boundary between letters and digits in the first token:
      "LAW501" → dept_code="LAW", course_code="501"
      "ACCT101" → dept_code="ACCT", course_code="101"
    """
    if not course_desc:
        return ("", "", "")

    tokens = course_desc.split(None, 1)
    first_token = tokens[0]
    remaining = tokens[1] if len(tokens) > 1 else ""

    # Split first token at letter-digit boundary
    m = re.match(r"^([A-Za-z]+)(\d+.*)$", first_token)
    if m:
        dept_code = m.group(1).upper()
        course_code = m.group(2)
    else:
        # No clear split — use the whole first token as course_code
        dept_code = ""
        course_code = first_token

    return (dept_code, course_code, remaining)


def find_textbook_blocks(course_header) -> list[dict]:
    """
    Starting from a cmCourseHeader div, find all textbook entries that
    belong to this course.

    DOM structure (siblings under <form>):
        <div class="cmCourseHeader"> ...
        <div class="collapse in crs_adpts_collapse"> ... textbooks ...
        <br>
        ... next course ...

    Returns list of dicts: {title, author, isbn, adoption_code}
    """
    books = []

    # The textbooks are in the next sibling div.crs_adpts_collapse
    scope = course_header.find_next_sibling(
        "div", class_=re.compile(r"crs_adpts_collapse")
    )
    if scope is None:
        return books

    adoption_codes = scope.find_all("p", class_=re.compile(r"text-uppercase"))
    titles = scope.find_all("h2", class_=re.compile(r"p0m0"))
    info_tables = scope.find_all("table", class_="cmTableBkInfo")

    count = max(len(adoption_codes), len(titles), len(info_tables))
    for j in range(count):
        book = {}

        if j < len(adoption_codes):
            book["adoption_code"] = adoption_codes[j].get_text(strip=True)

        if j < len(titles):
            h2 = titles[j]
            edition_span = h2.find("span", class_=re.compile(r"nobold|small"))
            if edition_span:
                edition_span.extract()
            book["title"] = h2.get_text(strip=True)

        if j < len(info_tables):
            table = info_tables[j]
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True).rstrip(":").strip()
                    if label == "Author":
                        book["author"] = cells[1].get_text(strip=True)
                    elif label == "ISBN-13":
                        book["isbn"] = clean_isbn(str(cells[1]))
                    elif label == "ISBN-10" and not book.get("isbn"):
                        book["isbn"] = clean_isbn(str(cells[1]))

        if book:
            books.append(book)

    return books


# ---------------------------------------------------------------------------
# Step 5: Write CSV
# ---------------------------------------------------------------------------
def write_csv(rows: list[dict], filepath: str) -> None:
    """Write rows to a CSV file using the standard schema."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------
def scrape(
    fvcusno: str,
    school_id: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    output_dir: str | None = None,
    delay: float = DEFAULT_DELAY,
) -> list[dict]:
    """Run the full scrape pipeline and return all rows."""
    if school_id is None:
        school_id = fvcusno

    session = make_session()

    # Step 1: Initialize — get CSID, terms, depts
    print(f"[*] Initializing session for FVCUSNO={fvcusno}...")
    info = init_session(session, fvcusno)
    csid = info["csid"]
    terms = info["terms"]
    depts = info["depts"]

    print(f"    CSID: {csid}")
    print(f"    Terms: {[t[1] for t in terms]}")
    print(f"    Departments: {[d[1] for d in depts]}")

    if not terms:
        print("[!] No terms found. Exiting.")
        return []
    if not depts:
        print("[!] No departments found. Exiting.")
        return []

    # Step 2: Fetch all courses for each term/dept
    all_courses = []  # list of (term_name, dept_name, course_dict)
    for term_id, term_name in terms:
        for dept_id, dept_name, dept_enckey in depts:
            print(f"[*] Fetching courses: {term_name} / {dept_name}...")
            courses = fetch_courses(
                session, csid, fvcusno, term_id, dept_id, dept_enckey, delay
            )
            print(f"    Found {len(courses)} courses")
            for c in courses:
                all_courses.append((term_name, dept_name, c))

    if not all_courses:
        print("[!] No courses found. Exiting.")
        return []

    # Step 3: Batch fetch textbook adoptions
    print(f"\n[*] Fetching textbook adoptions for {len(all_courses)} courses...")
    all_rows = []
    course_keys = [c[2].get("COURSE_ENC", "") for c in all_courses if c[2].get("COURSE_ENC")]

    batches = [
        course_keys[i : i + batch_size]
        for i in range(0, len(course_keys), batch_size)
    ]

    for batch in tqdm(batches, desc="Fetching adoptions"):
        html = fetch_adoptions(session, csid, fvcusno, batch, delay)
        rows = parse_adoption_html(html, fvcusno, school_id)
        all_rows.extend(rows)

    return all_rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Scrape textbook information from BNC Virtual (bncvirtual.com)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--url",
        help="Full BNC Virtual URL (e.g. https://bncvirtual.com/bsol)",
    )
    group.add_argument(
        "--fvcusno",
        help="FVCUSNO ID for the institution",
    )
    parser.add_argument(
        "--school-id",
        help="Override school_id in CSV output (defaults to FVCUSNO)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Courses per adoption request (default {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--output-dir",
        help="Custom output directory (default: data/bnc_{fvcusno}_textbooks/)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"Seconds between requests (default {DEFAULT_DELAY})",
    )

    args = parser.parse_args()

    session = make_session()

    # Resolve FVCUSNO
    raw = resolve_fvcusno(args.url, args.fvcusno)
    if not raw.isdigit():
        print(f"[*] Resolving FVCUSNO from URL: {raw}")
        fvcusno = discover_fvcusno(session, raw)
        print(f"    Discovered FVCUSNO: {fvcusno}")
    else:
        fvcusno = raw

    # Output directory
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "data",
            f"bnc_{fvcusno}_textbooks",
        )

    school_id = args.school_id or fvcusno

    # Run scrape
    rows = scrape(
        fvcusno=fvcusno,
        school_id=school_id,
        batch_size=args.batch_size,
        output_dir=output_dir,
        delay=args.delay,
    )

    if rows:
        csv_path = os.path.join(output_dir, f"bnc_{fvcusno}_textbooks.csv")
        write_csv(rows, csv_path)
        print(f"\n[+] Done! {len(rows)} rows written to {csv_path}")

        # Summary stats
        courses_with_isbn = sum(1 for r in rows if r.get("isbn"))
        courses_without = sum(1 for r in rows if not r.get("isbn"))
        unique_isbns = len(set(r["isbn"] for r in rows if r.get("isbn")))
        print(f"    Rows with ISBN: {courses_with_isbn}")
        print(f"    Rows without ISBN: {courses_without}")
        print(f"    Unique ISBNs: {unique_isbns}")
    else:
        print("\n[!] No data collected.")


if __name__ == "__main__":
    main()
