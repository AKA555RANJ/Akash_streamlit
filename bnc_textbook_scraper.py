import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

import requests as std_requests
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

BASE_URL = "https://bncvirtual.com"
CHOOSE_COURSES_URL = BASE_URL + "/vb_buy2.php?FVCUSNO={fvcusno}&ACTION=chooseCourses"
COURSE_SEARCH_URL  = BASE_URL + "/vb_crs_srch.php?CSID={csid}&FVCUSNO={fvcusno}"
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
    "updated_on",
]

DEFAULT_BATCH_SIZE    = 25
DEFAULT_DELAY         = 0.5
FLARESOLVERR_DEFAULT  = "http://localhost:8191/v1"

_TERM_SUFFIX_RE = re.compile(
    r"\s*\((?:Order Now|Pre-?Order|Preorder|Coming Soon)[^)]*\)\s*$",
    re.IGNORECASE,
)


def clean_term(term):
    return _TERM_SUFFIX_RE.sub("", (term or "").strip())


def make_session(cookies=None, user_agent=None):
    session = cffi_requests.Session(impersonate="chrome")
    if cookies:
        for name, value in cookies.items():
            session.cookies.set(name, value, domain="bncvirtual.com")
    if user_agent:
        session.headers.update({"User-Agent": user_agent})
    return session


def _fs_session_name(fvcusno):
    return f"bnc_{fvcusno}_scraper"


def _fs_create(flaresolverr_url, session_name):
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


def _fs_destroy(flaresolverr_url, session_name):
    try:
        std_requests.post(
            flaresolverr_url,
            json={"cmd": "sessions.destroy", "session": session_name},
            timeout=10,
        )
    except Exception:
        pass


def _fs_get(flaresolverr_url, session_name, url, max_timeout=120000):
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


def fs_bootstrap(fvcusno, flaresolverr_url=FLARESOLVERR_DEFAULT):
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


def resolve_fvcusno(url, fvcusno):
    if fvcusno:
        return fvcusno
    if url:
        qs = parse_qs(urlparse(url).query)
        if "FVCUSNO" in qs:
            return qs["FVCUSNO"][0]
        return url
    raise ValueError("Either --url or --fvcusno must be provided")


def discover_fvcusno(session, url):
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


def init_session(session, fvcusno, preloaded_html=None):
    if preloaded_html:
        html = preloaded_html
    else:
        resp = session.get(CHOOSE_COURSES_URL.format(fvcusno=fvcusno))
        resp.raise_for_status()
        html = resp.text

    m = re.search(r"var\s+CSID\s*=\s*'([^']+)'", html)
    if not m:
        raise RuntimeError("Could not extract CSID from chooseCourses page")
    csid = m.group(1)

    seen_terms = set()
    terms = []
    # Format 1: selectTerm(this, '12345', 'Spring 2026') — term ID is 2nd arg
    # Format 2: selectTerm('12345', 'Spring 2026', ...) — term ID is 1st arg
    term_hits = re.findall(r"selectTerm\([^,]*,\s*'(\d+)',\s*'([^']+)'", html)
    if not term_hits:
        term_hits = re.findall(r"selectTerm\(\s*'(\d+)',\s*'([^']+)'", html)
    for tid, tname in term_hits:
        if tid not in seen_terms:
            seen_terms.add(tid)
            terms.append((tid, tname))

    seen_depts = set()
    depts = []
    for did, dname, denc in re.findall(
        r"selectDept\([^,]*,\s*'([^']+)',\s*'([^']+)',\s*[^,]*,\s*'([^']*)'", html
    ):
        if did not in seen_depts:
            seen_depts.add(did)
            depts.append((did, dname, denc))

    # Fallback: single pre-selected dept via hidden input (e.g. schools with only one dept)
    if not depts:
        m = re.search(
            r"id=['\"]sole_selected_dept['\"][^>]*value=['\"](\d+)['\"][^>]*data-enckey=['\"]([^'\"]+)['\"]",
            html
        )
        if not m:
            m = re.search(
                r"id=['\"]sole_selected_dept['\"][^>]*data-enckey=['\"]([^'\"]+)['\"][^>]*value=['\"](\d+)['\"]",
                html
            )
            if m:
                m = type('m', (), {'group': lambda self, i: [None, m.group(2), m.group(1)][i]})()
        if m:
            dept_id  = m.group(1)
            dept_enc = m.group(2)
            # Extract dept name from nearby span
            name_m = re.search(r"class=['\"][^'\"]*ddIconTxt[^'\"]*['\"][^>]*>([^<]+)<", html)
            dept_name = name_m.group(1).strip() if name_m else "DEFAULT"
            depts.append((dept_id, dept_name, dept_enc))

    return {"csid": csid, "fvcusno": fvcusno, "terms": terms, "depts": depts}


def fetch_courses(session, csid, fvcusno, term_id, dept_id, dept_enckey, delay):
    time.sleep(delay)
    resp = session.post(
        COURSE_SEARCH_URL.format(csid=csid, fvcusno=fvcusno),
        data={"FvTerm": term_id, "FvDept": dept_enckey, "R": "1"},
    )
    resp.raise_for_status()
    try:
        result = resp.json()
    except Exception:
        print(f"  [WARN] Non-JSON response for term={term_id}, dept={dept_id}")
        return []
    courses = []
    if "success" in result and isinstance(result["success"], dict):
        for dept_courses in result["success"].values():
            if isinstance(dept_courses, list):
                courses.extend(dept_courses)
            elif isinstance(dept_courses, dict):
                for item in dept_courses.values():
                    if isinstance(item, dict):
                        courses.append(item)
    return courses


def fetch_adoptions(session, csid, fvcusno, course_keys, delay):
    time.sleep(delay)
    resp = session.post(
        CHOOSE_ADOPTIONS_URL.format(csid=csid, fvcusno=fvcusno),
        data={"fvCourseKeyList": ",".join(course_keys)},
    )
    resp.raise_for_status()
    return resp.text


def clean_isbn(cell_html):
    soup = BeautifulSoup(cell_html, "html.parser")
    for span in soup.find_all("span", style=re.compile(r"display:\s*none")):
        span.decompose()
    return soup.get_text(strip=True).replace("-", "").strip()


def parse_course_desc(course_desc, department_name=""):
    if not course_desc:
        return "", "", "", ""
    tokens = course_desc.split()
    if not tokens:
        return "", "", "", ""
    first = tokens[0]
    m = re.match(r"^([A-Za-z]+)\*(\d+[A-Za-z]*)\*(\S+)$", first)
    if m:
        dept_code   = m.group(1).upper()
        course_code = "|" + m.group(2)
        section     = "|" + m.group(3)
        return dept_code, course_code, section, " ".join(tokens[1:])
    m = re.match(r"^([A-Za-z]+)-(\d+[A-Za-z]*)-(\w[\w.-]*)$", first)
    if m:
        dept_code   = m.group(1).upper()
        course_code = "|" + m.group(2)
        section     = "|" + m.group(3)
        return dept_code, course_code, section, " ".join(tokens[1:])
    m = re.match(r"^([A-Za-z]+)-(\d+[A-Za-z]*)$", first)
    if m:
        dept_code   = m.group(1).upper()
        course_code = "|" + m.group(2)
        return dept_code, course_code, "", " ".join(tokens[1:])
    m = re.match(r"^([A-Za-z]+)(\d+[A-Za-z]*)-(\S+)$", first)
    if m:
        dept_code   = m.group(1).upper()
        course_code = "|" + m.group(2)
        section     = "|" + m.group(3)
        return dept_code, course_code, section, " ".join(tokens[1:])
    m = re.match(r"^([A-Za-z]+)(\d[\w.]*)$", first)
    if m:
        dept_code   = m.group(1).upper()
        course_code = "|" + m.group(2)
        rest        = tokens[1:]
        section = ""
        if rest and re.match(r"^[A-Za-z]{0,3}\d+[A-Za-z]{0,3}$", rest[0]):
            section = "|" + rest[0]
            rest    = rest[1:]
        if not section and rest and re.match(r"^\d+\.\d+$", rest[0]):
            section = "|" + rest[0]
            rest    = rest[1:]
        if not section and rest and re.match(r"^[A-Z]{1,4}:?$", rest[0]) and len(rest) >= 2:
            section = "|" + rest[0].rstrip(":")
            rest    = rest[1:]
        return dept_code, course_code, section, " ".join(rest)
    if re.match(r"^[A-Za-z][A-Za-z&.]*$", first):
        dept_code   = first.upper()
        rest        = tokens[1:]
        course_code = ""
        section     = ""
        # Single-letter type prefix before course number (e.g. "BIO L 111 01 Title", "PTA L 122 HY01 Title")
        if rest and re.match(r"^[A-Z]$", rest[0]) and len(rest) >= 3 and \
                re.match(r"^\d[\w.]*$", rest[1]) and \
                re.match(r"^(\d+|[A-Za-z]{0,3}\d+[A-Za-z]{0,3})$", rest[2]):
            section     = "|" + rest[0] + rest[2]
            course_code = "|" + rest[1]
            rest        = rest[3:]
        elif rest and re.match(r"^\d+[A-Za-z]*/\d+[A-Za-z]*$", rest[0]):
            # Slash-joined dual course code (e.g. 331/332 01 LANG DEV)
            course_code = "|" + rest[0]
            rest        = rest[1:]
            if rest and re.match(r"^[A-Za-z]{0,3}\d+[A-Za-z]{0,3}$", rest[0]):
                section = "|" + rest[0]
                rest    = rest[1:]
        elif rest and re.match(r"^[A-Za-z]{0,3}\d[\w.\-]*$", rest[0]):
            course_code = "|" + rest[0]
            rest        = rest[1:]
            # Split COURSE_SECTION underscore (e.g. 107_B 0001 → course 107, section B_0001)
            m_us = re.match(r"^(\d+[A-Za-z]*)_(\w+)$", course_code.lstrip("|"))
            if m_us:
                course_code = "|" + m_us.group(1)
                sec_part    = m_us.group(2)
                if rest and re.match(r"^(\d{4}|[A-Z]{1,3}\d{2,3})$", rest[0]):
                    section = "|" + sec_part + "_" + rest[0]
                    rest    = rest[1:]
                else:
                    section = "|" + sec_part
            # Split COURSE-SECTION hyphen (e.g. 321-01, 210L-AB, 290-BLENDED)
            m2 = re.match(r"^(\d+[A-Za-z]*)--?([A-Za-z]\w*|\d{2,}[A-Za-z]*)$", course_code.lstrip("|"))
            if m2 and not section:
                course_code = "|" + m2.group(1)
                section     = "|" + m2.group(2)
            if not section and rest and re.match(r"^[A-Za-z]{0,3}\d+[A-Za-z]{0,3}$", rest[0]):
                section = "|" + rest[0]
                rest    = rest[1:]
            if not section and rest and re.match(r"^\d+\.\d+$", rest[0]):
                section = "|" + rest[0]
                rest    = rest[1:]
            if not section and rest and re.match(r"^[A-Z]{1,4}:?$", rest[0]) and len(rest) >= 2:
                section = "|" + rest[0].rstrip(":")
                rest    = rest[1:]
            # Standalone hyphen separator (e.g. "290 - BL GENERAL MICRO")
            if not section and rest and rest[0] == "-" and len(rest) >= 2:
                rest = rest[1:]
                section = "|" + rest[0]
                rest    = rest[1:]
        return dept_code, course_code, section, " ".join(rest)
    dept_code   = department_name.upper() if department_name else ""
    course_code = "|" + first if re.match(r"^\d", first) else first
    return dept_code, course_code, "", " ".join(tokens[1:])


def find_textbook_blocks(course_header):
    scope = course_header.find_next_sibling("div", class_=re.compile(r"crs_adpts_collapse"))
    if scope is None:
        return []
    adoption_codes = scope.find_all("p",  class_=re.compile(r"text-uppercase"))
    titles         = scope.find_all("h2", class_=re.compile(r"p0m0"))
    info_tables    = scope.find_all("table", class_="cmTableBkInfo")
    books = []
    for j in range(max(len(adoption_codes), len(titles), len(info_tables))):
        book = {}
        if j < len(adoption_codes):
            book["adoption_code"] = adoption_codes[j].get_text(strip=True)
        if j < len(titles):
            h2 = titles[j]
            span = h2.find("span", class_=re.compile(r"nobold|small"))
            if span:
                span.extract()
            book["title"] = h2.get_text(strip=True)
        if j < len(info_tables):
            for row in info_tables[j].find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                label = cells[0].get_text(strip=True).rstrip(":")
                if label == "Author":
                    book["author"] = cells[1].get_text(strip=True)
                elif label == "ISBN-13":
                    book["isbn"] = clean_isbn(str(cells[1]))
                elif label == "ISBN-10" and not book.get("isbn"):
                    book["isbn"] = clean_isbn(str(cells[1]))
        if book:
            books.append(book)
    return books


def parse_adoption_html(html, fvcusno, school_id, batch_courses=None):
    soup       = BeautifulSoup(html, "html.parser")
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    source_url = CHOOSE_COURSES_URL.format(fvcusno=fvcusno)

    dept_map = {}
    for inp in soup.find_all("input", attrs={"name": re.compile(r"^supsort_d_desc_\d+$")}):
        m = re.search(r"_(\d+)$", inp.get("name", ""))
        if m:
            dept_map[m.group(1)] = inp.get("value", "")

    course_map = {}
    for inp in soup.find_all("input", attrs={"name": re.compile(r"^supsort_c_desc_\d+$")}):
        m = re.search(r"_(\d+)$", inp.get("name", ""))
        if m:
            course_map[m.group(1)] = inp.get("value", "")

    batch_dept_str = dept_map.get("1", "")
    rows = []

    for i, header in enumerate(soup.find_all("div", class_="cmCourseHeader")):
        idx         = str(i + 1)
        dept_str    = dept_map.get(idx) or batch_dept_str
        parts       = [p.strip() for p in dept_str.split("|div|")]
        term_name   = clean_term(parts[0]) if parts else ""
        dept_name   = parts[1] if len(parts) > 1 else ""

        if not term_name and batch_courses and i < len(batch_courses):
            term_name = clean_term(batch_courses[i][0])
        course_str  = course_map.get(idx, "")
        cparts      = [p.strip() for p in course_str.split("|div|")]
        course_desc = cparts[0] if cparts else ""

        dept_code, course_code, section, course_title = parse_course_desc(course_desc, dept_name)

        base = {
            "source_url":         source_url,
            "school_id":          school_id,
            "department_code":    dept_code,
            "course_code":        course_code,
            "course_title":       course_title,
            "section":            section,
            "section_instructor": "",
            "term":               term_name,
            "crawled_on":         crawled_on,
            "updated_on":         crawled_on,
        }

        books = find_textbook_blocks(header)
        if not books:
            rows.append({**base, "isbn": "", "title": "", "author": "", "material_adoption_code": ""})
        else:
            for book in books:
                rows.append({
                    **base,
                    "isbn":                  book.get("isbn", ""),
                    "title":                 book.get("title", ""),
                    "author":                book.get("author", ""),
                    "material_adoption_code": book.get("adoption_code", ""),
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


def log_missing_enc(log_path, fvcusno, term_name, dept_name, course_desc):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    new_file  = not os.path.exists(log_path) or os.path.getsize(log_path) == 0
    with open(log_path, "a", encoding="utf-8") as f:
        if new_file:
            f.write("timestamp\tfvcusno\treason\tterm\tdepartment\tcourse_desc\trequest_body\n")
        f.write(f"{timestamp}\t{fvcusno}\tMISSING_COURSE_ENC\t{term_name}\t{dept_name}\t{course_desc}\t\n")


def log_failed_batch(log_path, fvcusno, batch_keys, status_code, error_msg, batch_courses=None):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    body      = "fvCourseKeyList=" + ",".join(batch_keys)
    new_file  = not os.path.exists(log_path) or os.path.getsize(log_path) == 0
    with open(log_path, "a", encoding="utf-8") as f:
        if new_file:
            f.write("timestamp\tfvcusno\treason\tterm\tdepartment\tcourse_desc\trequest_body\n")
        if batch_courses:
            for term_name, dept_name, course in batch_courses:
                course_desc = course.get("COURSE_DESC", "")
                f.write(f"{timestamp}\t{fvcusno}\tHTTP_{status_code}\t{term_name}\t{dept_name}\t{course_desc}\t{body}\n")
        else:
            f.write(f"{timestamp}\t{fvcusno}\tHTTP_{status_code}\t\t\t\t{body}\n")
    tqdm.write(f"  [FAILED] Logged to {os.path.basename(log_path)}: status={status_code} keys={len(batch_keys)}")


def write_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def get_scraped_keys(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return {
            (r.get("term", ""), r.get("department_code", ""), r.get("course_code", ""))
            for r in csv.DictReader(f)
        }


def load_failed_courses(log_path):
    """Return set of (term, department, course_desc) tuples from HTTP_* failure rows."""
    failed = set()
    if not os.path.exists(log_path):
        return failed
    with open(log_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row.get("reason", "").startswith("HTTP_") and row.get("course_desc"):
                failed.add((row["term"], row["department"], row["course_desc"]))
    return failed


def scrape_retry_log(
    log_path,
    fvcusno,
    school_id=None,
    batch_size=DEFAULT_BATCH_SIZE,
    delay=DEFAULT_DELAY,
    flaresolverr_url=None,
    csv_path=None,
    new_log_path=None,
):
    if school_id is None:
        school_id = fvcusno

    if new_log_path:
        os.makedirs(os.path.dirname(new_log_path), exist_ok=True)
        if not os.path.exists(new_log_path) or os.path.getsize(new_log_path) == 0:
            with open(new_log_path, "w", encoding="utf-8") as f:
                f.write("timestamp\tfvcusno\treason\tterm\tdepartment\tcourse_desc\trequest_body\n")

    failed_set = load_failed_courses(log_path)
    if not failed_set:
        print("[!] No retryable courses found in log (no HTTP_* rows with course_desc).")
        return []

    print(f"[*] {len(failed_set)} course(s) to retry from: {os.path.basename(log_path)}")

    print(f"[*] Initializing session for FVCUSNO={fvcusno}...")
    if flaresolverr_url:
        cookies, ua, preloaded = fs_bootstrap(fvcusno, flaresolverr_url)
        session = make_session(cookies=cookies, user_agent=ua)
        info    = init_session(session, fvcusno, preloaded_html=preloaded)
    else:
        session = make_session()
        info    = init_session(session, fvcusno)

    csid  = info["csid"]
    terms = info["terms"]
    depts = info["depts"]
    print(f"    CSID: {csid}")

    # Index failures by (term, dept) so we only hit term/dept combos that had failures
    by_term_dept = {}
    for term, dept, course_desc in failed_set:
        by_term_dept.setdefault((term, dept), set()).add(course_desc)

    target_courses = []
    for term_id, term_name in terms:
        for dept_id, dept_name, dept_enckey in depts:
            wanted_descs = by_term_dept.get((term_name, dept_name))
            if not wanted_descs:
                continue
            print(f"[*] Re-fetching courses: {term_name} / {dept_name} ({len(wanted_descs)} targets)...")
            try:
                courses = fetch_courses(session, csid, fvcusno, term_id, dept_id, dept_enckey, delay)
            except Exception as exc:
                if getattr(getattr(exc, "response", None), "status_code", None) == 403:
                    session, csid = _refresh_session(fvcusno, flaresolverr_url, delay)
                    courses = fetch_courses(session, csid, fvcusno, term_id, dept_id, dept_enckey, delay)
                else:
                    raise
            matched = [c for c in courses if c.get("COURSE_DESC", "") in wanted_descs]
            print(f"    Matched {len(matched)} / {len(wanted_descs)} target courses")
            for c in matched:
                target_courses.append((term_name, dept_name, c))

    if not target_courses:
        print("[!] None of the failed courses were found in fresh discovery.")
        return []

    missing_enc = [c for c in target_courses if not c[2].get("COURSE_ENC")]
    valid_courses = [c for c in target_courses if c[2].get("COURSE_ENC")]

    if missing_enc and new_log_path:
        for term_name, dept_name, c in missing_enc:
            log_missing_enc(new_log_path, fvcusno, term_name, dept_name, c.get("COURSE_DESC", ""))

    print(f"\n[*] Fetching adoptions for {len(valid_courses)} recovered course(s)...")
    batches      = [valid_courses[i:i + batch_size] for i in range(0, len(valid_courses), batch_size)]
    all_rows     = []
    failed_count = 0

    for batch in tqdm(batches, desc="Retrying adoptions"):
        batch_keys = [c[2]["COURSE_ENC"] for c in batch]
        html       = None
        status     = None
        error_msg  = None

        try:
            html = fetch_adoptions(session, csid, fvcusno, batch_keys, delay)
        except Exception as exc:
            status    = getattr(getattr(exc, "response", None), "status_code", None)
            error_msg = str(exc)
            if status == 403:
                try:
                    session, csid = _refresh_session(fvcusno, flaresolverr_url, delay)
                    html = fetch_adoptions(session, csid, fvcusno, batch_keys, delay)
                    status = None; error_msg = None
                except Exception as retry_exc:
                    status    = getattr(getattr(retry_exc, "response", None), "status_code", None) or 403
                    error_msg = str(retry_exc)
            elif status is not None and 400 <= status < 500:
                try:
                    time.sleep(delay * 4)
                    html = fetch_adoptions(session, csid, fvcusno, batch_keys, delay)
                    status = None; error_msg = None
                except Exception as retry_exc:
                    status    = getattr(getattr(retry_exc, "response", None), "status_code", None) or status
                    error_msg = str(retry_exc)

        if error_msg is not None:
            failed_count += 1
            if new_log_path:
                log_failed_batch(new_log_path, fvcusno, batch_keys, status or "ERR", error_msg, batch_courses=batch)
            continue

        rows = parse_adoption_html(html, fvcusno, school_id, batch_courses=batch)
        if csv_path and rows:
            append_csv(rows, csv_path)
        all_rows.extend(rows)

    if failed_count:
        print(f"\n[!] {failed_count} batch(es) still failed — logged to {new_log_path or 'stderr'}")

    return all_rows


def _refresh_session(fvcusno, flaresolverr_url, delay):
    if flaresolverr_url:
        print("\n  [WARN] 403 — re-bootstrapping via FlareSolverr...")
        time.sleep(max(delay * 8, 10))
        cookies, ua, html = fs_bootstrap(fvcusno, flaresolverr_url)
        session = make_session(cookies=cookies, user_agent=ua)
        info    = init_session(session, fvcusno, preloaded_html=html)
    else:
        print("\n  [WARN] 403 — refreshing session...")
        time.sleep(delay * 4)
        session = make_session()
        info    = init_session(session, fvcusno)
    print(f"  [*] New CSID: {info['csid']}")
    return session, info["csid"]


def scrape(
    fvcusno,
    school_id=None,
    batch_size=DEFAULT_BATCH_SIZE,
    delay=DEFAULT_DELAY,
    flaresolverr_url=None,
    session=None,
    csv_path=None,
    log_path=None,
    fresh=False,
    max_batches=None,
):
    if school_id is None:
        school_id = fvcusno

    if csv_path and fresh and os.path.exists(csv_path):
        os.remove(csv_path)
        print("[*] Fresh run — deleted existing CSV.")
    if log_path and fresh and os.path.exists(log_path):
        os.remove(log_path)
        print("[*] Fresh run — deleted existing fail log.")

    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        if not os.path.exists(log_path) or os.path.getsize(log_path) == 0:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("timestamp\tfvcusno\treason\tterm\tdepartment\tcourse_desc\trequest_body\n")

    done_keys = set()
    if csv_path:
        done_keys = get_scraped_keys(csv_path)
        if done_keys:
            print(f"[*] {len(done_keys)} course/term combos already scraped — resuming.")

    print(f"[*] Initializing session for FVCUSNO={fvcusno}...")
    if flaresolverr_url:
        cookies, ua, preloaded = fs_bootstrap(fvcusno, flaresolverr_url)
        session = make_session(cookies=cookies, user_agent=ua)
        info    = init_session(session, fvcusno, preloaded_html=preloaded)
    else:
        if session is None:
            session = make_session()
        info = init_session(session, fvcusno)

    csid  = info["csid"]
    terms = info["terms"]
    depts = info["depts"]

    print(f"    CSID: {csid}")
    print(f"    Terms: {[t[1] for t in terms]}")
    print(f"    Departments: {[d[1] for d in depts]}")

    if not terms:
        print("[!] No terms found.")
        return []
    if not depts:
        print("[!] No departments found.")
        return []

    all_courses = []
    for term_id, term_name in terms:
        for dept_id, dept_name, dept_enckey in depts:
            print(f"[*] Fetching courses: {term_name} / {dept_name}...")
            try:
                courses = fetch_courses(session, csid, fvcusno, term_id, dept_id, dept_enckey, delay)
            except Exception as exc:
                if getattr(getattr(exc, "response", None), "status_code", None) == 403:
                    print("  [WARN] 403 on course fetch — refreshing session and retrying...")
                    session, csid = _refresh_session(fvcusno, flaresolverr_url, delay)
                    courses = fetch_courses(session, csid, fvcusno, term_id, dept_id, dept_enckey, delay)
                else:
                    raise

            if done_keys:
                done_set = {(k[0], k[1], k[2]) for k in done_keys}
                before   = len(courses)
                courses  = [
                    c for c in courses
                    if (clean_term(term_name),) + parse_course_desc(c.get("COURSE_DESC", ""), dept_name)[:2]
                    not in done_set
                ]
                skipped = before - len(courses)
                if skipped:
                    print(f"    Skipped {skipped} already-scraped courses")

            print(f"    Found {len(courses)} courses")
            for c in courses:
                all_courses.append((term_name, dept_name, c))

    if not all_courses:
        print("[!] No new courses to scrape.")
        return []

    missing_enc = [c for c in all_courses if not c[2].get("COURSE_ENC")]
    if missing_enc and log_path:
        for term_name, dept_name, c in missing_enc:
            log_missing_enc(log_path, fvcusno, term_name, dept_name, c.get("COURSE_DESC", ""))
        print(f"[!] {len(missing_enc)} course(s) had no COURSE_ENC — logged to {os.path.basename(log_path)}")

    valid_courses = [c for c in all_courses if c[2].get("COURSE_ENC")]
    batches       = [valid_courses[i:i + batch_size] for i in range(0, len(valid_courses), batch_size)]

    if max_batches:
        batches = batches[:max_batches]
        print(f"\n[*] Fetching adoptions for {len(all_courses)} courses (sample: {max_batches} batch(es))...")
    else:
        print(f"\n[*] Fetching textbook adoptions for {len(all_courses)} courses ({len(batches)} batches)...")

    all_rows     = []
    failed_count = 0

    for batch in tqdm(batches, desc="Fetching adoptions"):
        batch_keys = [c[2]["COURSE_ENC"] for c in batch]
        html       = None
        status     = None
        error_msg  = None

        try:
            html = fetch_adoptions(session, csid, fvcusno, batch_keys, delay)
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            error_msg = str(exc)

            if status == 403:
                try:
                    session, csid = _refresh_session(fvcusno, flaresolverr_url, delay)
                    html = fetch_adoptions(session, csid, fvcusno, batch_keys, delay)
                    status    = None
                    error_msg = None
                except Exception as retry_exc:
                    status    = getattr(getattr(retry_exc, "response", None), "status_code", None) or 403
                    error_msg = str(retry_exc)

            elif status is not None and 400 <= status < 500:
                try:
                    time.sleep(delay * 4)
                    html = fetch_adoptions(session, csid, fvcusno, batch_keys, delay)
                    status    = None
                    error_msg = None
                except Exception as retry_exc:
                    status    = getattr(getattr(retry_exc, "response", None), "status_code", None) or status
                    error_msg = str(retry_exc)

        if error_msg is not None:
            failed_count += 1
            if log_path:
                log_failed_batch(log_path, fvcusno, batch_keys, status or "ERR", error_msg, batch_courses=batch)
            else:
                tqdm.write(f"  [SKIP] batch of {len(batch_keys)} courses: status={status} — {error_msg}")
            continue

        rows = parse_adoption_html(html, fvcusno, school_id, batch_courses=batch)
        if csv_path and rows:
            append_csv(rows, csv_path)
        all_rows.extend(rows)

    if failed_count:
        print(f"\n[!] {failed_count} batch(es) failed and were logged to {log_path or 'stderr'}")

    return all_rows


def main():
    parser = argparse.ArgumentParser(
        description="Scrape textbook adoption data from BNC Virtual bookstores."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url",     help="Bookstore URL (e.g. https://bncvirtual.com/pacenyc.htm)")
    group.add_argument("--fvcusno", help="FVCUSNO institution ID")

    parser.add_argument("--school-id",   default=None, help="School ID written into CSV (defaults to FVCUSNO)")
    parser.add_argument("--school-name", default=None, help="School slug for output path (e.g. pace_university_new_york_city)")
    parser.add_argument("--output-dir",  default=None, help="Override output directory")
    parser.add_argument("--batch-size",  type=int,   default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--delay",       type=float, default=DEFAULT_DELAY)
    parser.add_argument("--max-batches", type=int,   default=None, help="Limit batches (for sampling)")
    parser.add_argument("--flaresolverr-url", default=None, help="FlareSolverr endpoint for Cloudflare bypass")
    parser.add_argument("--fresh", action="store_true", help="Delete existing CSV and rescrape from scratch")
    parser.add_argument("--retry-log", default=None, metavar="LOG_PATH",
                        help="Re-fetch only courses that failed in a previous run's fail log")

    args = parser.parse_args()

    session = make_session()

    raw = resolve_fvcusno(args.url, args.fvcusno)
    if not raw.isdigit():
        print(f"[*] Resolving FVCUSNO from: {raw}")
        try:
            fvcusno = discover_fvcusno(session, raw)
        except Exception as exc:
            print(f"[!] Could not discover FVCUSNO: {exc}")
            print("    Verify the URL points to a BNC Virtual bookstore.")
            raise SystemExit(1)
        print(f"    FVCUSNO: {fvcusno}")
    else:
        fvcusno = raw

    school_id = args.school_id or fvcusno

    if args.output_dir:
        output_dir = args.output_dir
        csv_name   = os.path.basename(output_dir.rstrip("/\\")) + ".csv"
    elif args.school_name and school_id != fvcusno:
        slug       = f"{args.school_name}__{school_id}__bks"
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", slug)
        csv_name   = slug + ".csv"
    else:
        slug       = f"bnc_{fvcusno}_textbooks"
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", slug)
        csv_name   = slug + ".csv"

    csv_path = os.path.join(output_dir, csv_name)
    log_path = os.path.join(output_dir, csv_name.replace(".csv", "__failed_batches.log"))
    print(f"[*] Output : {csv_path}")
    print(f"[*] Fail log: {log_path}")

    if args.retry_log:
        rows = scrape_retry_log(
            log_path=args.retry_log,
            fvcusno=fvcusno,
            school_id=school_id,
            batch_size=args.batch_size,
            delay=args.delay,
            flaresolverr_url=args.flaresolverr_url,
            csv_path=csv_path,
            new_log_path=log_path,
        )
    else:
        rows = scrape(
            fvcusno=fvcusno,
            school_id=school_id,
            batch_size=args.batch_size,
            delay=args.delay,
            flaresolverr_url=args.flaresolverr_url,
            session=session,
            csv_path=csv_path,
            log_path=log_path,
            fresh=args.fresh,
            max_batches=args.max_batches,
        )

    if rows or os.path.exists(csv_path):
        total = (sum(1 for _ in open(csv_path, encoding="utf-8")) - 1) if os.path.exists(csv_path) else len(rows)
        print(f"\n[+] Done — {total} total rows written to {csv_path}")
        print(f"    New rows this run : {len(rows)}")
        print(f"    Rows with ISBN    : {sum(1 for r in rows if r.get('isbn'))}")
        print(f"    Rows without ISBN : {sum(1 for r in rows if not r.get('isbn'))}")
        print(f"    Unique ISBNs      : {len({r['isbn'] for r in rows if r.get('isbn')})}")
    else:
        print("[!] No data collected.")


if __name__ == "__main__":
    main()
