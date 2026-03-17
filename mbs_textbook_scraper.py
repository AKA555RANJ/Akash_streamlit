#!/usr/bin/env python3
"""
mbs_textbook_scraper.py — Scrape textbook/course material information from
MBS Direct InSite bookstores. Built for South Texas College (mystcstore.com).

Uses FlareSolverr for Cloudflare bypass, then plain HTTP requests for API calls.

Usage:
    python mbs_textbook_scraper.py           # scrape only missing departments
    python mbs_textbook_scraper.py --fresh   # delete CSV and scrape everything
"""

import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# Force unbuffered stdout so prints appear immediately in log files
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHOOL_NAME = "south_texas_college"
SCHOOL_ID = "3094183"
BASE_URL = "https://www.mystcstore.com"
START_URL = BASE_URL + "/SelectTermDept"
MATERIALS_URL = BASE_URL + "/CourseMaterials"
FLARESOLVERR_URL = "http://localhost:8191/v1"

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

BATCH_SIZE = 19  # Stay under the 20-course captcha threshold
REQUEST_DELAY = 0.3

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")


# ---------------------------------------------------------------------------
# FlareSolverr bootstrap
# ---------------------------------------------------------------------------
FLARESOLVERR_SESSION = "mbs_scraper"


def flaresolverr_create_session():
    """Create a named FlareSolverr session for clean browser state."""
    # Destroy any existing session first
    try:
        requests.post(FLARESOLVERR_URL, json={
            "cmd": "sessions.destroy",
            "session": FLARESOLVERR_SESSION,
        }, timeout=10)
    except Exception:
        pass
    resp = requests.post(FLARESOLVERR_URL, json={
        "cmd": "sessions.create",
        "session": FLARESOLVERR_SESSION,
    }, timeout=30)
    resp.raise_for_status()


def flaresolverr_destroy_session():
    """Destroy the named FlareSolverr session."""
    try:
        requests.post(FLARESOLVERR_URL, json={
            "cmd": "sessions.destroy",
            "session": FLARESOLVERR_SESSION,
        }, timeout=10)
    except Exception:
        pass


def flaresolverr_get(url, max_timeout=60000):
    """Use FlareSolverr to GET a URL, bypassing Cloudflare.
    Uses a named session for clean state management.
    Returns (html, cookies_dict, user_agent, form_token).
    """
    resp = requests.post(FLARESOLVERR_URL, json={
        "cmd": "request.get",
        "url": url,
        "session": FLARESOLVERR_SESSION,
        "maxTimeout": max_timeout,
    })
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"FlareSolverr error: {data}")

    sol = data["solution"]
    html = sol.get("response", "")
    ua = sol.get("userAgent", "")

    # Build cookies dict
    cookies = {}
    for c in sol.get("cookies", []):
        if c.get("name"):
            cookies[c["name"]] = c["value"]

    # Extract form token from HTML
    form_token = ""
    m = re.search(r'name="__RequestVerificationToken".*?value="([^"]+)"', html)
    if m:
        form_token = m.group(1)

    return html, cookies, ua, form_token


def create_session():
    """Bootstrap a session via FlareSolverr. Returns (session, form_token)."""
    print("[*] Bootstrapping session via FlareSolverr...")
    flaresolverr_create_session()
    html, cookies, ua, form_token = flaresolverr_get(START_URL)

    if not form_token:
        raise RuntimeError("Could not extract __RequestVerificationToken from page")
    if not cookies.get("cf_clearance"):
        raise RuntimeError("No cf_clearance cookie — Cloudflare bypass failed")

    sess = requests.Session()
    sess.cookies.update(cookies)
    sess.headers.update({
        "User-Agent": ua,
        "Origin": BASE_URL,
        "Referer": START_URL,
    })

    print(f"[*] Session ready. Token: {form_token[:30]}...")
    print(f"    Cookies: {list(cookies.keys())}")
    return sess, form_token


def refresh_session(sess):
    """Destroy current session and create a fresh one via FlareSolverr.
    Retries up to 5 times with increasing delays if Cloudflare blocks.
    Returns (session, form_token).
    """
    print("[*] Refreshing session via FlareSolverr...", flush=True)
    for attempt in range(5):
        try:
            flaresolverr_destroy_session()
            time.sleep(5 * (attempt + 1))  # 5s, 10s, 15s, 20s, 25s
            return create_session()
        except Exception as e:
            print(f"  [WARN] Session refresh attempt {attempt + 1} failed: {e}", flush=True)
            if attempt == 4:
                raise


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
AJAX_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded",
}


def api_post(sess, url, data, retries=3):
    """POST to an API endpoint with retry logic. Returns response text."""
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.post(url, data=data, headers=AJAX_HEADERS, timeout=30)
            resp.raise_for_status()
            text = resp.text
            # Server may return JSON-encoded HTML string — unwrap.
            # Use strict=False to allow control chars (\r, \n, \t) in the string.
            if isinstance(text, str) and text.startswith('"') and text.endswith('"'):
                try:
                    decoder = json.JSONDecoder(strict=False)
                    text = decoder.decode(text)
                except (json.JSONDecodeError, ValueError):
                    pass
            return text
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] API call failed (attempt {attempt + 1}): {e}")
                time.sleep(2 * (attempt + 1))
            else:
                raise
    return ""


# ---------------------------------------------------------------------------
# Step 1: Fetch terms
# ---------------------------------------------------------------------------
def fetch_terms(sess, token):
    """Fetch available terms. Returns list of (term_id, term_name)."""
    html = api_post(sess, BASE_URL + "/SelectTermDept/Terms", {
        "__RequestVerificationToken": token,
    })
    soup = BeautifulSoup(html, "html.parser")
    terms = []
    for li in soup.find_all("li"):
        data_id = li.get("data-id", "")
        if data_id.startswith("ter-"):
            term_id = data_id.replace("ter-", "")
            term_name = li.get_text(strip=True)
            terms.append((term_id, term_name))
    return terms


# ---------------------------------------------------------------------------
# Step 2: Fetch departments for a term
# ---------------------------------------------------------------------------
def fetch_departments(sess, token, term_id):
    """Fetch departments for a term. Returns list of (dept_id, dept_code)."""
    html = api_post(sess, BASE_URL + "/SelectTermDept/Department", {
        "__RequestVerificationToken": token,
        "termId": term_id,
    })
    soup = BeautifulSoup(html, "html.parser")
    depts = []
    for li in soup.find_all("li"):
        data_id = li.get("data-id", "")
        if data_id.startswith("dpt-"):
            dept_id = data_id.replace("dpt-", "")
            dept_code = li.get_text(strip=True)
            depts.append((dept_id, dept_code))
    return depts


# ---------------------------------------------------------------------------
# Step 3: Fetch courses for a term/department
# ---------------------------------------------------------------------------
def fetch_courses(sess, token, term_id, dept_id):
    """Fetch courses for a term/dept. Returns list of course dicts."""
    html = api_post(sess, BASE_URL + "/SelectTermDept/Courses", {
        "__RequestVerificationToken": token,
        "termId": term_id,
        "deptId": dept_id,
    })
    soup = BeautifulSoup(html, "html.parser")
    courses = []
    for li in soup.find_all("li"):
        data_id = li.get("data-id", "")
        if not data_id.startswith("cou-"):
            continue
        course_id = data_id.replace("cou-", "")
        raw_text = li.get_text(strip=True)

        # Format: "{course_code} -{section} [-SECTIONS] -{instructor}"
        parts = [p.strip() for p in raw_text.split(" -")]
        course_code = parts[0] if parts else raw_text
        section = parts[1] if len(parts) > 1 else ""
        # Instructor is the last non-empty part that isn't "SECTIONS"
        instructor = ""
        for p in reversed(parts[2:]):
            if p and p.upper() != "SECTIONS":
                instructor = p
                break

        courses.append({
            "course_id": course_id,
            "course_code": course_code,
            "section": section,
            "instructor": instructor,
            "raw_text": raw_text,
        })
    return courses


# ---------------------------------------------------------------------------
# Step 4: Add course to cart / clear cart
# ---------------------------------------------------------------------------
def add_course_to_cart(sess, token, term_id, dept_id, course_id,
                       term_name, dept_code, course_text, debug=False):
    """Add a single course to the session cart.
    Returns True if course is in cart (either newly added or already present).
    """
    payload = {
        "__RequestVerificationToken": token,
        "model.TermId": term_id,
        "model.DeptId": dept_id,
        "model.CourseId": course_id,
        "model.TermName": term_name,
        "model.DeptName": dept_code,
        "model.CourseName": course_text,
    }
    resp = api_post(sess, BASE_URL + "/SelectTermDept/CourseList", payload)
    if debug:
        print(f"    [DEBUG] CourseList response ({len(resp)} chars): {resp[:300]}", flush=True)
    try:
        lower = resp.lower()
        # True if added successfully OR if already in cart
        if '"retval":true' in lower or '"retval": true' in lower:
            return True
        if "already been added" in lower or "duplicate" in lower:
            return True
        return False
    except Exception:
        return False


def clear_cart(sess, token, added_course_ids):
    """Remove courses from cart by their IDs (tracked when added)."""
    for cid in added_course_ids:
        api_post(sess, BASE_URL + "/SelectTermDept/Remove", {
            "__RequestVerificationToken": token,
            "id": cid,
        })


def fetch_materials_page(sess):
    """GET the CourseMaterials page. Uses the session cookies directly.
    The AJAX endpoints work with plain requests, but full page GETs
    may need the cf_clearance cookie to pass Cloudflare.
    """
    time.sleep(REQUEST_DELAY)
    resp = sess.get(MATERIALS_URL, timeout=60)
    resp.raise_for_status()
    # Check if we got a Cloudflare challenge instead of the real page
    if "just a moment" in resp.text.lower()[:500]:
        raise RuntimeError("Cloudflare challenge on CourseMaterials page — need session refresh")
    return resp.text


# ---------------------------------------------------------------------------
# Step 5: Parse CourseMaterials HTML
# ---------------------------------------------------------------------------
def parse_materials_html(html, term_name):
    """Parse CourseMaterials HTML. Returns list of row dicts."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    course_cards = soup.find_all("div", class_=re.compile(r"Materials_Course"))
    for card in course_cards:
        header = card.find("div", class_="card-header")
        if not header:
            continue

        # Extract from GA4 hidden inputs (cleanest source)
        dept_code = _input_val(header, "ga4-course-department")
        course_num = _input_val(header, "ga4-course-courseNumber")
        section = _input_val(header, "ga4-course-sectionNumber")
        instructor = _input_val(header, "ga4-course-instructor")

        # Fallback to span text
        if not dept_code:
            span = header.find("span", class_="No_Material_Course_Name")
            if span:
                text = span.get_text(strip=True)
                m = re.search(r"Name:\s*(.+?)(?:\s*\||$)", text)
                if m:
                    parts = m.group(1).strip().split(None, 1)
                    dept_code = parts[0] if parts else ""
                    course_num = parts[1] if len(parts) > 1 else ""

        if not section:
            span = header.find("span", class_="No_Material_Course_Section")
            if span:
                m = re.search(r"Section:\s*(.+?)(?:\s*\||$)", span.get_text(strip=True))
                if m:
                    section = m.group(1).strip()

        if not instructor:
            span = header.find("span", class_="No_Material_Course_Instructor")
            if span:
                m = re.search(r"Instructor:\s*(.+?)(?:\s*\||$)", span.get_text(strip=True))
                if m:
                    instructor = m.group(1).strip()

        # Clean up artifacts
        if instructor == "|":
            instructor = ""
        section = re.sub(r"\s*-?\s*SECTIONS\s*$", "", section, flags=re.IGNORECASE).strip()
        course_code = f"{dept_code} {course_num}".strip() if course_num else dept_code

        # Find textbook details
        book_details = card.find_all("div", class_="courseBookDetail")

        if not book_details:
            card_text = card.get_text(" ", strip=True)
            if "does not require any course materials" in card_text.lower():
                adoption = "This course does not require any course materials"
            else:
                adoption = ""
            results.append({
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": "",
                "section": section,
                "section_instructor": instructor,
                "term": term_name,
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": adoption,
            })
        else:
            for detail in book_details:
                isbn = _input_val(detail, "ga4-book-isbn")
                title = _input_val(detail, "ga4-book-name")
                author = _input_val(detail, "ga4-book-author")

                if not isbn:
                    p = detail.find("p", class_="Book_ISBN")
                    if p:
                        m = re.search(r"ISBN:\s*(\S+)", p.get_text(strip=True))
                        if m:
                            isbn = m.group(1)
                if not title:
                    h2 = detail.find("h2", class_="Book_Title")
                    if h2:
                        title = h2.get_text(strip=True)
                if not author:
                    p = detail.find("p", class_="Book_Author")
                    if p:
                        m = re.search(r"Author:\s*(.+)", p.get_text(strip=True))
                        if m:
                            author = m.group(1).strip()

                adoption_code = ""
                req_p = detail.find("p", class_=re.compile(r"Course_With_Material"))
                if req_p:
                    adoption_code = req_p.get_text(strip=True)

                isbn = isbn.replace("-", "").strip() if isbn else ""

                results.append({
                    "department_code": dept_code,
                    "course_code": course_code,
                    "course_title": "",
                    "section": section,
                    "section_instructor": instructor,
                    "term": term_name,
                    "isbn": isbn,
                    "title": title,
                    "author": author,
                    "material_adoption_code": adoption_code,
                })

    return results


def _input_val(parent, class_name):
    """Extract value from a hidden input by class name."""
    el = parent.find("input", class_=class_name)
    return el.get("value", "").strip() if el else ""


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
def append_csv(rows, filepath):
    """Append rows to CSV (create with header if new)."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def get_scraped_departments(filepath):
    """Read existing CSV and return set of department codes already scraped."""
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    scraped = set()
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dept = row.get("department_code", "").strip()
            if dept:
                scraped.add(dept)
    return scraped


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------
def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_url = BASE_URL

    # Fresh run — delete existing CSV
    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_depts = get_scraped_departments(CSV_PATH)
    if done_depts:
        print(f"[*] {len(done_depts)} departments already scraped: {sorted(done_depts)}")
        print("[*] Will only scrape missing departments.")

    # Bootstrap session via FlareSolverr
    sess, token = create_session()

    # Fetch terms
    print("[*] Fetching terms...")
    terms = fetch_terms(sess, token)
    print(f"    Found {len(terms)} terms: {[t[1] for t in terms]}")

    if not terms:
        print("[!] No terms found. Exiting.")
        return

    total_rows = 0
    all_expected_depts = set()

    for term_id, term_name in terms:
        print(f"\n[*] Processing term: {term_name} (id={term_id})")

        # Fetch departments
        depts = fetch_departments(sess, token, term_id)
        print(f"    Found {len(depts)} departments")
        all_expected_depts.update(d[1] for d in depts)

        if not depts:
            continue

        # Collect courses only from departments not yet scraped
        all_courses = []
        skipped = 0
        for dept_id, dept_code in tqdm(depts, desc=f"  Enumerating depts ({term_name})"):
            if dept_code in done_depts:
                skipped += 1
                continue
            courses = fetch_courses(sess, token, term_id, dept_id)
            for c in courses:
                c["term_id"] = term_id
                c["term_name"] = term_name
                c["dept_id"] = dept_id
                c["dept_code"] = dept_code
            all_courses.extend(courses)

        if skipped:
            print(f"    Skipped {skipped} already-scraped departments")
        print(f"    Courses to scrape: {len(all_courses)}")

        if not all_courses:
            print("    Nothing to scrape for this term.")
            continue

        # Process courses in batches
        batches = [
            all_courses[i: i + BATCH_SIZE]
            for i in range(0, len(all_courses), BATCH_SIZE)
        ]

        cart_ids = []  # Track course IDs in cart for clearing
        for batch_idx, batch in enumerate(
            tqdm(batches, desc=f"  Fetching materials ({term_name})")
        ):
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # Clear cart from previous batch
                    if batch_idx > 0 or attempt > 0:
                        clear_cart(sess, token, cart_ids)
                    cart_ids = []

                    # Add courses to cart
                    added = 0
                    for ci, course in enumerate(batch):
                        # Debug first course of first batch on each attempt
                        debug = (batch_idx <= 1 and ci == 0)
                        success = add_course_to_cart(
                            sess, token,
                            course["term_id"], course["dept_id"],
                            course["course_id"], course["term_name"],
                            course["dept_code"], course["raw_text"],
                            debug=debug,
                        )
                        if success:
                            added += 1
                            cart_ids.append(course["course_id"])
                        time.sleep(REQUEST_DELAY)

                    if added == 0:
                        raise RuntimeError(
                            f"Batch {batch_idx}: 0/{len(batch)} courses added "
                            f"(depts: {set(c['dept_code'] for c in batch)}) — likely blocked"
                        )

                    # Fetch materials
                    html = fetch_materials_page(sess)
                    batch_depts = set(c["dept_code"] for c in batch)
                    print(f"    [batch {batch_idx}] added={added}/{len(batch)} | "
                          f"materials page: {len(html)} chars | "
                          f"batch depts: {sorted(batch_depts)}", flush=True)
                    all_materials = parse_materials_html(html, term_name)

                    # Filter to only keep rows from THIS batch's departments
                    # (cart may contain courses from previous batches or stale sessions)
                    materials = [
                        r for r in all_materials
                        if r["department_code"].strip() in batch_depts
                    ]

                    # Debug: dump HTML snippet if no materials found
                    if not materials and html:
                        debug_path = f"/tmp/mbs_debug_batch{batch_idx}.html"
                        with open(debug_path, "w") as df:
                            df.write(html)
                        print(f"    [DEBUG] 0 materials from batch depts! "
                              f"Total parsed: {len(all_materials)}, "
                              f"HTML dumped to {debug_path}", flush=True)

                    for row in materials:
                        row["source_url"] = source_url
                        row["school_id"] = SCHOOL_ID
                        row["crawled_on"] = crawled_on

                    if materials:
                        append_csv(materials, CSV_PATH)
                        total_rows += len(materials)

                    batch_depts = set(c["dept_code"] for c in batch)
                    print(f"    [batch {batch_idx}/{len(batches)}] +{len(materials)} rows "
                          f"(total: {total_rows}) depts: {batch_depts}", flush=True)
                    break  # Success

                except Exception as e:
                    print(f"\n[!] Batch {batch_idx} attempt {attempt + 1} failed: {e}", flush=True)
                    if attempt < max_retries - 1:
                        # Refresh session via FlareSolverr
                        sess, token = refresh_session(sess)
                    else:
                        skipped_depts = set(c["dept_code"] for c in batch)
                        skipped_courses = [c["raw_text"] for c in batch]
                        print(f"[!] SKIPPING batch {batch_idx} after {max_retries} retries", flush=True)
                        print(f"    Skipped depts: {skipped_depts}", flush=True)
                        print(f"    Skipped courses: {skipped_courses}", flush=True)

    # Final summary
    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"Total rows written: {total_rows}")
    print(f"CSV: {CSV_PATH}")

    # Check for missing departments
    final_depts = get_scraped_departments(CSV_PATH)
    missing = all_expected_depts - final_depts
    if missing:
        print(f"\n⚠ MISSING {len(missing)} departments: {sorted(missing)}")
        print("  Re-run without --fresh to scrape only these.")
    else:
        print(f"\n✓ All {len(all_expected_depts)} departments scraped successfully!")


if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    scrape(fresh=fresh)
