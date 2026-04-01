#!/usr/bin/env python3
"""
Stark State College Bookstore Textbook Scraper
Platform: Timber (by Herkimer Media) — Drupal-based, integrates with Booklog POS
URL: https://shop.starkstate.edu/timber/college
"""

import csv
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

SCHOOL_NAME = "stark_state_college"
SCHOOL_ID = "3073939"
BASE_URL = "https://shop.starkstate.edu"
TIMBER_URL = BASE_URL + "/timber/college"
TIMBER_AJAX_URL = BASE_URL + "/timber/college/ajax"
FLARESOLVERR_URL = "http://localhost:8191/v1"

# Maps req-group-{code} class suffix to human-readable adoption label
ADOPTION_MAP = {
    "R": "Required",
    "O": "Optional",
    "C": "Choice",
    "N": "Not Required",
}

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

REQUEST_DELAY = 0.5

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")

FLARESOLVERR_SESSION = "stark_state_scraper"


def flaresolverr_create_session():
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
    }, timeout=120)
    resp.raise_for_status()


def flaresolverr_destroy_session():
    try:
        requests.post(FLARESOLVERR_URL, json={
            "cmd": "sessions.destroy",
            "session": FLARESOLVERR_SESSION,
        }, timeout=10)
    except Exception:
        pass


def flaresolverr_get(url, max_timeout=60000):
    resp = requests.post(FLARESOLVERR_URL, json={
        "cmd": "request.get",
        "url": url,
        "session": FLARESOLVERR_SESSION,
        "maxTimeout": max_timeout,
    }, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"FlareSolverr error: {data}")

    sol = data["solution"]
    html = sol.get("response", "")
    ua = sol.get("userAgent", "")

    cookies = {}
    for c in sol.get("cookies", []):
        if c.get("name"):
            cookies[c["name"]] = c["value"]

    return html, cookies, ua


def create_session():
    print("[*] Bootstrapping session via FlareSolverr...")
    flaresolverr_create_session()
    html, cookies, ua = flaresolverr_get(TIMBER_URL)

    if is_cloudflare_block(html):
        raise RuntimeError("Cloudflare challenge not bypassed")

    sess = requests.Session()
    sess.cookies.update(cookies)
    sess.headers.update({
        "User-Agent": ua,
        "Referer": TIMBER_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    print(f"[*] Session ready. Cookies: {list(cookies.keys())}")
    return sess, html


def refresh_session(sess):
    print("[*] Refreshing session via FlareSolverr...", flush=True)
    for attempt in range(5):
        try:
            flaresolverr_destroy_session()
            time.sleep(5 * (attempt + 1))
            return create_session()
        except Exception as e:
            print(f"  [WARN] Session refresh attempt {attempt + 1} failed: {e}", flush=True)
            if attempt == 4:
                raise


def is_cloudflare_block(text):
    lower = text[:1000].lower()
    return ("just a moment" in lower or
            "challenge-platform" in lower or
            "<title>attention" in lower)


def clean_term(label):
    """Strip parenthetical suffixes like '(Order Now)' from term labels."""
    return re.sub(r'\s*\(.*?\)\s*$', '', label).strip()


def format_course_code(code):
    """Prefix course code with pipe to preserve leading zeros. E.g. '2301' → '|2301'."""
    code = code.strip()
    if not code:
        return ""
    if code.startswith("|"):
        return code
    return f"|{code}"


def format_section_code(section):
    """Prefix section code with pipe to preserve leading zeros."""
    section = section.strip()
    if not section:
        return ""
    if section.startswith("|"):
        return section
    return f"|{section}"


def split_dept_course(raw):
    """Split 'ACCT 2301' into ('ACCT', '|2301'). Returns (raw, '') if no space."""
    raw = raw.strip()
    parts = raw.split(None, 1)
    if len(parts) == 2:
        return parts[0], format_course_code(parts[1])
    return raw, ""


def safe_get(sess, url, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, timeout=60)
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            if is_cloudflare_block(resp.text):
                raise RuntimeError("Cloudflare challenge detected")
            return resp.text
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] GET failed (attempt {attempt + 1}): {e}")
                time.sleep(2 * (attempt + 1))
            else:
                raise
    return ""


def safe_post(sess, url, data=None, json_data=None, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            if json_data is not None:
                resp = sess.post(url, json=json_data, timeout=60)
            else:
                resp = sess.post(url, data=data, timeout=60)
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            if is_cloudflare_block(resp.text):
                raise RuntimeError("Cloudflare challenge detected")
            return resp.text
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] POST failed (attempt {attempt + 1}): {e}")
                time.sleep(2 * (attempt + 1))
            else:
                raise
    return ""


def parse_drupal_ajax_html(text):
    """Unwrap Drupal Ajax JSON command array into concatenated HTML.

    Drupal Views AJAX returns:
        [{"command": "insert", "selector": "#...", "data": "<html fragment>"}, ...]

    If text is not JSON (plain HTML), return it unchanged.
    """
    text = text.strip()
    if not text.startswith("["):
        return text
    try:
        commands = json.loads(text)
        if isinstance(commands, list):
            fragments = [
                cmd.get("data", "")
                for cmd in commands
                if isinstance(cmd, dict) and cmd.get("command") in ("insert", "replace", "changed")
                and cmd.get("data")
            ]
            if fragments:
                return "\n".join(fragments)
    except (json.JSONDecodeError, ValueError):
        pass
    return text


def timber_ajax_get(sess, path, retries=3):
    """GET /timber/college/ajax?l={encoded_path}.

    The server maintains selection state (term/dept/course) in the Drupal session.
    Calls must be made sequentially: select term → select dept → select course → select section.
    """
    url = TIMBER_AJAX_URL + "?l=" + urllib.parse.quote(path, safe="")
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, timeout=30)
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            if is_cloudflare_block(resp.text):
                raise RuntimeError("Cloudflare challenge detected")
            return resp.text
        except RuntimeError:
            raise
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] timber_ajax_get {path} attempt {attempt + 1}: {e}")
                time.sleep(2 * (attempt + 1))
            else:
                raise
    return ""


def parse_tcc_links(html):
    """Parse Timber TCC navigation links from any level.

    Format: <a class='tcc-item-link' href='#' url='/college_dept/131073'>
              <span class='abbreviation'>ACC</span> - <span class='name'>Accounting</span>
            </a>

    Returns list of {"value": url_path, "code": short_code, "label": full_text}.
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for a in soup.find_all("a", class_="tcc-item-link"):
        url_val = a.get("url", "").strip()
        if not url_val or url_val == "#":
            continue
        abbr_el = a.find("span", class_="abbreviation")
        code = abbr_el.get_text(strip=True) if abbr_el else a.get_text(strip=True)
        label = a.get_text(strip=True)
        items.append({"value": url_val, "code": code, "label": label})
    return items


def split_course_label(label):
    """Split '121 - Introduction to Accounting' into ('121', 'Introduction to Accounting').

    Returns (course_num, course_title). If no separator found, returns (label, '').
    """
    label = label.strip()
    m = re.match(r"^(\d+[A-Za-z]?)\s*[-\u2013]\s*(.+)$", label)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return label, ""


def fetch_book_author(sess, nid, cadoption_id):
    """Fetch author from the Timber book details endpoint.

    URL: /timber/college/details/{nid}/{cadoption_id}
    Response contains: "Author: PATTON ISBN: ... Publisher: ... Edition: ..."

    Returns author string, or '' if unavailable.
    """
    if not nid or not cadoption_id:
        return ""
    try:
        url = f"{BASE_URL}/timber/college/details/{nid}/{cadoption_id}"
        time.sleep(0.2)
        resp = sess.get(url, timeout=10)
        if resp.status_code != 200:
            return ""
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, "html.parser")
        nothing_field = soup.find("div", class_="views-field-nothing")
        if nothing_field:
            text = nothing_field.get_text(" ", strip=True)
            m = re.search(r"Author:\s*([^\n]+?)(?:\s+ISBN:|\s+Publisher:|$)", text, re.I)
            if m:
                return m.group(1).strip()
    except Exception:
        pass
    return ""


def parse_timber_materials(sess, html, term_name, dept_code, course_code,
                           course_title, section_code):
    """Parse textbook materials from a Timber TCC section AJAX response.

    Response format:
        <div id='tcc-product' sectionid='...'>
          <div class='req-group req-group-R ...'>   ← adoption group
            <div class='timber-item-group ...'>
              <span class='tcc-product-title'>Book Title</span>
              <span class='tcc-sku-number'>(9781234567890)</span>
              <div class='chooser-product' nid='...' cadoption_id='...'>
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    tcc_product = soup.find(id="tcc-product")
    if not tcc_product:
        return results

    for req_group in tcc_product.find_all("div", class_=re.compile(r"\breq-group\b")):
        adoption = ""
        for cls in req_group.get("class", []):
            m = re.match(r"^req-group-([A-Z]+)$", cls)
            if m:
                adoption = ADOPTION_MAP.get(m.group(1), m.group(1))
                break

        for item_group in req_group.find_all("div", class_="timber-item-group"):
            isbn = ""
            title = ""

            sku_el = item_group.find("span", class_="tcc-sku-number")
            if sku_el:
                sku_text = sku_el.get_text(strip=True).strip("()")
                isbn_m = re.search(r"(\d{10,13})", sku_text.replace("-", ""))
                if isbn_m:
                    isbn = isbn_m.group(1)

            title_el = item_group.find("span", class_="tcc-product-title")
            if title_el:
                title = title_el.get_text(strip=True)

            author = ""
            chooser = item_group.find("div", class_="chooser-product")
            if chooser:
                nid = chooser.get("nid", "")
                cadoption_id = chooser.get("cadoption_id", "")
                author = fetch_book_author(sess, nid, cadoption_id)

            if isbn or title:
                results.append({
                    "department_code": dept_code,
                    "course_code": format_course_code(course_code),
                    "course_title": course_title,
                    "section": format_section_code(section_code),
                    "section_instructor": "",
                    "term": term_name,
                    "isbn": isbn,
                    "title": title,
                    "author": author,
                    "material_adoption_code": adoption,
                })

    if not results:
        results.append({
            "department_code": dept_code,
            "course_code": format_course_code(course_code),
            "course_title": course_title,
            "section": format_section_code(section_code),
            "section_instructor": "",
            "term": term_name,
            "isbn": "",
            "title": "",
            "author": "",
            "material_adoption_code": "No materials required",
        })

    return results


def parse_terms_from_page(html):
    """Extract available terms from the main Timber college page."""
    soup = BeautifulSoup(html, "html.parser")
    terms = []

    select = soup.find("select", id=re.compile(r"term", re.I))
    if not select:
        select = soup.find("select", attrs={"name": re.compile(r"term", re.I)})
    if not select:
        for s in soup.find_all("select"):
            options = s.find_all("option")
            for opt in options:
                text = opt.get_text(strip=True).upper()
                if any(kw in text for kw in ["FALL", "SPRING", "SUMMER", "WINTER"]):
                    select = s
                    break
            if select:
                break

    if select:
        for option in select.find_all("option"):
            val = option.get("value", "").strip()
            text = option.get_text(strip=True)
            if val and text and val != "" and val != "0":
                terms.append({"value": val, "label": text})
        return terms

    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True).upper()
        if any(kw in text for kw in ["FALL", "SPRING", "SUMMER", "WINTER"]):
            terms.append({"value": href, "label": link.get_text(strip=True)})

    for li in soup.find_all("li"):
        text = li.get_text(strip=True)
        if re.match(r"(FALL|SPRING|SUMMER|WINTER)\s+\d{4}", text, re.I):
            data_val = li.get("data-value", "") or li.get("data-id", "") or text
            terms.append({"value": data_val, "label": text})

    return terms


def parse_departments_from_html(html):
    """Extract departments from an HTML response."""
    soup = BeautifulSoup(html, "html.parser")
    depts = []

    select = soup.find("select", id=re.compile(r"dept", re.I))
    if not select:
        select = soup.find("select", attrs={"name": re.compile(r"dept", re.I)})

    if select:
        for option in select.find_all("option"):
            val = option.get("value", "").strip()
            text = option.get_text(strip=True)
            if val and text and val != "" and val != "0" and "select" not in text.lower():
                depts.append({"value": val, "label": text})
        return depts

    for link in soup.find_all("a", class_=re.compile(r"dept", re.I)):
        val = link.get("data-value", "") or link.get("href", "")
        text = link.get_text(strip=True)
        if val and text:
            depts.append({"value": val, "label": text})

    if not depts:
        for li in soup.find_all("li", class_=re.compile(r"dept", re.I)):
            val = li.get("data-value", "") or li.get("data-id", "")
            text = li.get_text(strip=True)
            if val and text:
                depts.append({"value": val, "label": text})

    return depts


def parse_courses_from_html(html):
    """Extract courses from an HTML response."""
    soup = BeautifulSoup(html, "html.parser")
    courses = []

    select = soup.find("select", id=re.compile(r"course", re.I))
    if not select:
        select = soup.find("select", attrs={"name": re.compile(r"course", re.I)})

    if select:
        for option in select.find_all("option"):
            val = option.get("value", "").strip()
            text = option.get_text(strip=True)
            if val and text and val != "" and val != "0" and "select" not in text.lower():
                courses.append({"value": val, "label": text})
        return courses

    for link in soup.find_all("a", class_=re.compile(r"course", re.I)):
        val = link.get("data-value", "") or link.get("href", "")
        text = link.get_text(strip=True)
        if val and text:
            courses.append({"value": val, "label": text})

    return courses


def parse_sections_from_html(html):
    """Extract sections from an HTML response."""
    soup = BeautifulSoup(html, "html.parser")
    sections = []

    select = soup.find("select", id=re.compile(r"section", re.I))
    if not select:
        select = soup.find("select", attrs={"name": re.compile(r"section", re.I)})

    if select:
        for option in select.find_all("option"):
            val = option.get("value", "").strip()
            text = option.get_text(strip=True)
            if val and text and val != "" and val != "0" and "select" not in text.lower():
                sections.append({"value": val, "label": text})
        return sections

    for link in soup.find_all("a", class_=re.compile(r"section", re.I)):
        val = link.get("data-value", "") or link.get("href", "")
        text = link.get_text(strip=True)
        if val and text:
            sections.append({"value": val, "label": text})

    return sections


def discover_ajax_endpoints(html):
    """Discover AJAX endpoints from the page's JavaScript."""
    endpoints = {}

    ajax_patterns = [
        (r'["\']([^"\']*?/timber/[^"\']*?(?:dept|department)[^"\']*?)["\']', "departments"),
        (r'["\']([^"\']*?/timber/[^"\']*?(?:course)[^"\']*?)["\']', "courses"),
        (r'["\']([^"\']*?/timber/[^"\']*?(?:section)[^"\']*?)["\']', "sections"),
        (r'["\']([^"\']*?/timber/[^"\']*?(?:material|book|adopt)[^"\']*?)["\']', "materials"),
        (r'["\']([^"\']*?/college/[^"\']*?(?:by-name|lookup|search)[^"\']*?)["\']', "lookup"),
    ]

    for pattern, name in ajax_patterns:
        matches = re.findall(pattern, html, re.I)
        if matches:
            endpoints[name] = matches
            print(f"    [DISCOVER] Found {name} endpoints: {matches[:3]}")

    drupal_ajax = re.findall(r'Drupal\.url\(["\']([^"\']+)["\']\)', html)
    if drupal_ajax:
        endpoints["drupal_ajax"] = drupal_ajax
        print(f"    [DISCOVER] Drupal AJAX URLs: {drupal_ajax[:5]}")

    ajax_urls = re.findall(r'(?:url|href|action|data-url)\s*[:=]\s*["\']([^"\']+(?:ajax|callback|timber|college)[^"\']*)["\']', html, re.I)
    if ajax_urls:
        endpoints["ajax_urls"] = ajax_urls
        print(f"    [DISCOVER] AJAX URLs: {ajax_urls[:5]}")

    return endpoints


def parse_materials_page(html, term_name, dept_code):
    """Parse textbook/materials information from a Timber page."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    book_containers = soup.find_all("div", class_=re.compile(
        r"book|material|product|adoption|textbook|item|course-material", re.I
    ))
    if not book_containers:
        book_containers = soup.find_all("tr", class_=re.compile(
            r"book|material|product|adoption", re.I
        ))
    if not book_containers:
        book_containers = soup.find_all("li", class_=re.compile(
            r"book|material|product|adoption", re.I
        ))

    for container in book_containers:
        isbn = ""
        title = ""
        author = ""
        course_code = ""
        course_title = ""
        section = ""
        instructor = ""
        adoption_code = ""

        isbn_el = container.find(string=re.compile(r"ISBN", re.I))
        if isbn_el:
            isbn_text = isbn_el.parent.get_text(strip=True) if isbn_el.parent else str(isbn_el)
            m = re.search(r"ISBN[:\s]*(\d[\d\-Xx]{8,})", isbn_text)
            if m:
                isbn = m.group(1).replace("-", "").strip()

        if not isbn:
            for el in container.find_all(class_=re.compile(r"isbn", re.I)):
                text = el.get_text(strip=True)
                m = re.search(r"(\d{10,13})", text.replace("-", ""))
                if m:
                    isbn = m.group(1)
                    break

        if not isbn:
            for el in container.find_all(["span", "p", "div", "td"]):
                text = el.get_text(strip=True).replace("-", "")
                if re.match(r"^\d{10}$|^\d{13}$", text):
                    isbn = text
                    break

        title_el = container.find(class_=re.compile(r"title|book-?name|product-?name", re.I))
        if title_el:
            title = title_el.get_text(strip=True)
        if not title:
            h_el = container.find(["h2", "h3", "h4", "strong"])
            if h_el:
                candidate = h_el.get_text(strip=True)
                if len(candidate) > 3 and "ISBN" not in candidate.upper():
                    title = candidate

        author_el = container.find(class_=re.compile(r"author", re.I))
        if author_el:
            author = author_el.get_text(strip=True)
            author = re.sub(r"^(?:Author|By)[:\s]*", "", author, flags=re.I).strip()
        if not author:
            auth_str = container.find(string=re.compile(r"(?:Author|By)[:\s]", re.I))
            if auth_str:
                text = auth_str.parent.get_text(strip=True) if auth_str.parent else str(auth_str)
                m = re.search(r"(?:Author|By)[:\s]*(.+?)(?:\||$)", text, re.I)
                if m:
                    author = m.group(1).strip()

        course_el = container.find(class_=re.compile(r"course", re.I))
        if course_el:
            course_code = course_el.get_text(strip=True)

        req_el = container.find(class_=re.compile(r"requirement|required|adoption|status", re.I))
        if req_el:
            adoption_code = req_el.get_text(strip=True)
        if not adoption_code:
            for badge_class in ["badge", "label", "tag", "status"]:
                badge = container.find(class_=re.compile(badge_class, re.I))
                if badge:
                    text = badge.get_text(strip=True).lower()
                    if any(kw in text for kw in ["required", "recommended", "optional", "choice"]):
                        adoption_code = badge.get_text(strip=True)
                        break

        section_el = container.find(class_=re.compile(r"section", re.I))
        if section_el:
            section = section_el.get_text(strip=True)
            section = re.sub(r"^Section[:\s]*", "", section, flags=re.I).strip()

        instructor_el = container.find(class_=re.compile(r"instructor|professor|faculty", re.I))
        if instructor_el:
            instructor = instructor_el.get_text(strip=True)
            instructor = re.sub(r"^(?:Instructor|Professor|Faculty)[:\s]*", "", instructor, flags=re.I).strip()

        if isbn or title or author:
            if course_code:
                parsed_dept, parsed_course = split_dept_course(course_code)
                if parsed_course:
                    course_code = parsed_course
                else:
                    course_code = format_course_code(course_code)
            results.append({
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": course_title,
                "section": format_section_code(section),
                "section_instructor": instructor,
                "term": term_name,
                "isbn": isbn,
                "title": title,
                "author": author,
                "material_adoption_code": adoption_code,
            })

    if not results:
        text = soup.get_text(" ", strip=True)
        if re.search(r"no\s+(?:textbook|material|book|adoption|course material)s?\s+(?:required|found|available|needed)", text, re.I):
            results.append({
                "department_code": dept_code,
                "course_code": "",
                "course_title": "",
                "section": "",
                "section_instructor": "",
                "term": term_name,
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": "No materials required",
            })

    return results


def parse_by_name_page(html, term_name, dept_code, course_label, section_label=""):
    """Parse the /college/by-name response which shows materials for a specific course."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        header_cells = []
        if rows:
            header_cells = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            cell_texts = [c.get_text(strip=True) for c in cells]

            isbn = ""
            title = ""
            author = ""
            adoption_code = ""

            for i, hdr in enumerate(header_cells):
                if i >= len(cell_texts):
                    break
                val = cell_texts[i]
                if "isbn" in hdr:
                    isbn = val.replace("-", "").strip()
                elif "title" in hdr or "name" in hdr:
                    title = val
                elif "author" in hdr:
                    author = val
                elif "require" in hdr or "status" in hdr or "adoption" in hdr:
                    adoption_code = val

            if not isbn and not title:
                for val in cell_texts:
                    clean = val.replace("-", "")
                    if re.match(r"^\d{10}$|^\d{13}$", clean):
                        isbn = clean
                        break

            if isbn or title:
                results.append({
                    "department_code": dept_code,
                    "course_code": format_course_code(course_label) if course_label else "",
                    "course_title": "",
                    "section": format_section_code(section_label),
                    "section_instructor": "",
                    "term": term_name,
                    "isbn": isbn,
                    "title": title,
                    "author": author,
                    "material_adoption_code": adoption_code,
                })

    if not results:
        results = parse_materials_page(html, term_name, dept_code)

    if not results:
        course_code = format_course_code(course_label) if course_label else ""
        text = soup.get_text(" ", strip=True)

        if re.search(r"no\s+(?:textbook|material|book|adoption)s?\s+(?:required|found|available|needed)", text, re.I):
            results.append({
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": "",
                "section": format_section_code(section_label),
                "section_instructor": "",
                "term": term_name,
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": "No materials required",
            })
        elif re.search(r"no\s+(?:results|records|data)", text, re.I):
            pass

    return results


def try_timber_ajax_endpoints(sess, term_value, term_label):
    """Try various known Timber/Drupal AJAX endpoint patterns to load departments."""
    patterns = [
        f"/timber/college?term={term_value}",
        f"/timber/college/departments?term={term_value}",
        f"/timber/college/ajax/departments?term={term_value}",
        f"/college/departments?term={term_value}",
        f"/timber/college/dept?term={term_value}",
    ]

    for url_path in patterns:
        try:
            url = BASE_URL + url_path
            raw = safe_get(sess, url)
            html = parse_drupal_ajax_html(raw)
            depts = parse_departments_from_html(html)
            if depts:
                print(f"    [*] Found departments via GET {url_path}")
                return depts, html
        except Exception as e:
            if "Cloudflare" in str(e):
                raise
            continue

    # Drupal Views AJAX: POST to the page URL with form fields
    post_patterns = [
        (TIMBER_URL, {"term": term_value, "ajax_page_state[theme]": "timber", "_triggering_element_name": "term"}),
        (TIMBER_URL, {"field_term": term_value, "_triggering_element_name": "field_term"}),
        (TIMBER_URL, {"edit-term": term_value}),
    ]
    for post_url, post_data in post_patterns:
        try:
            sess.headers.update({"X-Requested-With": "XMLHttpRequest",
                                  "Accept": "application/json, text/html, */*"})
            raw = safe_post(sess, post_url, data=post_data)
            html = parse_drupal_ajax_html(raw)
            depts = parse_departments_from_html(html)
            if depts:
                print(f"    [*] Found departments via POST to {post_url}")
                return depts, html
        except Exception as e:
            if "Cloudflare" in str(e):
                raise
            continue

    return [], ""


def try_course_endpoints(sess, term_value, dept_value):
    """Try various endpoint patterns to load courses for a department."""
    patterns = [
        f"/timber/college?term={term_value}&dept={dept_value}",
        f"/timber/college/courses?term={term_value}&dept={dept_value}",
        f"/timber/college/ajax/courses?term={term_value}&dept={dept_value}",
        f"/college/courses?term={term_value}&dept={dept_value}",
    ]

    for url_path in patterns:
        try:
            url = BASE_URL + url_path
            raw = safe_get(sess, url)
            html = parse_drupal_ajax_html(raw)
            courses = parse_courses_from_html(html)
            if courses:
                return courses, html
        except Exception as e:
            if "Cloudflare" in str(e):
                raise
            continue

    return [], ""


def try_section_endpoints(sess, term_value, dept_value, course_value):
    """Try various endpoint patterns to load sections for a course."""
    patterns = [
        f"/timber/college?term={term_value}&dept={dept_value}&course={course_value}",
        f"/timber/college/sections?term={term_value}&dept={dept_value}&course={course_value}",
        f"/college/sections?term={term_value}&dept={dept_value}&course={course_value}",
    ]

    for url_path in patterns:
        try:
            url = BASE_URL + url_path
            raw = safe_get(sess, url)
            html = parse_drupal_ajax_html(raw)
            sections = parse_sections_from_html(html)
            if sections:
                return sections, html
        except Exception as e:
            if "Cloudflare" in str(e):
                raise
            continue

    return [], ""


def try_materials_endpoints(sess, term_value, dept_value, course_value,
                            section_value="", term_label="", dept_label="",
                            course_label="", section_label=""):
    """Try various endpoint patterns to get materials/textbooks."""
    patterns = [
        f"/college/by-name?term={term_value}&dept={dept_value}&course={course_value}&section={section_value}",
        f"/college/by-name?term={term_label}&dept={dept_label}&course={course_label}&section={section_label}",
        f"/timber/college?term={term_value}&dept={dept_value}&course={course_value}&section={section_value}",
        f"/timber/college/materials?term={term_value}&dept={dept_value}&course={course_value}&section={section_value}",
        f"/timber/college/books?term={term_value}&dept={dept_value}&course={course_value}",
    ]

    for url_path in patterns:
        try:
            url = BASE_URL + url_path
            raw = safe_get(sess, url)
            html = parse_drupal_ajax_html(raw)
            if len(html) > 500:
                return html, url_path
        except Exception as e:
            if "Cloudflare" in str(e):
                raise
            continue

    return "", ""


def append_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def get_scraped_departments(filepath):
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


def dump_debug(html, label):
    """Save HTML to debug file for analysis."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"debug_{label}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"    [DEBUG] HTML saved to {path} ({len(html)} chars)")
    return path


def discover_page_structure(html):
    """Analyze the main page to understand Timber's structure."""
    soup = BeautifulSoup(html, "html.parser")

    print("\n[*] === PAGE STRUCTURE ANALYSIS ===")
    print(f"    Title: {soup.title.get_text(strip=True) if soup.title else 'N/A'}")

    forms = soup.find_all("form")
    print(f"    Forms found: {len(forms)}")
    for i, form in enumerate(forms):
        action = form.get("action", "N/A")
        method = form.get("method", "GET")
        form_id = form.get("id", "N/A")
        print(f"      Form {i}: id={form_id}, method={method}, action={action}")

    selects = soup.find_all("select")
    print(f"    Select elements: {len(selects)}")
    for s in selects:
        s_id = s.get("id", "N/A")
        s_name = s.get("name", "N/A")
        options = s.find_all("option")
        print(f"      Select: id={s_id}, name={s_name}, options={len(options)}")
        for opt in options[:10]:
            print(f"        - value={opt.get('value', '')!r} text={opt.get_text(strip=True)!r}")

    scripts = soup.find_all("script", src=True)
    print(f"    External scripts: {len(scripts)}")
    for s in scripts:
        src = s.get("src", "")
        if "timber" in src.lower() or "college" in src.lower() or "book" in src.lower():
            print(f"      [RELEVANT] {src}")

    endpoints = discover_ajax_endpoints(html)

    links = soup.find_all("a", href=re.compile(r"timber|college|book|textbook|course", re.I))
    print(f"    Relevant links: {len(links)}")
    for link in links[:20]:
        print(f"      - {link.get('href', '')} -> {link.get_text(strip=True)[:60]}")

    divs_with_id = soup.find_all(id=re.compile(r"term|dept|course|section|book|material|timber", re.I))
    print(f"    Relevant div IDs: {len(divs_with_id)}")
    for d in divs_with_id:
        print(f"      - <{d.name} id={d.get('id', '')} class={d.get('class', '')}>")

    print("[*] === END ANALYSIS ===\n")
    return endpoints


def scrape(fresh=False, discover_only=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d 00:00:00")
    source_url = TIMBER_URL

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_depts = get_scraped_departments(CSV_PATH)
    if done_depts:
        print(f"[*] {len(done_depts)} departments already scraped: {sorted(done_depts)}")

    sess, initial_html = create_session()
    dump_debug(initial_html, "initial_page")

    if discover_only:
        discover_page_structure(initial_html)
        print("\n[*] Discovery mode — stopping here. Check debug files for page structure.")
        flaresolverr_destroy_session()
        return

    # Parse terms using TCC link format: <a class='tcc-item-link' url='/college_term/131166'>
    terms = parse_tcc_links(initial_html)
    print(f"[*] Found {len(terms)} terms: {[clean_term(t['code']) for t in terms]}")

    if not terms:
        print("[!] No TCC term links found. Check debug_initial_page.html.")
        flaresolverr_destroy_session()
        return

    total_rows = 0

    for term in terms:
        term_path = term["value"]          # e.g. /college_term/131166
        term_label = clean_term(term["code"])  # e.g. SPRING 2026
        print(f"\n[*] Processing term: {term_label} (path={term_path})")

        # Selecting the term sets server-side session state and returns departments
        try:
            depts_html = timber_ajax_get(sess, term_path)
        except RuntimeError as e:
            if "Cloudflare" in str(e):
                print(f"    [WARN] CF block on term select, refreshing session...")
                sess, _ = refresh_session(sess)
                depts_html = timber_ajax_get(sess, term_path)
            else:
                print(f"    [ERROR] term {term_label}: {e}")
                continue

        depts = parse_tcc_links(depts_html)
        print(f"    Found {len(depts)} departments")

        if not depts:
            print(f"    [!] No departments for {term_label}. Skipping.")
            continue

        for dept in tqdm(depts, desc=f"  Depts ({term_label})"):
            dept_code = dept["code"]   # e.g. ACC
            dept_path = dept["value"]  # e.g. /college_dept/131073

            if dept_code in done_depts:
                continue

            # Select dept — server keeps term context, returns courses
            try:
                courses_html = timber_ajax_get(sess, dept_path)
            except RuntimeError as e:
                if "Cloudflare" in str(e):
                    tqdm.write(f"\n  [WARN] CF block on dept {dept_code}, refreshing session...")
                    sess, _ = refresh_session(sess)
                    # Re-select term after session refresh to restore server state
                    timber_ajax_get(sess, term_path)
                    courses_html = timber_ajax_get(sess, dept_path)
                else:
                    tqdm.write(f"\n  [ERROR] dept {dept_code}: {e}")
                    continue

            courses = parse_tcc_links(courses_html)

            if not courses:
                append_csv([{
                    "source_url": source_url, "school_id": SCHOOL_ID,
                    "department_code": dept_code, "course_code": "",
                    "course_title": "", "section": "", "section_instructor": "",
                    "term": term_label, "isbn": "", "title": "", "author": "",
                    "material_adoption_code": "No courses found",
                    "crawled_on": crawled_on, "updated_on": crawled_on,
                }], CSV_PATH)
                total_rows += 1
                continue

            dept_rows = 0
            for course in courses:
                course_path = course["value"]
                # Skip aggregate "All" course entries — they don't carry meaningful course codes
                if course["code"].strip().lower() == "all":
                    course_num, course_title = "", ""
                else:
                    course_num, course_title = split_course_label(course["code"])

                # Select course — returns sections
                try:
                    sections_html = timber_ajax_get(sess, course_path)
                except Exception as e:
                    tqdm.write(f"\n  [ERROR] {dept_code} {course_num}: {e}")
                    continue

                sections = parse_tcc_links(sections_html)

                # Use specific sections (53008, 53009, …) when available; fall back to "All"
                non_all = [s for s in sections if s["code"].strip().lower() != "all"]
                target_sections = non_all if non_all else sections

                if not target_sections:
                    # No section level — parse materials from course-level HTML directly
                    materials = parse_timber_materials(
                        sess, sections_html, term_label, dept_code,
                        course_num, course_title, ""
                    )
                    for row in materials:
                        row["source_url"] = source_url
                        row["school_id"] = SCHOOL_ID
                        row["crawled_on"] = crawled_on
                        row["updated_on"] = crawled_on
                    if materials:
                        append_csv(materials, CSV_PATH)
                        dept_rows += len(materials)
                        total_rows += len(materials)
                    continue

                for sec in target_sections:
                    sec_path = sec["value"]
                    # "All" aggregated section → store empty section code in CSV
                    sec_code = "" if sec["code"].strip().lower() == "all" else sec["code"].strip()

                    # Select section — returns materials
                    try:
                        mat_html = timber_ajax_get(sess, sec_path)
                    except Exception as e:
                        tqdm.write(f"\n  [ERROR] {dept_code} {course_num} {sec_code}: {e}")
                        continue

                    materials = parse_timber_materials(
                        sess, mat_html, term_label, dept_code,
                        course_num, course_title, sec_code
                    )
                    for row in materials:
                        row["source_url"] = source_url
                        row["school_id"] = SCHOOL_ID
                        row["crawled_on"] = crawled_on
                        row["updated_on"] = crawled_on
                    if materials:
                        append_csv(materials, CSV_PATH)
                        dept_rows += len(materials)
                        total_rows += len(materials)

            tqdm.write(f"    [{dept_code}] +{dept_rows} rows (total: {total_rows})")

    flaresolverr_destroy_session()

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"Total rows written: {total_rows}")
    print(f"CSV: {CSV_PATH}")

    final_depts = get_scraped_departments(CSV_PATH)
    missing = {d["code"] for d in depts} - final_depts if 'depts' in dir() else set()
    if missing:
        print(f"\n[!] MISSING {len(missing)} departments: {sorted(missing)}")
        print("  Re-run without --fresh to scrape only these.")
    else:
        print(f"\n[OK] All departments scraped successfully!")


if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    discover = "--discover" in sys.argv
    scrape(fresh=fresh, discover_only=discover)
