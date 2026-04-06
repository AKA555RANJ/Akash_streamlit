"""
Parker University Bookstore Textbook Scraper
Platform: Timber e-Commerce (Drupal 6, Herkimer Media / bookstorewebsoftware.com)
URL: https://share.parker.edu/college

API flow (all unauthenticated GET requests, HTML fragment responses):
  1. GET /college
       → parse .tcc-item-link[url^='/college_term/'] for terms
  2. GET /timber/college/ajax?l=/college_term/{termId}
       → parse .tcc-item-link[url^='/college_dept/'] for departments
  3. GET /timber/college/ajax?l=/college_dept/{deptId}
       → parse .tcc-item-link[url^='/college_course/'] for courses
  4. GET /timber/college/ajax?l=/college_course/{courseId}
       → parse .tcc-item-link for sections/items (url contains nid)
  5. GET /timber/college/details/{nid}
       → HTML product page with title, ISBN/SKU, author, adoption code

No FlareSolverr or Cloudflare handling needed; the site serves plain HTML
to standard HTTP clients.
"""

import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, quote

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

SCHOOL_NAME = "parker_university"
SCHOOL_ID   = "3094167"
BASE_URL    = "https://share.parker.edu"
COLLEGE_URL = f"{BASE_URL}/college"
AJAX_URL    = f"{BASE_URL}/timber/college/ajax"
DETAILS_URL = f"{BASE_URL}/timber/college/details"

REQUEST_DELAY = 0.6

CSV_FIELDS = [
    "source_url", "school_id", "department_code", "course_code", "course_title",
    "section", "section_instructor", "term", "isbn", "title", "author",
    "material_adoption_code", "crawled_on", "updated_on",
]

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")

def make_session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": COLLEGE_URL,
    })
    return sess

def parse_tcc_items(html: str) -> list[dict]:
    """
    Return a list of {url, text} dicts from all a.tcc-item-link elements
    in an AJAX HTML fragment or full page.
    The 'url' attribute (not href) holds the path like /college_term/65576.
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for a in soup.find_all("a", class_="tcc-item-link"):
        url_attr = a.get("url", "").strip()
        text = a.get_text(separator=" ", strip=True)
        if url_attr:
            items.append({"url": url_attr, "text": text})
    return items

def extract_id(url_path: str) -> str:
    """Return the trailing numeric ID from a path like /college_term/65576 → '65576'."""
    return url_path.rstrip("/").rsplit("/", 1)[-1]

def extract_url_type(url_path: str) -> str:
    """Return the resource type prefix, e.g. 'college_term', 'college_dept', etc."""
    parts = url_path.strip("/").split("/")
    return parts[-2] if len(parts) >= 2 else ""

def timber_ajax_get(sess: requests.Session, path: str) -> str:
    """GET /timber/college/ajax?l={path} and return response text."""
    time.sleep(REQUEST_DELAY)
    url = f"{AJAX_URL}?l={quote(path, safe='')}"
    resp = sess.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text

def fetch_terms(sess: requests.Session) -> list[dict]:
    """Fetch the main /college page and return list of {id, name} terms."""
    time.sleep(REQUEST_DELAY)
    resp = sess.get(COLLEGE_URL, timeout=30)
    resp.raise_for_status()
    items = parse_tcc_items(resp.text)
    terms = []
    for item in items:
        if "/college_term/" in item["url"]:
            terms.append({"id": extract_id(item["url"]), "name": item["text"]})
    return terms

def fetch_departments(sess: requests.Session, term_id: str) -> list[dict]:
    """Return list of {id, code, name} depts for a term."""
    html = timber_ajax_get(sess, f"/college_term/{term_id}")
    items = parse_tcc_items(html)
    depts = []
    for item in items:
        if "/college_dept/" in item["url"]:
            code, name = _split_dept(item["text"])
            depts.append({"id": extract_id(item["url"]), "code": code, "name": name})
    return depts

def fetch_courses(sess: requests.Session, dept_id: str) -> list[dict]:
    """Return list of {id, text} courses for a department."""
    html = timber_ajax_get(sess, f"/college_dept/{dept_id}")
    items = parse_tcc_items(html)
    courses = []
    for item in items:
        if "/college_course/" in item["url"]:
            courses.append({"id": extract_id(item["url"]), "text": item["text"]})
    return courses

def fetch_sections(sess: requests.Session, course_id: str) -> list[dict]:
    """
    Return list of section/item dicts for a course.
    Each dict has {id, text, adoption_code} where id is used for the details URL.
    The adoption_code may appear as a leading label like 'Required' or 'Optional'.
    """
    html = timber_ajax_get(sess, f"/college_course/{course_id}")
    items = parse_tcc_items(html)
    sections = []
    for item in items:
        node_id = extract_id(item["url"])
        adoption, section_text = _split_adoption_prefix(item["text"])
        sections.append({
            "id":            node_id,
            "text":          section_text,
            "adoption_code": adoption,
            "raw_text":      item["text"],
            "url":           item["url"],
        })
    return sections

def fetch_details(sess: requests.Session, nid: str) -> dict:
    """
    GET /timber/college/details/{nid} and parse the HTML product page.
    Returns {title, isbn, author, adoption_code, instructor, section_num}.
    Parses defensively — all fields default to "".
    """
    time.sleep(REQUEST_DELAY)
    url = f"{DETAILS_URL}/{nid}"
    resp = sess.get(url, timeout=30)
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    return _parse_details_html(resp.text)

def _split_dept(text: str) -> tuple[str, str]:
    """
    'DC - DOCTOR OF CHIROPRACTIC' → ('DC', 'DOCTOR OF CHIROPRACTIC')
    'HPER (BS) - STRENGTH & HUMAN PERFORMANCE (B.S.)' → ('HPER (BS)', 'STRENGTH ...')
    Falls back to (text, text) if no ' - ' separator.
    """
    if " - " in text:
        code, _, name = text.partition(" - ")
        return code.strip(), name.strip()
    return text.strip(), text.strip()

def _split_adoption_prefix(text: str) -> tuple[str, str]:
    """
    Try to peel off a leading adoption label like 'Required', 'Optional', etc.
    Returns (adoption_code, remainder).
    """
    m = re.match(r"^(Required|Optional|Recommended|Choice)\s*[:\-]?\s*", text, re.IGNORECASE)
    if m:
        return m.group(1).capitalize(), text[m.end():].strip()
    return "", text

def _parse_details_html(html: str) -> dict:
    """
    Parse /timber/college/details/{nid} HTML.

    Confirmed structure (nid 41867):
      <h2><a href="...">MANUAL FOR THE CHIROPRACTIC ENTREPRENEUR</a></h2>
      <p><strong>ISBN/SKU:</strong> 9781737802426</p>
      <p><strong>Author:</strong> GOODMAN</p>

    Additional fields (defensive):
      <p><strong>Adoption:</strong> Required</p>
      <p><strong>Instructor:</strong> Dr. Smith</p>
      <p><strong>Section:</strong> 001</p>
    """
    soup = BeautifulSoup(html, "html.parser")
    result: dict = {
        "title": "", "isbn": "", "author": "",
        "adoption_code": "", "instructor": "", "section_num": "",
    }

    h2 = soup.find("h2")
    if h2:
        result["title"] = h2.get_text(strip=True)

    for p in soup.find_all("p"):
        strong = p.find("strong")
        if not strong:
            continue
        label = strong.get_text(strip=True).rstrip(":").lower()
        strong.extract()
        value = p.get_text(strip=True).lstrip(":").strip()

        if "isbn" in label or "sku" in label:
            result["isbn"] = _clean_isbn(value)
        elif label == "author":
            result["author"] = value
        elif "adoption" in label:
            result["adoption_code"] = value
        elif "instructor" in label:
            result["instructor"] = value
        elif "section" in label:
            result["section_num"] = value

    return result

def _parse_course_text(text: str) -> tuple[str, str, str]:
    """
    Parse course item text into (dept_code, course_code, course_title).

    Handles two formats from Timber:
      'BASC5101 - BIOLOGY OF CELLS AND TISSUE'  → ('BASC', '|5101', 'BIOLOGY OF CELLS AND TISSUE')
      'MHCM 510 Healthcare Management'           → ('MHCM', '|510',  'Healthcare Management')
      'DC 101'                                   → ('DC',   '|101',  '')
      'Some Course Title'                        → ('',     '',      'Some Course Title')
    """
    t = text.strip()

    m = re.match(r"^([A-Za-z]{2,10})(\d[\w\-]*)\s*[-–]\s*(.*)", t)
    if m:
        return m.group(1).upper(), fmt(m.group(2)), m.group(3).strip()

    m = re.match(r"^([A-Za-z]{2,10})\s+(\d[\w\-]*)\s*(?:[-–]\s*)?(.*)", t)
    if m:
        return m.group(1).upper(), fmt(m.group(2)), m.group(3).strip()

    return "", "", t

def _parse_section_text(text: str) -> tuple[str, str]:
    """
    Parse section item text into (section_num, instructor).

    Examples:
      '01 - Ferguson, Jay'  → ('01', 'Ferguson, Jay')
      '01 - '              → ('01', '')
      '01'                  → ('01', '')
    """
    t = text.strip()
    m = re.match(r"^(\w+)\s*[-–]\s*(.*)", t)
    if m:
        sec = m.group(1).strip()
        instructor = m.group(2).strip()
        return sec, instructor
    return t, ""

def _clean_isbn(value: str) -> str:
    return re.sub(r"[-\s]", "", value).strip()

def fmt(code: str) -> str:
    """Prefix code with | to preserve leading zeros."""
    code = (code or "").strip()
    return f"|{code}" if code and not code.startswith("|") else code

def normalize_term(s: str) -> str:
    """Strip ordering suffixes like '(Order Now)', '(Pre-Order)', etc."""
    return re.sub(r"\s*\(.*?\)\s*", " ", s or "").strip().upper()

def append_csv(rows: list[dict], filepath: str) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    new_file = not os.path.exists(filepath) or os.path.getsize(filepath) == 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerows(rows)

def get_scraped_keys(filepath: str) -> set:
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return {
            (r.get("term", ""), r.get("department_code", ""),
             r.get("course_code", ""), r.get("section", ""))
            for r in csv.DictReader(f)
        }

def scrape(fresh: bool = False) -> None:
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys = get_scraped_keys(CSV_PATH)
    if done_keys:
        print(f"[*] Resuming: {len(done_keys)} combo(s) already scraped.")

    sess = make_session()

    print(f"[*] Fetching terms from {COLLEGE_URL} ...")
    terms = fetch_terms(sess)
    if not terms:
        print("[!] No terms found. Exiting.")
        return
    print(f"[*] Found {len(terms)} term(s): {[t['name'] for t in terms]}")

    total_rows   = 0
    debug_saved  = False
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for term in terms:
        term_id   = term["id"]
        term_name = normalize_term(term["name"])
        print(f"\n[*] Term: {term_name} (id={term_id})")

        depts = fetch_departments(sess, term_id)
        if not depts:
            print(f"    [!] No departments found for {term_name}.")
            continue
        print(f"    {len(depts)} department(s)")

        for dept in tqdm(depts, desc=f"  {term_name} depts"):
            dept_id   = dept["id"]
            dept_code = dept["code"]

            courses = fetch_courses(sess, dept_id)
            if not courses:
                tqdm.write(f"    [!] {term_name} / {dept_code}: 0 courses, skipping.")
                continue

            dept_rows = 0

            for course in courses:
                course_id  = course["id"]
                raw_course = course["text"]
                inferred_dept, course_code, course_title = _parse_course_text(raw_course)
                if not course_code:
                    course_code = fmt(course_id)
                effective_dept = inferred_dept or dept_code

                sections = fetch_sections(sess, course_id)
                if not sections:
                    check_key = (term_name, effective_dept, course_code, "")
                    if check_key not in done_keys:
                        row = _build_row(
                            term_name, effective_dept, course_code, course_title,
                            section="", instructor="", isbn="", title="",
                            author="", adoption_code="This course does not require any course materials",
                            crawled_on=crawled_on,
                        )
                        append_csv([row], CSV_PATH)
                        done_keys.add(check_key)
                        total_rows += 1
                        dept_rows  += 1
                    continue

                for sec in sections:
                    nid           = sec["id"]
                    adoption_code = sec["adoption_code"]

                    details = fetch_details(sess, nid)

                    if not debug_saved and details:
                        import json
                        dbg = os.path.join(OUTPUT_DIR, "debug_details.json")
                        with open(dbg, "w", encoding="utf-8") as df:
                            json.dump({"nid": nid, "details": details}, df, indent=2)
                        tqdm.write(f"    [DEBUG] First details saved → {dbg}")
                        debug_saved = True

                    final_adoption = (
                        details.get("adoption_code")
                        or adoption_code
                        or ""
                    )

                    if details.get("section_num"):
                        section_num = details["section_num"]
                        instructor  = details.get("instructor", "")
                    else:
                        section_num, instructor = _parse_section_text(sec["text"] or nid)

                    check_key = (term_name, effective_dept, course_code, fmt(section_num))
                    if check_key in done_keys:
                        continue

                    isbn   = details.get("isbn", "")
                    title  = details.get("title", "")
                    author = details.get("author", "")

                    if not (isbn or title):
                        final_adoption = final_adoption or "This course does not require any course materials"

                    row = _build_row(
                        term_name, effective_dept, course_code, course_title,
                        section=fmt(section_num), instructor=instructor,
                        isbn=isbn, title=title, author=author,
                        adoption_code=final_adoption, crawled_on=crawled_on,
                    )
                    append_csv([row], CSV_PATH)
                    done_keys.add(check_key)
                    total_rows += 1
                    dept_rows  += 1

            if dept_rows:
                tqdm.write(f"    [{dept_code}] +{dept_rows} rows (total so far: {total_rows})")

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE — {total_rows} rows written")
    print(f"CSV: {CSV_PATH}")
    if total_rows == 0:
        print("[!] No data collected. The active term may not have course adoptions yet.")
        print("    Re-run when the bookstore loads materials for the upcoming term.")
        if not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0:
            append_csv([], CSV_PATH)
            print(f"    (Header-only CSV written to {CSV_PATH})")

def _build_row(
    term: str, dept_code: str, course_code: str, course_title: str,
    section: str, instructor: str, isbn: str, title: str, author: str,
    adoption_code: str, crawled_on: str,
) -> dict:
    return {
        "source_url":           COLLEGE_URL,
        "school_id":            SCHOOL_ID,
        "department_code":      dept_code,
        "course_code":          course_code,
        "course_title":         course_title,
        "section":              section,
        "section_instructor":   instructor,
        "term":                 term,
        "isbn":                 isbn,
        "title":                title,
        "author":               author,
        "material_adoption_code": adoption_code,
        "crawled_on":           crawled_on,
        "updated_on":           crawled_on,
    }

if __name__ == "__main__":
    scrape(fresh="--fresh" in sys.argv)
