#!/usr/bin/env python3

import csv
import re
import fitz

DATA_DIR = "data/galen_college_of_nursing_louisville__3033039__bks"
SOURCE_URL = "https://galen.libguides.com/Booklist"
SCHOOL_ID = "3033039"
CRAWLED_ON = "2026-03-21 00:00:00"

PDFS = [
    ("PN_Booklist_Summer_2026.pdf", "PN", "Summer 2026"),
    ("ADN_Booklist_Summer_2026.pdf", "ADN", "Summer 2026"),
    ("BSN_Pre_Licensure_Booklist_Summer_2026.pdf", "BSN", "Summer 2026"),
    ("RN_BSN_Post_Licensure_Booklist_Spring_Session_II_2026.pdf", "RN-BSN", "Spring Session II 2026"),
    ("MSN_Post_Licensure_Booklist_Spring_Session_II_2026.pdf", "MSN", "Spring Session II 2026"),
    ("DNP_Post_Licensure_Booklist_Spring_Session_II_2026.pdf", "DNP", "Spring Session II 2026"),
]

ISBN_RE = re.compile(r'97[89]\d{10}')

COURSE_PREFIXES = (
    'AID|BIO|BSL|CLS|COM|ENG|GPS|HUM|LDR|MAT|'
    'NSG|NU|NUR|PHL|PHM|PNS|PSY|SOC|STA|DNP'
)

COURSE_RE = re.compile(
    rf'^(?:{COURSE_PREFIXES})\s+(\d{{3,4}}[A-Z]?(?:/\d{{3,4}}[A-Z]?)?)\s*:?\s+(.+?)(?:\s*\(.*\))?\s*$',
    re.MULTILINE
)

def extract_text(pdf_path):
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text() + "\n"
    return text

NEW_ENTRY_RE = re.compile(
    r'^[⌨†\s]*'
    r'[*]?'
    r'[A-Z][A-Za-z\'\-]+'
    r'.*'
    r'\((?:\d{4}|n\.d\.)\)'
)

PUBLISHERS_RE = re.compile(
    r'\.\s*(?:Elsevier|F\.\s*A\.\s*Davis|Wolters Kluwer|Jones\s*&?\s*Bartlett|'
    r'Lippincott|Pearson|Springer Publishing|Springer|McGraw|Cengage|Sage|Oxford|'
    r'Cambridge|American Psychological|Wiley|Mosby|Saunders|Health Administration Press|'
    r'Virginia Tech|Sigma|Theta Tau|VitalSource|National Academies|National League|'
    r'Jossey|W\.\s*W\.\s*Norton|Open\s*Stax|OpenStax|American Nurses Association|'
    r'Jones and Bartlett|Rowman|AACN|Brookes Publishing|American Association)'
)

def is_new_entry_start(line):
    stripped = line.strip()
    if not stripped:
        return False
    if stripped[0] in '⌨†' and len(stripped) > 1:
        return True
    if NEW_ENTRY_RE.match(stripped):
        return True
    return False

def current_entry_has_year(lines_so_far):
    text = ' '.join(lines_so_far)
    return bool(re.search(r'\((?:\d{4}|n\.d\.)\)', text))

def group_entry_lines(lines):
    entries = []
    current = []
    for line in lines:
        stripped = line.strip()
        if current:
            if stripped and stripped[0] in '⌨†':
                entries.append(' '.join(current))
                current = [line]
            elif is_new_entry_start(line) and current_entry_has_year(current):
                entries.append(' '.join(current))
                current = [line]
            else:
                current.append(line)
        else:
            current.append(line)
    if current:
        entries.append(' '.join(current))
    return entries

def parse_single_entry(entry_text):
    clean = re.sub(r'[⌨†]', '', entry_text).strip()
    clean = clean.lstrip('* ')
    clean = re.sub(r'https?://\S+', '', clean).strip()
    clean = re.sub(r'\[https?://[^\]]*\]', '', clean).strip()

    isbn_match = ISBN_RE.search(clean)
    isbn = isbn_match.group(0) if isbn_match else ""

    if not isbn:
        if clean.lower().startswith('recommend use of'):
            return None
        if 'Please' in clean or 'discount' in clean.lower():
            return None

    yr_match = re.search(r'\.\s*,?\s*\((?:\d{4}|n\.d\.)\)\.?\s*', clean)
    if yr_match:
        author = clean[:yr_match.start()].strip()
        rest_after_year = clean[yr_match.end():].strip()

        if isbn:
            before_isbn = rest_after_year[:rest_after_year.find(isbn)].strip().rstrip('.')
        else:
            before_isbn = rest_after_year.strip().rstrip('.')

        pub_match = PUBLISHERS_RE.search(before_isbn)
        if pub_match:
            title = before_isbn[:pub_match.start()].strip().rstrip('.')
        else:
            title = before_isbn.strip().rstrip('.')
    elif isbn:
        before_isbn = clean[:clean.find(isbn)].strip().rstrip('.')
        author = ""
        title = before_isbn
    else:
        author = ""
        title = clean.rstrip('.')
        url_match = re.search(r'https?://\S+', clean)
        if url_match:
            before_url = clean[:url_match.start()].strip().rstrip('.')
            yr_match2 = re.search(r'\.\s*,?\s*\((?:\d{4}|n\.d\.)\)\.?\s*', before_url)
            if yr_match2:
                author = before_url[:yr_match2.start()].strip()
                title = before_url[yr_match2.end():].strip().rstrip('.')
                pub_match = PUBLISHERS_RE.search(title)
                if pub_match:
                    title = title[:pub_match.start()].strip().rstrip('.')
            else:
                title = before_url

    title = re.sub(r'\s*\(\d+\w*\s+ed\..*?\)\s*$', '', title).strip()
    title = title.rstrip('.')
    title = title.rstrip('*').rstrip()

    if not title:
        return None

    return {
        'isbn': isbn,
        'title': title,
        'author': author,
    }

def parse_books_from_section(lines):
    entries = group_entry_lines(lines)
    books = []
    for entry_text in entries:
        result = parse_single_entry(entry_text)
        if result:
            books.append(result)
    return books

def parse_pdf(pdf_path, department, term):
    text = extract_text(f"{DATA_DIR}/{pdf_path}")
    rows = []

    lines = text.split('\n')

    current_course_code = ""
    current_course_title = ""
    current_section_type = ""
    section_lines = []

    def flush_section():
        nonlocal section_lines
        if not section_lines or not current_course_code:
            section_lines = []
            return

        section_text = ' '.join(section_lines).lower()
        if 'no required textbook' in section_text or 'no required resource' in section_text:
            rows.append({
                'source_url': SOURCE_URL,
                'school_id': SCHOOL_ID,
                'department_code': department,
                'course_code': f"|{current_course_code}",
                'course_title': current_course_title,
                'section': '',
                'section_instructor': '',
                'term': term,
                'isbn': '',
                'title': '',
                'author': '',
                'material_adoption_code': 'This course does not require any course materials',
                'crawled_on': CRAWLED_ON,
                'updated_on': CRAWLED_ON,
            })
            section_lines = []
            return

        books = parse_books_from_section(section_lines)
        adoption_code = "Required" if current_section_type == "Required" else "Recommended"

        for book in books:
            rows.append({
                'source_url': SOURCE_URL,
                'school_id': SCHOOL_ID,
                'department_code': department,
                'course_code': f"|{current_course_code}",
                'course_title': current_course_title,
                'section': '',
                'section_instructor': '',
                'term': term,
                'isbn': book['isbn'],
                'title': book['title'],
                'author': book['author'],
                'material_adoption_code': adoption_code,
                'crawled_on': CRAWLED_ON,
                'updated_on': CRAWLED_ON,
            })

        section_lines = []

    for line in lines:
        line_stripped = line.strip()

        if line_stripped.startswith('Prepared by:') or line_stripped.startswith('Page:') or line_stripped.startswith('Revised'):
            continue
        if 'BOOKLIST for' in line_stripped:
            continue
        if line_stripped.startswith('The following outlines') or line_stripped.startswith('Use International'):
            continue

        course_match = COURSE_RE.match(line_stripped)
        if course_match:
            flush_section()
            current_course_code = course_match.group(1)
            current_course_title = course_match.group(2).strip()
            current_section_type = ""
            continue

        if current_course_code and not current_section_type:
            lower = line_stripped.lower()
            if ('no required' in lower and ('textbook' in lower or 'resource' in lower)):
                rows.append({
                    'source_url': SOURCE_URL,
                    'school_id': SCHOOL_ID,
                    'department_code': department,
                    'course_code': f"|{current_course_code}",
                    'course_title': current_course_title,
                    'section': '',
                    'section_instructor': '',
                    'term': term,
                    'isbn': '',
                    'title': '',
                    'author': '',
                    'material_adoption_code': 'This course does not require any course materials',
                    'crawled_on': CRAWLED_ON,
                    'updated_on': CRAWLED_ON,
                })
                current_course_code = ""
                continue

        if line_stripped == 'Required:' or line_stripped.startswith('Required:'):
            flush_section()
            current_section_type = "Required"
            continue
        if line_stripped == 'Recommended:' or line_stripped.startswith('Recommended:'):
            flush_section()
            current_section_type = "Recommended"
            continue

        if current_section_type and current_course_code:
            has_isbn = bool(ISBN_RE.search(line_stripped))
            if not has_isbn and any(skip in line_stripped for skip in [
                'Please watch this video',
                'Please review the Elsevier',
                '*Please review',
                'either format using one of the Discount',
                'Please confer with course',
                'When renting a textbook',
                'Textbooks/resources may be',
                'Some required textbooks',
                'The following publishers',
                'Elsevier (', 'F. A. Davis (', 'Jones & Bartlett (', 'Wolters Kluwer (',
                'www.fadavis.com', 'www.jblearning.com',
                'book had those features', 'renting. Galen is not',
                'Do not complete the transaction',
                'solutions adopted by Galen',
                'Students can access',
                'necessary for academic',
                'not always necessary',
                'clinical. Please confer',
                '*Note:', 'Note:',
                'Discount Ordering',
                'ordering information',
                'discount information',
                'Textbook ordering',
                'click on the link',
                'Print version',
                'eBook version',
                'discount code',
            ]):
                continue
            if line_stripped.startswith('•') or line_stripped.startswith('o '):
                continue
            if not has_isbn and re.match(r'^(https?://|\[https?://|GalenCollegeofNursing)', line_stripped):
                continue
            if re.match(r'^\d{1,4}$', line_stripped) and not ISBN_RE.match(line_stripped):
                continue
            if re.match(r'^\d+/\d+/\d+$', line_stripped):
                continue
            if line_stripped:
                section_lines.append(line_stripped)

    flush_section()
    return rows

def main():
    all_rows = []
    for pdf_file, dept, term in PDFS:
        print(f"Parsing {pdf_file}...")
        rows = parse_pdf(pdf_file, dept, term)
        print(f"  Found {len(rows)} entries")
        all_rows.append((pdf_file, dept, term, rows))

    csv_path = f"{DATA_DIR}/galen_college_of_nursing_louisville__3033039__bks.csv"
    fieldnames = [
        'source_url', 'school_id', 'department_code', 'course_code',
        'course_title', 'section', 'section_instructor', 'term',
        'isbn', 'title', 'author', 'material_adoption_code', 'crawled_on', 'updated_on'
    ]

    total = 0
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for pdf_file, dept, term, rows in all_rows:
            for row in rows:
                writer.writerow(row)
                total += 1

    print(f"\nTotal: {total} rows written to {csv_path}")

if __name__ == '__main__':
    main()
