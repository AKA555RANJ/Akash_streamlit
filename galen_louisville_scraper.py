#!/usr/bin/env python3
"""Parse Galen College booklist PDFs into a standardized CSV for Louisville campus."""

import csv
import re
import fitz  # pymupdf

DATA_DIR = "data/galen_college_of_nursing_louisville__3033039__bks"
SOURCE_URL = "https://galen.libguides.com/Booklist"
SCHOOL_ID = "3033039"
CRAWLED_ON = "2026-03-21 00:00:00"

# PDF files and their metadata (exclude VN Texas - not applicable to Louisville KY)
PDFS = [
    ("PN_Booklist_Summer_2026.pdf", "PN", "Summer 2026"),
    ("ADN_Booklist_Summer_2026.pdf", "ADN", "Summer 2026"),
    ("BSN_Pre_Licensure_Booklist_Summer_2026.pdf", "BSN", "Summer 2026"),
    ("RN_BSN_Post_Licensure_Booklist_Spring_Session_II_2026.pdf", "RN-BSN", "Spring Session II 2026"),
    ("MSN_Post_Licensure_Booklist_Spring_Session_II_2026.pdf", "MSN", "Spring Session II 2026"),
    ("DNP_Post_Licensure_Booklist_Spring_Session_II_2026.pdf", "DNP", "Spring Session II 2026"),
]

# ISBN pattern - 13 digit
ISBN_RE = re.compile(r'97[89]\d{10}')

# All known course prefixes across Galen programs
COURSE_PREFIXES = (
    'AID|BIO|BSL|CLS|COM|ENG|GPS|HUM|LDR|MAT|'
    'NSG|NU|NUR|PHL|PHM|PNS|PSY|SOC|STA|DNP'
)

# Course header pattern - matches all prefixes, slash courses (e.g. NU 136/137),
# optional colon before title (e.g. "NSG 7300 Health Policy Leadership")
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


# Pattern to detect the start of a new APA citation entry.
# Matches: optional ⌨/† symbols, then author surname (2+ chars starting with capital),
# followed by (year) somewhere in the line.
# Requires 2+ word chars to avoid false positives on continuation lines like "P. (2022)."
NEW_ENTRY_RE = re.compile(
    r'^[⌨†\s]*'                      # optional symbols/whitespace
    r'[*]?'                           # optional asterisk (e.g. *National Academy)
    r'[A-Z][A-Za-z\'\-]+'            # surname: 2+ chars starting with capital
    r'.*'                             # rest of author text
    r'\((?:\d{4}|n\.d\.)\)'           # (year) or (n.d.)
)

# Publisher names for splitting title from publisher
PUBLISHERS_RE = re.compile(
    r'\.\s*(?:Elsevier|F\.\s*A\.\s*Davis|Wolters Kluwer|Jones\s*&?\s*Bartlett|'
    r'Lippincott|Pearson|Springer Publishing|Springer|McGraw|Cengage|Sage|Oxford|'
    r'Cambridge|American Psychological|Wiley|Mosby|Saunders|Health Administration Press|'
    r'Virginia Tech|Sigma|Theta Tau|VitalSource|National Academies|National League|'
    r'Jossey|W\.\s*W\.\s*Norton|Open\s*Stax|OpenStax|American Nurses Association|'
    r'Jones and Bartlett|Rowman|AACN|Brookes Publishing|American Association)'
)


def is_new_entry_start(line):
    """Check if a line starts a new book entry."""
    stripped = line.strip()
    if not stripped:
        return False
    # Lines starting with ⌨ or † followed by author text
    if stripped[0] in '⌨†' and len(stripped) > 1:
        return True
    # Lines matching author citation pattern (Surname, I. (year).)
    if NEW_ENTRY_RE.match(stripped):
        return True
    return False


def current_entry_has_year(lines_so_far):
    """Check if accumulated entry text already contains a year pattern, indicating it's complete."""
    text = ' '.join(lines_so_far)
    return bool(re.search(r'\((?:\d{4}|n\.d\.)\)', text))


def group_entry_lines(lines):
    """Group section lines into individual book entries.

    A new entry starts when:
    1. The line begins with ⌨ or † (always a new entry), OR
    2. The line matches an author citation pattern AND the current accumulated
       entry already contains a year (i.e., the previous entry is complete).
    This prevents splitting multi-line author lists where continuation lines
    also look like author names (e.g., 'Lazzara, J., ... (2020). Title').
    """
    entries = []
    current = []
    for line in lines:
        stripped = line.strip()
        if current:
            # Lines with ⌨/† always start a new entry
            if stripped and stripped[0] in '⌨†':
                entries.append(' '.join(current))
                current = [line]
            # Author-pattern lines only start new entry if current is complete
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
    """Parse a single book entry text into isbn, title, author."""
    # Clean symbols
    clean = re.sub(r'[⌨†]', '', entry_text).strip()
    clean = clean.lstrip('* ')  # remove leading asterisk
    # Strip URLs (discount links, open textbook URLs, etc.)
    clean = re.sub(r'https?://\S+', '', clean).strip()
    # Strip bracketed URLs
    clean = re.sub(r'\[https?://[^\]]*\]', '', clean).strip()

    # Find ISBN
    isbn_match = ISBN_RE.search(clean)
    isbn = isbn_match.group(0) if isbn_match else ""

    # Skip non-book entries (just instructions or handbook recommendations)
    if not isbn:
        # Still allow entries with a title (open textbooks, etc.)
        # but skip generic recommendations like "Recommend use of any..."
        if clean.lower().startswith('recommend use of'):
            return None
        if 'Please' in clean or 'discount' in clean.lower():
            return None

    # Try to split on year pattern: Author. (year). Title...
    yr_match = re.search(r'\.\s*,?\s*\((?:\d{4}|n\.d\.)\)\.?\s*', clean)
    if yr_match:
        author = clean[:yr_match.start()].strip()
        rest_after_year = clean[yr_match.end():].strip()

        # If there's an ISBN, title is between year and ISBN
        if isbn:
            before_isbn = rest_after_year[:rest_after_year.find(isbn)].strip().rstrip('.')
        else:
            before_isbn = rest_after_year.strip().rstrip('.')

        # Split title from publisher
        pub_match = PUBLISHERS_RE.search(before_isbn)
        if pub_match:
            title = before_isbn[:pub_match.start()].strip().rstrip('.')
        else:
            # Remove trailing publisher-like text after last period
            title = before_isbn.strip().rstrip('.')
    elif isbn:
        # No year found but ISBN exists - take everything before ISBN
        before_isbn = clean[:clean.find(isbn)].strip().rstrip('.')
        author = ""
        title = before_isbn
    else:
        # No year, no ISBN - likely an open textbook with URL or non-standard entry
        # Try to extract author and title anyway
        author = ""
        title = clean.rstrip('.')
        # If it looks like a URL-only entry, try to parse
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

    # Clean up title - remove edition info at end
    title = re.sub(r'\s*\(\d+\w*\s+ed\..*?\)\s*$', '', title).strip()
    title = title.rstrip('.')
    # Remove trailing asterisk (used as footnote marker)
    title = title.rstrip('*').rstrip()

    if not title:
        return None

    return {
        'isbn': isbn,
        'title': title,
        'author': author,
    }


def parse_books_from_section(lines):
    """Parse book entries from a list of lines in a Required/Recommended section."""
    entries = group_entry_lines(lines)
    books = []
    for entry_text in entries:
        result = parse_single_entry(entry_text)
        if result:
            books.append(result)
    return books


def parse_pdf(pdf_path, department, term):
    """Parse a single PDF and return list of row dicts."""
    text = extract_text(f"{DATA_DIR}/{pdf_path}")
    rows = []

    # Split text into lines
    lines = text.split('\n')

    current_course_code = ""
    current_course_title = ""
    current_section_type = ""  # "Required" or "Recommended"
    section_lines = []

    def flush_section():
        nonlocal section_lines
        if not section_lines or not current_course_code:
            section_lines = []
            return

        # Check for "no required textbooks" type lines
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

        # Skip header/footer lines
        if line_stripped.startswith('Prepared by:') or line_stripped.startswith('Page:') or line_stripped.startswith('Revised'):
            continue
        if 'BOOKLIST for' in line_stripped:
            continue
        if line_stripped.startswith('The following outlines') or line_stripped.startswith('Use International'):
            continue

        # Check for course header
        course_match = COURSE_RE.match(line_stripped)
        if course_match:
            flush_section()
            current_course_code = course_match.group(1)
            current_course_title = course_match.group(2).strip()
            current_section_type = ""
            continue

        # Check for "no required textbooks" right after course header (no Required: section)
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

        # Check for Required/Recommended header
        if line_stripped == 'Required:' or line_stripped.startswith('Required:'):
            flush_section()
            current_section_type = "Required"
            continue
        if line_stripped == 'Recommended:' or line_stripped.startswith('Recommended:'):
            flush_section()
            current_section_type = "Recommended"
            continue

        # Accumulate lines in current section
        if current_section_type and current_course_code:
            # Skip instruction/boilerplate lines (but NOT if line contains an ISBN)
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
            # Skip pure URL lines (no author/ISBN content), continuation URLs
            if not has_isbn and re.match(r'^(https?://|\[https?://|GalenCollegeofNursing)', line_stripped):
                continue
            # Skip page numbers (1-2 digits) and dates that appear inline
            # Don't skip ISBNs (10+ digit numbers starting with 97)
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

    # Write CSV
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
