import csv
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

SCHOOL_NAME = "rasmussen_university_minnesota"
SCHOOL_ID   = "3047068"
BASE_URL    = "https://www.rasmussenbookstoreonline.com"
REPORT_URL  = f"{BASE_URL}/pricereport.cfm"

REQUEST_DELAY = 0.5

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

COURSE_CODE_RE = re.compile(r"^([A-Z]+)(\d+)_(.+)$")

_ISBN_PREFIX_RE  = re.compile(r"^VS", re.IGNORECASE)
_ISBN_SUFFIX_RE  = re.compile(r"(_RAS_PPP|_DIGITALRSM|_[A-Z0-9]+)$", re.IGNORECASE)

def make_session():
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer":  BASE_URL + "/",
        "Origin":   BASE_URL,
        "Accept":   "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return sess

def fetch_report(sess):
    try:
        resp = sess.get(REPORT_URL, timeout=60)
        resp.raise_for_status()
        html = resp.text

        soup = BeautifulSoup(html, "lxml")
        sem_code_tag  = soup.find("input", {"id": "pr_semester"})
        sem_name_tag  = soup.find("input", {"id": "pr_semestername"})
        sem_code = sem_code_tag["value"].strip() if sem_code_tag else "UNKNOWN"
        sem_name = sem_name_tag["value"].strip() if sem_name_tag else "UNKNOWN"
        n = sum(len(tb.find_all("tr")) for tb in soup.find_all("tbody"))
        print(f"[*] Active term: {sem_name} ({sem_code}) — {n} rows")
        return html, sem_code, sem_name
    except Exception as e:
        raise RuntimeError(f"fetch_report failed: {e}") from e

def clean_isbn(raw):
    s = (raw or "").strip()
    s = _ISBN_PREFIX_RE.sub("", s)
    s = _ISBN_SUFFIX_RE.sub("", s)

    digits = re.sub(r"\D", "", s)
    if len(digits) in (10, 13):
        return digits

    if digits and s.isdigit():
        return digits
    return ""

def fmt(code):
    code = (code or "").strip()
    return f"|{code}" if code and not code.startswith("|") else code

def normalize_term(s):
    return re.sub(r"\s*\(.*?\)\s*", " ", s or "").strip().upper()

def parse_course_code(raw_code):
    raw_code = (raw_code or "").strip()

    m = COURSE_CODE_RE.match(raw_code)
    if m:
        return m.group(1), fmt(m.group(2)), fmt(m.group(3))

    m2 = re.match(r"^([A-Z]{2,})(\d+)$", raw_code)
    if m2:
        return m2.group(1), fmt(m2.group(2)), ""

    if "_" in raw_code:
        parts = raw_code.split("_", 1)
        dept_m = re.match(r"([A-Z]+)(\d+)", parts[0])
        if dept_m:
            return dept_m.group(1), fmt(dept_m.group(2)), fmt(parts[1])

    return "", fmt(raw_code), ""

def parse_table(html, sem_code, sem_name, crawled_on):
    soup = BeautifulSoup(html, "lxml")
    tbodies = soup.find_all("tbody")
    if not tbodies:
        return []

    term = normalize_term(sem_name)
    source_url = f"{REPORT_URL}?pr_semester={sem_code}"
    rows = []
    seen_notext = set()

    all_trs = [tr for tb in tbodies for tr in tb.find_all("tr")]
    for tr in all_trs:
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 6:
            continue

        raw_code    = cells[0]
        course_name = cells[1]
        raw_isbn    = cells[2]
        title       = cells[3]
        mat_type    = cells[4]
        req_status  = cells[5]

        dept, course_code, section = parse_course_code(raw_code)

        if mat_type.upper() == "NOTEXT":
            key = (dept, course_code, section)
            if key in seen_notext:
                continue
            seen_notext.add(key)
            rows.append({
                "source_url":           source_url,
                "school_id":            SCHOOL_ID,
                "department_code":      dept,
                "course_code":          course_code,
                "course_title":         course_name,
                "section":              section,
                "section_instructor":   "",
                "term":                 term,
                "isbn":                 "",
                "title":                "",
                "author":               "",
                "material_adoption_code": "This course does not require any course materials",
                "crawled_on":           crawled_on,
                "updated_on":           crawled_on,
            })
            continue

        isbn = clean_isbn(raw_isbn)

        req_upper = req_status.strip().upper()
        if req_upper == "REQUIRED":
            adoption = "Required"
        elif req_upper == "OPTIONAL":
            adoption = "Optional"
        else:
            adoption = req_status.strip() or "Required"

        rows.append({
            "source_url":           source_url,
            "school_id":            SCHOOL_ID,
            "department_code":      dept,
            "course_code":          course_code,
            "course_title":         course_name,
            "section":              section,
            "section_instructor":   "",
            "term":                 term,
            "isbn":                 isbn,
            "title":                title,
            "author":               "",
            "material_adoption_code": adoption,
            "crawled_on":           crawled_on,
            "updated_on":           crawled_on,
        })

    return rows

def append_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    new_file = not os.path.exists(filepath) or os.path.getsize(filepath) == 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)

def get_scraped_terms(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return {r.get("term", "") for r in csv.DictReader(f) if r.get("term")}

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_terms = get_scraped_terms(CSV_PATH)
    if done_terms:
        print(f"[*] Already scraped terms: {done_terms}")

    sess = make_session()

    print("[*] Fetching price report...")
    html, sem_code, sem_name = fetch_report(sess)

    term_key = normalize_term(sem_name)
    if term_key in done_terms:
        print(f"[*] Term '{term_key}' already scraped. Use --fresh to re-scrape.")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    debug_path = os.path.join(OUTPUT_DIR, f"debug_{sem_code}.html")
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[*] Debug HTML saved: {debug_path}")

    print(f"[*] Parsing {sem_name} ({sem_code})...")
    rows = parse_table(html, sem_code, sem_name, crawled_on)
    print(f"    {len(rows)} rows parsed")

    if rows:
        append_csv(rows, CSV_PATH)

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE — {len(rows)} rows written")
    print(f"CSV: {CSV_PATH}")
    if not rows:
        print("[!] No data written. Check debug HTML.")

if __name__ == "__main__":
    scrape(fresh="--fresh" in sys.argv)
