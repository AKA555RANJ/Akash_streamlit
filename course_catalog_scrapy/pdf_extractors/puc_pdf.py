import csv
import re
import sys
from datetime import datetime
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from course_catalog_scrapy.pipelines import format_dept_code
from course_catalog_scrapy.text_utils import clean_course_title

PDF_URL = "https://www.puc.edu/_media/pdf/academics/catalog/current/catalog/Catalog-2025-2027.pdf"
PDF_PATH = "/tmp/puc.pdf"
SCHOOL_ID = "2995723"
SLUG = "pacific_union_college__2995723__cc"
ACADEMIC_YEAR = "2025-2027"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
FIELDNAMES = ["school_id", "department_code", "course_code", "course_title",
              "graduate_type", "term", "academic_year", "source_url",
              "backup_filename", "crawled_on", "updated_on"]

# The catalog mixes two layouts: compact program tables ("CODE Title N CODE
# Title N" across columns) and a descriptions section ("CODE Title N" at line
# start). Parsing must be PER LINE — joining the full text glues description
# lines onto course lines and breaks the credit boundary.
TC = r"[A-Za-z0-9 ,&/:'.()+*\-]"
CR = r"\.?\d+(?:[-–+.]\d+)*"
COMPACT = re.compile(
    rf"([A-Z]{{1,5}})\s?(\d{{2,4}}[A-Z]?)\s+([A-Z][A-Za-z]{TC}{{2,48}}?)"
    rf"\s*\(?({CR})\)?\*{{0,2}}(?=\s+[A-Z]{{1,5}}\s?\d|\s*$)")
DESC = re.compile(
    rf"^([A-Z]{{1,5}})\s?(\d{{2,4}}[A-Z]?)\s+([A-Z][A-Za-z]{TC}{{3,50}}?)"
    rf"\s*\(?({CR})\)?\*{{0,2}}(\s|$)")
# Wrapped titles: "SOWK 275 History and Philosophy of Social Welfare" with the
# tail + credit on a following line ("Institutions 3 ..."). The head line has
# NO digits after the code; the continuation is a short Title-Case fragment
# ending in a credit (other-column text may trail it).
HEAD = re.compile(
    r"^([A-Z]{2,5})\s?(\d{2,4}[A-Z]?)\s+([A-Z][A-Za-z][A-Za-z ,&':\-]{2,60})"
    "\\s*(?:[\uf000-\uf8ff].*)?$")
CONT = re.compile(rf"^([A-Z][A-Za-z ,&':\-]{{1,44}}?)\s+({CR})\b")
# Bare no-credit reference line, e.g. "GNRL 100 Campus Community." — short
# Title-Case phrase ending with a period.
BARE = re.compile(r"^([A-Z]{2,5})\s?(\d{2,4}[A-Z]?)\s+"
                  r"([A-Z][a-z]+(?: [A-Z][a-z]+){0,3})\.$")
CALENDAR = re.compile(r"^M\s?\d{1,2}\s+[A-Z]")
ROMAN_GLUE = re.compile(r"^(.*?\b[IVX]{1,4})(\.?\d.*)$")
PRIVATE_GLYPHS = re.compile("[\uf000-\uf8ff]")


def cl(t):
    t = PRIVATE_GLYPHS.sub(" ", t)
    t = re.sub(r"[*]+", "", t)
    m = ROMAN_GLUE.match(t)
    if m:
        t = m.group(1)
    return clean_course_title(t.strip(" +*,-"))


def main():
    out_dir = DATA_DIR / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with pdfplumber.open(PDF_PATH) as pdf:
        lines = []
        for pg in pdf.pages:
            lines += (pg.extract_text() or "").split("\n")
    lines = [ln.strip() for ln in lines]

    seen = {}

    def add(dept, num, title):
        code = f"{dept} {num}"
        # a course code inside the title means we grabbed cross-reference
        # prose (e.g. "...College English requirement. HNRS 111, 121, and")
        if (code not in seen and len(title) >= 3 and re.search(r"[a-z]", title)
                and not re.search(r"\b[A-Z]{2,5}\s?\d{2,4}\b", title)):
            seen[code] = title

    for s in lines:
        # academic-calendar rows ("M 19 Martin Luther King Day ...") mimic codes
        if CALENDAR.match(s) and re.search(r"\bDay\b|class", s, re.I):
            continue
        for m in COMPACT.finditer(s):
            add(m.group(1), m.group(2), cl(m.group(3)))
        m = DESC.match(s)
        if m:
            add(m.group(1), m.group(2), cl(m.group(3)))
    # second pass: wrapped titles (only codes still unseen can be added)
    for i, s in enumerate(lines):
        m = HEAD.match(s)
        if m and f"{m.group(1)} {m.group(2)}" not in seen:
            for nxt in lines[i + 1:i + 3]:
                c = CONT.match(nxt)
                if c:
                    add(m.group(1), m.group(2),
                        cl(f"{m.group(3).strip()} {c.group(1).strip()}"))
                    break
        b = BARE.match(s)
        if b:
            add(b.group(1), b.group(2), cl(b.group(3)))

    path = out_dir / f"{SLUG}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDNAMES)
        wr.writeheader()
        for code in sorted(seen):
            dept, num = code.split(" ", 1)
            fdept, fcode = format_dept_code(dept, code)
            wr.writerow({
                "school_id": SCHOOL_ID, "department_code": fdept,
                "course_code": fcode, "course_title": seen[code],
                "graduate_type": "", "term": "",
                "academic_year": ACADEMIC_YEAR, "source_url": PDF_URL,
                "backup_filename": "", "crawled_on": now, "updated_on": now,
            })
    print(f"wrote {len(seen)} rows to {path}")


if __name__ == "__main__":
    main()
