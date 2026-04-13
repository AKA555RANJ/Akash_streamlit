import csv
import os
import re
import time
import argparse
from datetime import datetime, timezone
from urllib.parse import urljoin, unquote

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

SCHOOL_ID = "2995987"
BASE_URL = "https://www.deanza.edu"
SYL_PAGE_URL = "https://www.deanza.edu/syl/"
API_URL = "https://www.deanza.edu/_resources/php/apps/syl/_actions.php"
DOWNLOAD_URL = "https://www.deanza.edu/schedule/_download.php?id={doc_id}"

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "de_anza_college__2995987__syllabus",
)
CSV_FILENAME = "de_anza_college__2995987__syllabus.csv"

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

DELAY = 0.3

QUARTER_MAP = {
    "W": ("W26", "Winter 2026"),
    "S": ("S26", "Spring 2026"),
    "SU": ("SU26", "Summer 2026"),
    "F": ("F26", "Fall 2026"),
}

DEPT_PAGE_HOSTS = ["www.deanza.edu", "www2.deanza.edu"]

def make_session() -> cffi_requests.Session:

    return cffi_requests.Session(impersonate="chrome")

def api_get_departments(session: cffi_requests.Session, year: str, quarter: str) -> list[tuple[str, str]]:

    resp = session.post(API_URL, data={"a": "l", "t": "4", "y": year, "q": quarter}, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    return [
        (o["value"], o.get_text(strip=True))
        for o in soup.find_all("option")
        if o.get("value")
    ]

def api_get_syllabi(session: cffi_requests.Session, year: str, quarter: str, dept_code: str) -> list[dict]:

    resp = session.post(API_URL, data={"a": "sll", "y": year, "q": quarter, "d": dept_code}, timeout=15)
    resp.raise_for_status()
    if not resp.text.strip():
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    entries = []

    h2 = soup.find("h2")
    dept_name = ""
    if h2:

        small = h2.find("small")
        if small:
            small.extract()
        dept_name = h2.get_text(strip=True)

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue

        course_raw = tds[0].get_text(strip=True)
        section = tds[1].get_text(strip=True)
        title = tds[2].get_text(strip=True)
        instructor_el = tds[3].find("a")
        instructor = instructor_el.get_text(strip=True) if instructor_el else tds[3].get_text(strip=True)

        download_link = tds[4].find("a", href=True)
        if not download_link:
            continue
        href = download_link["href"]

        m = re.search(r"id=(\d+)", href)
        if not m:
            continue
        doc_id = m.group(1)

        parts = course_raw.split()
        if len(parts) >= 2:
            dept = parts[0]
            num = parts[1]
            course_code = f"{dept}-{num}"
        else:
            dept = course_raw
            num = ""
            course_code = dept

        entries.append({
            "dept_code": dept,
            "department_name": dept_name,
            "course_code": course_code,
            "course_num": num,
            "course_title": title,
            "section_code": section,
            "instructor": instructor,
            "doc_id": doc_id,
            "pdf_url": DOWNLOAD_URL.format(doc_id=doc_id),
            "source_url": SYL_PAGE_URL,
        })

    return entries

def scrape_via_api(session: cffi_requests.Session, target_quarters: list[str] | None = None) -> list[dict]:

    print("Strategy 1: Using PHP syl API ...")

    session.get(SYL_PAGE_URL, timeout=15)

    quarters = target_quarters or list(QUARTER_MAP.keys())
    all_entries = []

    for quarter in quarters:
        term_code, term_name = QUARTER_MAP[quarter]
        print(f"\n  Fetching departments for {term_name} (q={quarter}) ...")
        depts = api_get_departments(session, "2026", quarter)
        if not depts:
            print(f"    No departments found for {term_name}")
            continue
        print(f"    {len(depts)} departments found")

        for dept_code, dept_name in depts:
            entries = api_get_syllabi(session, "2026", quarter, dept_code)
            if entries:

                for e in entries:
                    e["term_code"] = term_code
                    e["term"] = term_name
                    e["quarter"] = quarter
                all_entries.extend(entries)
                print(f"    {dept_code}: {len(entries)} syllabi")
            time.sleep(DELAY)

    print(f"\n  API total: {len(all_entries)} syllabi")
    return all_entries

def parse_pdf_filename(filename: str) -> dict:

    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    term_codes = "|".join(tc for tc, _ in QUARTER_MAP.values())

    m = re.match(
        rf"^(.+?)-([A-Z][A-Z/& ]{{0,5}})-(\d+[A-Z]?)-([A-Z0-9]+)-({term_codes})$",
        base,
    )
    if m:
        return {
            "instructor": m.group(1).replace("-", " "),
            "dept_code": m.group(2),
            "course_num": m.group(3),
            "section_code": m.group(4),
            "term_code": m.group(5),
        }

    m = re.match(
        rf"^(.+?)-([A-Z][A-Z/& ]{{0,5}})-(\d+[A-Z]?)-({term_codes})$",
        base,
    )
    if m:
        return {
            "instructor": m.group(1).replace("-", " "),
            "dept_code": m.group(2),
            "course_num": m.group(3),
            "section_code": "",
            "term_code": m.group(4),
        }

    return {}

def crawl_department_pages(session: cffi_requests.Session) -> list[dict]:

    print("\nStrategy 2: Crawling department syllabi pages ...")

    dept_slugs = [
        "math", "chemistry", "physics", "biology", "cis", "english",
        "anthropology", "art", "business", "communication-studies",
        "economics", "history", "humanities", "kinesiology", "music",
        "philosophy", "photography", "psychology", "sociology",
    ]
    term_codes = ["W26", "S26"]

    entries = []
    for slug in dept_slugs:
        for tc in term_codes:
            for host in DEPT_PAGE_HOSTS:
                url = f"https://{host}/{slug}/syllabi/2026/{tc}syllabi.html"
                try:
                    resp = session.get(url, timeout=15)
                    if resp.status_code != 200:
                        continue
                    soup = BeautifulSoup(resp.text, "lxml")
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        if not href.lower().endswith(".pdf"):
                            continue
                        pdf_url = urljoin(url, href)
                        filename = unquote(pdf_url.split("/")[-1])
                        parsed = parse_pdf_filename(filename)
                        if parsed and parsed["term_code"] in {tc for tc, _ in QUARTER_MAP.values()}:
                            entries.append({
                                "pdf_url": pdf_url,
                                "filename": filename,
                                "source_url": url,
                                **parsed,
                                "department_name": "",
                                "course_code": f"{parsed['dept_code']}-{parsed['course_num']}",
                                "course_title": "",
                                "doc_id": "",
                            })
                    break
                except Exception:
                    continue
                time.sleep(DELAY)

    print(f"  Department crawl total: {len(entries)} syllabi")
    return entries

FILE_SIGNATURES = {
    b"%PDF": ("pdf", ".pdf"),
    b"PK\x03\x04": ("docx", ".docx"),
    b"\xd0\xcf\x11\xe0": ("doc", ".doc"),
    b"<!DOC": ("html", ".html"),
    b"<html": ("html", ".html"),
}

def detect_file_format(data: bytes) -> tuple[str, str]:

    for sig, (fmt, ext) in FILE_SIGNATURES.items():
        if data[:len(sig)] == sig:
            return fmt, ext
    return "pdf", ".pdf"

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def download_file(session: cffi_requests.Session, url: str, filepath: str) -> tuple[int, str, str]:

    resp = session.get(url, timeout=60)
    resp.raise_for_status()
    fmt, ext = detect_file_format(resp.content)

    if not filepath.endswith(ext):
        filepath = filepath.rsplit(".", 1)[0] + ext
    with open(filepath, "wb") as f:
        f.write(resp.content)
    return len(resp.content), fmt, ext

def build_row(entry: dict, filename: str, file_format: str, filesize: int,
              crawled_on: str, downloaded_on: str = "") -> dict:

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
            f"../data/de_anza_college__{SCHOOL_ID}__syllabus/{filename}"
        ),
        "syllabus_filesize": str(filesize),
        "syllabus_file_source_url": entry.get("pdf_url", ""),
        "source_url": entry.get("source_url", SYL_PAGE_URL),
        "crawled_on": crawled_on,
        "downloaded_on": downloaded_on or crawled_on,
    }

def main():
    parser = argparse.ArgumentParser(
        description="Scrape De Anza College syllabi (IPEDS 2995987)"
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Only discover syllabi; don't download PDFs",
    )
    parser.add_argument(
        "--terms",
        nargs="+",
        choices=["W", "S", "SU", "F"],
        default=None,
        help="Filter to specific quarter codes (e.g., W S)",
    )
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    session = make_session()
    crawled_on = datetime.now(timezone.utc).isoformat()

    entries = scrape_via_api(session, target_quarters=args.terms)

    if not entries:
        dept_entries = crawl_department_pages(session)
        for e in dept_entries:

            for q, (tc, tn) in QUARTER_MAP.items():
                if e.get("term_code") == tc:
                    e["term"] = tn
                    break
        entries = dept_entries

    seen = set()
    unique_entries = []
    for e in entries:
        key = (e.get("course_code", ""), e.get("section_code", ""), e.get("term_code", ""))
        if key not in seen:
            seen.add(key)
            unique_entries.append(e)
    entries = unique_entries

    print(f"\nTotal unique syllabi: {len(entries)}")

    if not entries:
        print("No syllabi found.")
        return

    if args.no_download:
        print("\n--no-download: listing discovered syllabi only")
        for e in entries:
            dept = e.get("dept_code", "?")
            cc = e.get("course_code", "?")
            sec = e.get("section_code", "")
            instr = e.get("instructor", "")
            term = e.get("term_code", "")
            title = e.get("course_title", "")
            print(f"  [{term}] {cc}-{sec}  {title}  ({instr})")
        print(f"\nTotal: {len(entries)} syllabi")
        return

    rows: list[dict] = []
    total = len(entries)
    downloaded = 0
    cached = 0
    errors = 0

    for i, entry in enumerate(entries, 1):

        tc = entry.get("term_code", "W26")
        cc = entry.get("course_code", "UNKNOWN").replace("-", "_")
        sec = entry.get("section_code", "")
        base_stem = f"2026_{tc}_{cc}_{sec}" if sec else f"2026_{tc}_{cc}"

        base_stem = re.sub(r'[<>:"/\\|?*]', '_', base_stem)

        existing = [f for f in os.listdir(OUTPUT_DIR)
                    if f.startswith(base_stem) and f != base_stem and os.path.getsize(os.path.join(OUTPUT_DIR, f)) > 0]
        if existing:
            cached_file = existing[0]
            filepath = os.path.join(OUTPUT_DIR, cached_file)
            filesize = os.path.getsize(filepath)
            with open(filepath, "rb") as fh:
                fmt, _ = detect_file_format(fh.read(8))
            cached += 1
            rows.append(build_row(entry, cached_file, fmt, filesize, crawled_on))
            continue

        filepath = os.path.join(OUTPUT_DIR, base_stem + ".pdf")
        try:
            filesize, fmt, ext = download_file(session, entry["pdf_url"], filepath)
            actual_filename = base_stem + ext
            now = datetime.now(timezone.utc).isoformat()
            rows.append(build_row(entry, actual_filename, fmt, filesize, crawled_on, now))
            downloaded += 1
            if downloaded % 25 == 0 or i == total:
                print(f"  [{i}/{total}] Downloaded {downloaded} ...")
        except Exception as e:
            print(f"  [{i}/{total}] ERROR {base_stem}: {e}")
            errors += 1

        time.sleep(DELAY)

    rows.sort(key=lambda r: (r["term_code"], r["department_code"],
                              r["course_code"], r["section_code"]))

    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEMA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone! {len(rows)} syllabi processed")
    print(f"  Downloaded: {downloaded}")
    print(f"  Cached: {cached}")
    print(f"  Errors: {errors}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"CSV: {csv_path} ({len(rows)} rows)")

if __name__ == "__main__":
    main()
