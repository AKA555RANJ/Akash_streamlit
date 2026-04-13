import argparse
import csv
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs

import requests as std_requests
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from tqdm import tqdm

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
FLARESOLVERR_DEFAULT_URL = "http://localhost:8191/v1"

def make_session(cookies: dict | None = None, user_agent: str | None = None) -> cffi_requests.Session:
    session = cffi_requests.Session(impersonate="chrome")
    if cookies:
        for name, value in cookies.items():
            session.cookies.set(name, value, domain="bncvirtual.com")
    if user_agent:
        session.headers.update({"User-Agent": user_agent})
    return session

def _fs_session_name(fvcusno: str) -> str:
    return f"bnc_{fvcusno}_scraper"

def _fs_create(flaresolverr_url: str, session_name: str) -> None:
    try:
        std_requests.post(
            flaresolverr_url,
            json={"cmd": "sessions.destroy", "session": session_name},
            timeout=10,
        )
    except Exception:
        pass
    std_requests.post(
        flaresolverr_url,
        json={"cmd": "sessions.create", "session": session_name},
        timeout=120,
    ).raise_for_status()

def _fs_destroy(flaresolverr_url: str, session_name: str) -> None:
    try:
        std_requests.post(
            flaresolverr_url,
            json={"cmd": "sessions.destroy", "session": session_name},
            timeout=10,
        )
    except Exception:
        pass

def _fs_get(flaresolverr_url: str, session_name: str, url: str, max_timeout: int = 120000):
    resp = std_requests.post(
        flaresolverr_url,
        json={
            "cmd": "request.get",
            "url": url,
            "session": session_name,
            "maxTimeout": max_timeout,
        },
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"FlareSolverr error: {data}")
    sol = data["solution"]
    return sol.get("response", ""), sol.get("cookies", []), sol.get("userAgent", "")

def fs_bootstrap(fvcusno: str, flaresolverr_url: str = FLARESOLVERR_DEFAULT_URL) -> tuple[dict, str, str]:
    session_name = _fs_session_name(fvcusno)
    url = CHOOSE_COURSES_URL.format(fvcusno=fvcusno)

    print(f"[*] FlareSolverr bootstrap: {url}")
    _fs_create(flaresolverr_url, session_name)
    try:
        html, raw_cookies, user_agent = _fs_get(flaresolverr_url, session_name, url)
    finally:
        _fs_destroy(flaresolverr_url, session_name)

    cookies = {c["name"]: c["value"] for c in raw_cookies if c.get("name")}
    print(f"    Captured cookies: {list(cookies.keys())}")
    return cookies, user_agent, html

def resolve_fvcusno(url: str | None, fvcusno: str | None) -> str:
    if fvcusno:
        return fvcusno
    if url:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "FVCUSNO" in qs:
            return qs["FVCUSNO"][0]
        return url
    raise ValueError("Either --url or --fvcusno must be provided")

def discover_fvcusno(session: cffi_requests.Session, url: str) -> str:
    if url.isdigit():
        return url
    if not url.startswith("http"):
        url = BASE_URL + "/" + url.lstrip("/")
    resp = session.get(url, allow_redirects=True)
    resp.raise_for_status()
    final_qs = parse_qs(urlparse(str(resp.url)).query)
    if "FVCUSNO" in final_qs:
        return final_qs["FVCUSNO"][0]
    m = re.search(r"FVCUSNO[=:][\s'\"]*(\d+)", resp.text)
    if m:
        return m.group(1)
    raise ValueError(f"Could not discover FVCUSNO from {url}")

def init_session(session: cffi_requests.Session, fvcusno: str, preloaded_html: str | None = None) -> dict:
    if preloaded_html:
        html = preloaded_html
    else:
        url = CHOOSE_COURSES_URL.format(fvcusno=fvcusno)
        resp = session.get(url)
        resp.raise_for_status()
        html = resp.text

    m = re.search(r"var\s+CSID\s*=\s*'([^']+)'", html)
    if not m:
        raise RuntimeError("Could not extract CSID from chooseCourses page")
    csid = m.group(1)

    term_matches = re.findall(
        r"selectTerm\([^,]*,\s*'(\d+)',\s*'([^']+)'", html
    )
    seen = set()
    terms = []
    for tid, tname in term_matches:
        if tid not in seen:
            seen.add(tid)
            terms.append((tid, tname))

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

def fetch_courses(
    session: cffi_requests.Session,
    csid: str,
    fvcusno: str,
    term_id: str,
    dept_id: str,
    dept_enckey: str,
    delay: float,
) -> list[dict]:
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

def fetch_adoptions(
    session: cffi_requests.Session,
    csid: str,
    fvcusno: str,
    course_keys: list[str],
    delay: float,
) -> str:
    url = CHOOSE_ADOPTIONS_URL.format(csid=csid, fvcusno=fvcusno)
    data = {"fvCourseKeyList": ",".join(course_keys)}
    time.sleep(delay)
    resp = session.post(url, data=data)
    resp.raise_for_status()
    return resp.text

def clean_isbn(cell_html: str) -> str:
    soup = BeautifulSoup(cell_html, "html.parser")
    for span in soup.find_all("span", style=re.compile(r"display:\s*none")):
        span.decompose()
    text = soup.get_text(strip=True)
    return text.replace("-", "").strip()

def parse_adoption_html(html: str, fvcusno: str, school_id: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    crawled_on = datetime.now(timezone.utc).isoformat()

    course_inputs = soup.find_all(
        "input", attrs={"name": re.compile(r"^supsort_c_desc_\d+$")}
    )
    dept_inputs = soup.find_all(
        "input", attrs={"name": re.compile(r"^supsort_d_desc_\d+$")}
    )

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

    course_headers = soup.find_all("div", class_="cmCourseHeader")

    batch_dept_str = dept_map.get("1", "")

    for i, header in enumerate(course_headers):
        idx = str(i + 1)

        dept_str = dept_map.get(idx) or batch_dept_str
        parts = [p.strip() for p in dept_str.split("|div|")]
        term_name = parts[0] if len(parts) > 0 else ""
        department_name = parts[1] if len(parts) > 1 else ""

        course_str = course_map.get(idx, "")
        cparts = [p.strip() for p in course_str.split("|div|")]
        course_desc = cparts[0] if len(cparts) > 0 else ""

        dept_code, course_code, section, course_title = parse_course_desc(
            course_desc, department_name
        )

        source_url = CHOOSE_COURSES_URL.format(fvcusno=fvcusno)

        book_blocks = find_textbook_blocks(header)

        if not book_blocks:
            rows.append({
                "source_url": source_url,
                "school_id": school_id,
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": course_title,
                "section": section,
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
                    "section": section,
                    "section_instructor": "",
                    "term": term_name,
                    "isbn": book.get("isbn", ""),
                    "title": book.get("title", ""),
                    "author": book.get("author", ""),
                    "material_adoption_code": book.get("adoption_code", ""),
                    "crawled_on": crawled_on,
                })

    return rows

def parse_course_desc(course_desc: str, department_name: str) -> tuple[str, str, str, str]:
    if not course_desc:
        return ("", "", "", "")

    tokens = course_desc.split()
    if not tokens:
        return ("", "", "", "")

    first = tokens[0]
    m = re.match(r"^([A-Za-z]+)(\d[\w.]*)$", first)
    if m:

        dept_code = m.group(1).upper()
        course_code = "|" + m.group(2)
        rest = tokens[1:]

        section = ""
        if rest and re.match(r"^\d+$", rest[0]):
            section = "|" + rest[0]
            rest = rest[1:]
        course_title = " ".join(rest)
    elif re.match(r"^[A-Za-z]+$", first):

        dept_code = first.upper()
        rest = tokens[1:]
        course_code = ""
        section = ""
        if rest and re.match(r"^[A-Za-z]{0,3}\d+[A-Za-z]?$", rest[0]):
            course_code = "|" + rest[0]
            rest = rest[1:]
            if rest and re.match(r"^\d+$", rest[0]):
                section = "|" + rest[0]
                rest = rest[1:]
        course_title = " ".join(rest)
    else:
        dept_code = ""
        course_code = "|" + first if re.match(r"^\d", first) else first
        course_title = " ".join(tokens[1:])
        section = ""

    return (dept_code, course_code, section, course_title)

def find_textbook_blocks(course_header) -> list[dict]:
    books = []

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

def write_csv(rows: list[dict], filepath: str) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

def _refresh_session(fvcusno: str, flaresolverr_url: str | None, delay: float):
    if flaresolverr_url:
        print(f"\n  [WARN] 403 — re-bootstrapping via FlareSolverr...")
        time.sleep(max(delay * 8, 10))
        cookies, ua, html = fs_bootstrap(fvcusno, flaresolverr_url)
        session = make_session(cookies=cookies, user_agent=ua)
        info = init_session(session, fvcusno, preloaded_html=html)
    else:
        print(f"\n  [WARN] 403 — refreshing session (plain curl_cffi)...")
        time.sleep(delay * 4)
        session = make_session()
        info = init_session(session, fvcusno)
    csid = info["csid"]
    print(f"  [*] New CSID: {csid}")
    return session, csid

def scrape(
    fvcusno: str,
    school_id: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    output_dir: str | None = None,
    delay: float = DEFAULT_DELAY,
    flaresolverr_url: str | None = None,
) -> list[dict]:
    if school_id is None:
        school_id = fvcusno

    print(f"[*] Initializing session for FVCUSNO={fvcusno}...")
    if flaresolverr_url:
        cookies, ua, preloaded_html = fs_bootstrap(fvcusno, flaresolverr_url)
        session = make_session(cookies=cookies, user_agent=ua)
        info = init_session(session, fvcusno, preloaded_html=preloaded_html)
    else:
        session = make_session()
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

    all_courses = []
    for term_id, term_name in terms:
        for dept_id, dept_name, dept_enckey in depts:
            print(f"[*] Fetching courses: {term_name} / {dept_name}...")
            try:
                courses = fetch_courses(
                    session, csid, fvcusno, term_id, dept_id, dept_enckey, delay
                )
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status == 403:
                    print(f"  [WARN] 403 on course fetch — refreshing session and retrying...")
                    session, csid = _refresh_session(fvcusno, flaresolverr_url, delay)
                    courses = fetch_courses(
                        session, csid, fvcusno, term_id, dept_id, dept_enckey, delay
                    )
                else:
                    raise
            print(f"    Found {len(courses)} courses")
            for c in courses:
                all_courses.append((term_name, dept_name, c))

    if not all_courses:
        print("[!] No courses found. Exiting.")
        return []

    print(f"\n[*] Fetching textbook adoptions for {len(all_courses)} courses...")
    all_rows = []
    course_keys = [c[2].get("COURSE_ENC", "") for c in all_courses if c[2].get("COURSE_ENC")]

    batches = [
        course_keys[i : i + batch_size]
        for i in range(0, len(course_keys), batch_size)
    ]

    for batch in tqdm(batches, desc="Fetching adoptions"):
        try:
            html = fetch_adoptions(session, csid, fvcusno, batch, delay)
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 403:
                try:
                    session, csid = _refresh_session(fvcusno, flaresolverr_url, delay)
                    html = fetch_adoptions(session, csid, fvcusno, batch, delay)
                except Exception as retry_exc:
                    print(f"  [ERROR] Retry failed: {retry_exc} — skipping batch")
                    continue
            else:
                print(f"\n  [ERROR] Unexpected error: {exc} — skipping batch")
                continue
        rows = parse_adoption_html(html, fvcusno, school_id)
        all_rows.extend(rows)

    return all_rows

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

    raw = resolve_fvcusno(args.url, args.fvcusno)
    if not raw.isdigit():
        print(f"[*] Resolving FVCUSNO from URL: {raw}")
        fvcusno = discover_fvcusno(session, raw)
        print(f"    Discovered FVCUSNO: {fvcusno}")
    else:
        fvcusno = raw

    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "data",
            f"bnc_{fvcusno}_textbooks",
        )

    school_id = args.school_id or fvcusno

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
