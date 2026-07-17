import csv
import re
import sys
from datetime import datetime
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from course_catalog_scrapy.pipelines import format_dept_code
from course_catalog_scrapy.items import year_from_url

PDF_URL = "https://www.palomar.edu/catalog/wp-content/uploads/sites/8/2026/05/2026-2027-Catalog-Volume-LXXV-Reduced.pdf"
PDF_PATH = "/tmp/palomar.pdf"
SCHOOL_ID = "2995726"
SLUG = "palomar_college__2995726__cc"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
FIELDNAMES = ["school_id", "department_code", "course_code", "course_title",
              "graduate_type", "term", "academic_year", "source_url",
              "backup_filename", "crawled_on", "updated_on"]

# Course-descriptions section: "DEPT NUM Title (units)" with parenthesized units.
HEADER_RE = re.compile(r'^([A-Z]{2,4})\s(\d{2,3}[A-Z]?)\s+(.+?)\s+\((\d+(?:\.\d+)?)\)\s*$', re.M)
# Program-requirement tables list courses with BARE units and titles that wrap to
# the next line, e.g. "ACR 101 Air Conditioning, Heating, and 3.0" / "Refrigeration".
# Many trade/dance/kinesiology courses appear ONLY here, not in the descriptions.
TABLE_RE = re.compile(r'^([A-Z]{2,4})\s(\d{2,3}[A-Z]?)\s+([A-Z].+?)\s+(\d{1,2}(?:\.\d)?)\s*$')
# a continuation line is a bare title fragment: not another course code, not a
# table/section marker, not a units/total row.
NOT_CONT = re.compile(r'^(?:[A-Z]{2,4}\s\d|Total|Units|Program|Learning|Note|Prereq|'
                      r'Advisory|Recommended|Course|Semester|Select|Choose|Fall|Spring|'
                      r'Summer|Or |OR |and one|\d)', re.I)


def _continuation(line):
    line = line.strip()
    if not line or len(line) > 60 or NOT_CONT.match(line):
        return ""
    if not re.search(r'[A-Za-z]', line) or re.search(r'\d\.\d\s*$', line):
        return ""
    return line


def main():
    out_dir = DATA_DIR / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, seen, year = [], set(), year_from_url(PDF_URL)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def emit(dept, num, title):
        code = f"{dept} {num}"
        if code in seen:
            return
        seen.add(code)
        fdept, fcode = format_dept_code(dept, code)
        rows.append({
            "school_id": SCHOOL_ID, "department_code": fdept,
            "course_code": fcode, "course_title": title.strip(),
            "graduate_type": "Undergraduate", "term": "",
            "academic_year": year, "source_url": PDF_URL,
            "backup_filename": "", "crawled_on": now, "updated_on": now,
        })

    with pdfplumber.open(PDF_PATH) as pdf:
        columns = []
        for pg in pdf.pages:
            w = pg.width
            for x0, x1 in ((0, w / 2), (w / 2, w)):
                columns.append(pg.crop((x0, 0, x1, pg.height)).extract_text() or "")
        # Pass 1: descriptions (parenthesized units) — complete, authoritative titles.
        for text in columns:
            for dept, num, title, units in HEADER_RE.findall(text):
                emit(dept, num, title)
        # Pass 2: program-requirement tables (bare units) — capture courses that
        # only appear here, joining the wrapped continuation line for the title.
        for text in columns:
            lines = text.split("\n")
            for i, ln in enumerate(lines):
                m = TABLE_RE.match(ln.strip())
                if not m:
                    continue
                units = float(m.group(4))
                if units < 0.5 or units > 20:
                    continue
                title = m.group(3).strip().rstrip(",")
                cont = _continuation(lines[i + 1]) if i + 1 < len(lines) else ""
                if cont:
                    title = f"{title} {cont}"
                emit(m.group(1), m.group(2), title)
    path = out_dir / f"{SLUG}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDNAMES)
        wr.writeheader()
        wr.writerows(rows)
    print(f"wrote {len(rows)} rows to {path} | year={year}")

if __name__ == "__main__":
    main()
