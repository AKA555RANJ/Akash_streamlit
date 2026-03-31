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
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

SCHOOL_NAME = "stark_state_college"
SCHOOL_ID = "3073939"
BASE_URL = "https://shop.starkstate.edu"
TIMBER_URL = BASE_URL + "/timber/college"
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


def safe_get(sess, url, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, timeout=60)
            resp.raise_for_status()
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
            if not course_code:
                course_code = dept_code
            results.append({
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": course_title,
                "section": section,
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
                "course_code": dept_code,
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
                    "course_code": f"{dept_code} {course_label}".strip() if course_label else dept_code,
                    "course_title": "",
                    "section": section_label,
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
        course_code = f"{dept_code} {course_label}".strip() if course_label else dept_code
        text = soup.get_text(" ", strip=True)

        if re.search(r"no\s+(?:textbook|material|book|adoption)s?\s+(?:required|found|available|needed)", text, re.I):
            results.append({
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": "",
                "section": section_label,
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
            html = safe_get(sess, url)
            depts = parse_departments_from_html(html)
            if depts:
                print(f"    [*] Found departments via {url_path}")
                return depts, html
        except Exception:
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
            html = safe_get(sess, url)
            courses = parse_courses_from_html(html)
            if courses:
                return courses, html
        except Exception:
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
            html = safe_get(sess, url)
            sections = parse_sections_from_html(html)
            if sections:
                return sections, html
        except Exception:
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
            html = safe_get(sess, url)
            if len(html) > 500:
                return html, url_path
        except Exception:
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
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_url = TIMBER_URL

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run - deleted existing CSV.")

    done_depts = get_scraped_departments(CSV_PATH)
    if done_depts:
        print(f"[*] {len(done_depts)} departments already scraped: {sorted(done_depts)}")

    sess, initial_html = create_session()

    dump_debug(initial_html, "initial_page")

    endpoints = discover_page_structure(initial_html)

    terms = parse_terms_from_page(initial_html)
    print(f"[*] Found {len(terms)} terms: {[t['label'] for t in terms]}")

    if discover_only:
        print("\n[*] Discovery mode - stopping here. Check debug files for page structure.")
        flaresolverr_destroy_session()
        return

    if not terms:
        print("[!] No terms found on page. The Timber page structure may need manual analysis.")
        print("[!] Check the debug HTML file for the actual page structure.")
        flaresolverr_destroy_session()
        return

    total_rows = 0

    for term in terms:
        term_value = term["value"]
        term_label = term["label"]
        print(f"\n[*] Processing term: {term_label} (value={term_value})")

        depts, dept_html = try_timber_ajax_endpoints(sess, term_value, term_label)

        if not depts and dept_html:
            depts = parse_departments_from_html(dept_html)

        if not depts:
            print(f"    [!] No departments found for {term_label}. Trying direct page fetch...")
            try:
                url = f"{TIMBER_URL}?term={term_value}"
                dept_html = safe_get(sess, url)
                dump_debug(dept_html, f"term_{term_value}")
                depts = parse_departments_from_html(dept_html)
            except Exception as e:
                print(f"    [!] Failed: {e}")

        if not depts:
            print(f"    [!] Still no departments for {term_label}. Skipping.")
            continue

        print(f"    Found {len(depts)} departments")

        for dept in tqdm(depts, desc=f"  Depts ({term_label})"):
            dept_value = dept["value"]
            dept_label = dept["label"]

            if dept_label in done_depts:
                continue

            courses, course_html = try_course_endpoints(sess, term_value, dept_value)

            if not courses:
                mat_html, used_path = try_materials_endpoints(
                    sess, term_value, dept_value, "", "",
                    term_label, dept_label, "", ""
                )
                if mat_html:
                    materials = parse_by_name_page(mat_html, term_label, dept_label, "")
                    if not materials:
                        materials = parse_materials_page(mat_html, term_label, dept_label)

                    for row in materials:
                        row["source_url"] = source_url
                        row["school_id"] = SCHOOL_ID
                        row["crawled_on"] = crawled_on

                    if materials:
                        append_csv(materials, CSV_PATH)
                        total_rows += len(materials)
                continue

            for course in courses:
                course_value = course["value"]
                course_label = course["label"]

                sections, section_html = try_section_endpoints(
                    sess, term_value, dept_value, course_value
                )

                if sections:
                    for sec in sections:
                        sec_value = sec["value"]
                        sec_label = sec["label"]

                        mat_html, used_path = try_materials_endpoints(
                            sess, term_value, dept_value, course_value, sec_value,
                            term_label, dept_label, course_label, sec_label
                        )
                        if mat_html:
                            materials = parse_by_name_page(
                                mat_html, term_label, dept_label,
                                course_label, sec_label
                            )
                            for row in materials:
                                row["source_url"] = source_url
                                row["school_id"] = SCHOOL_ID
                                row["crawled_on"] = crawled_on

                            if materials:
                                append_csv(materials, CSV_PATH)
                                total_rows += len(materials)
                else:
                    mat_html, used_path = try_materials_endpoints(
                        sess, term_value, dept_value, course_value, "",
                        term_label, dept_label, course_label, ""
                    )
                    if mat_html:
                        materials = parse_by_name_page(
                            mat_html, term_label, dept_label, course_label
                        )
                        for row in materials:
                            row["source_url"] = source_url
                            row["school_id"] = SCHOOL_ID
                            row["crawled_on"] = crawled_on

                        if materials:
                            append_csv(materials, CSV_PATH)
                            total_rows += len(materials)

    flaresolverr_destroy_session()

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"Total rows written: {total_rows}")
    print(f"CSV: {CSV_PATH}")


if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    discover = "--discover" in sys.argv
    scrape(fresh=fresh, discover_only=discover)
