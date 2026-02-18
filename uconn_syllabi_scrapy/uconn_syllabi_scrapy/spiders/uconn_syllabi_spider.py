"""
UConn Syllabi Spider
====================
Scrapes https://syllabus.uconn.edu/public/ — a plain PHP site with no
ASP.NET/ViewState/AJAX. Two GET requests per term are sufficient:

  1. GET search_term.php         → dropdown of all terms
  2. GET search_term.php?term=N  → HTML table of all syllabi for that term

Spider arguments (-a key=value):
  target_terms  — comma-separated term codes to scrape (default: all)
  target_depts  — comma-separated dept prefixes to keep (default: all)
  no_download   — set to "1" to skip file downloads (metadata-only mode)
"""

import re
from urllib.parse import urljoin, urlencode, urlparse, parse_qs

import scrapy

from uconn_syllabi_scrapy.items import UConnSyllabusItem

BASE_URL = "https://syllabus.uconn.edu/public/"
TERM_LIST_URL = urljoin(BASE_URL, "search_term.php")


# ---------------------------------------------------------------------------
# Pure helper functions (module-level, easy to unit-test)
# ---------------------------------------------------------------------------

def _extract_term_options(response):
    """Return list of (term_code, term_label) from the term <select>.

    Tries CSS selectors in order of specificity.  Only keeps options whose
    value is a digit string (rules out blank/placeholder options).
    """
    selectors_to_try = [
        'select[name="term"] option',
        "select#term option",
        "form select option",
    ]
    for sel in selectors_to_try:
        options = response.css(sel)
        if options:
            results = []
            for opt in options:
                value = opt.attrib.get("value", "").strip()
                label = opt.css("::text").get("").strip()
                if value.isdigit():
                    results.append((value, label))
            if results:
                return results
    return []


def _split_class(class_name):
    """Split "CSE 3666" → ("CSE", "3666").  Returns ("", "") on bad input."""
    parts = class_name.strip().split(None, 1)
    if len(parts) == 2:
        return parts[0].upper(), parts[1]
    if len(parts) == 1:
        return parts[0].upper(), ""
    return "", ""


def _find_next_page(response):
    """Defensive pagination guard — returns next-page URL or None.

    The current UConn site has no pagination, but guard against it so the
    spider doesn't silently miss pages if the site ever adds them.
    """
    # Common patterns: rel="next", text "Next", "»"
    next_link = (
        response.css('a[rel="next"]::attr(href)').get()
        or response.css('a:contains("Next")::attr(href)').get()
        or response.css('a:contains("»")::attr(href)').get()
    )
    if next_link:
        return response.urljoin(next_link)
    return None


def _parse_results_table(response, term_code, term_name):
    """Parse the syllabus results table and yield raw row dicts.

    Uses header-based column discovery with positional fallback:
      class_col=1, section_col=2, instructor_col=3, syllabi_col=4
    (0-indexed, skipping the first "Term" column which is col 0)

    Yields dicts with keys: class_name, section, instructor, href
    """
    # Discover column indices from <th> headers
    headers = [th.css("::text").get("").strip().lower() for th in response.css("table th")]

    def col_index(names, default):
        for name in names:
            for i, h in enumerate(headers):
                if name in h:
                    return i
        return default

    class_col    = col_index(["class"],                  1)
    section_col  = col_index(["section"],                2)
    instructor_col = col_index(["instructor"],           3)
    syllabi_col  = col_index(["syllabi", "syllabus"],    4)

    # The site emits bare <tr> with no <tbody>/<thead> wrappers, so we use
    # "table tr" and skip rows that have <th> elements (header row) or have
    # no <td> elements (empty separator rows the site inserts between rows).
    for row in response.css("table tr"):
        cells = row.css("td")
        if len(cells) <= max(class_col, section_col, instructor_col, syllabi_col):
            continue

        class_name = cells[class_col].css("::text").get("").strip()
        section    = cells[section_col].css("::text").get("").strip()
        instructor = cells[instructor_col].css("::text").get("").strip()

        # Download link in the syllabi cell
        href = cells[syllabi_col].css("a::attr(href)").get("").strip()

        if not class_name:
            continue

        yield {
            "class_name": class_name,
            "section":    section,
            "instructor": instructor,
            "href":       href,
        }


# ---------------------------------------------------------------------------
# Spider
# ---------------------------------------------------------------------------

class UConnSyllabiSpider(scrapy.Spider):
    name = "uconn_syllabi"
    allowed_domains = ["syllabus.uconn.edu"]

    # Spider-level custom settings (can be overridden in settings.py)
    custom_settings = {}

    def __init__(self, target_terms=None, target_depts=None, no_download=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Parse comma-separated argument lists
        self._target_terms = set(t.strip() for t in target_terms.split(",") if t.strip()) if target_terms else None
        self._target_depts = set(d.strip().upper() for d in target_depts.split(",") if d.strip()) if target_depts else None
        self._no_download = str(no_download).strip() in ("1", "true", "yes") if no_download else False

        if self._target_terms:
            self.logger.info(f"Filtering to terms: {self._target_terms}")
        if self._target_depts:
            self.logger.info(f"Filtering to depts: {self._target_depts}")
        if self._no_download:
            self.logger.info("Download mode: OFF (metadata only)")

    def start_requests(self):
        yield scrapy.Request(TERM_LIST_URL, callback=self.parse_term_list)

    # ------------------------------------------------------------------
    # Callback 1: Parse term dropdown
    # ------------------------------------------------------------------

    def parse_term_list(self, response):
        options = _extract_term_options(response)
        if not options:
            self.logger.warning("No term options found on the term list page.")
            return

        self.logger.info(f"Found {len(options)} terms total.")

        for term_code, term_label in options:
            if self._target_terms and term_code not in self._target_terms:
                continue
            url = f"{TERM_LIST_URL}?term={term_code}"
            self.logger.info(f"Queuing term {term_code}: {term_label}")
            yield scrapy.Request(
                url,
                callback=self.parse_term_results,
                cb_kwargs={"term_code": term_code, "term_name": term_label},
            )

    # ------------------------------------------------------------------
    # Callback 2: Parse results table for a single term
    # ------------------------------------------------------------------

    def parse_term_results(self, response, term_code, term_name):
        rows = list(_parse_results_table(response, term_code, term_name))
        self.logger.info(f"Term {term_code} ({term_name}): {len(rows)} rows before dept filter")

        yielded = 0
        for row in rows:
            class_name = row["class_name"]
            dept, _ = _split_class(class_name)

            # Apply dept filter
            if self._target_depts and dept not in self._target_depts:
                continue

            href = row["href"]

            # Resolve absolute URL and encode pipe character
            if href:
                abs_url = response.urljoin(href)
                # Encode raw pipe character (safe; %7C already valid)
                abs_url = abs_url.replace("|", "%7C")
            else:
                abs_url = ""

            item = UConnSyllabusItem(
                term_name  = term_name,
                term_code  = term_code,
                class_name = class_name,
                section    = row["section"],
                instructor = row["instructor"],
                syllabus_web_url        = abs_url,
                syllabus_local_filepath = "",
                syllabus_local_filename = "",
                # FilesPipeline requires file_urls
                file_urls = [abs_url] if (abs_url and not self._no_download) else [],
                files     = [],
            )
            yielded += 1
            yield item

        self.logger.info(f"Term {term_code}: yielded {yielded} items after dept filter")

        # Defensive pagination guard
        next_page = _find_next_page(response)
        if next_page:
            self.logger.info(f"Following next page: {next_page}")
            yield scrapy.Request(
                next_page,
                callback=self.parse_term_results,
                cb_kwargs={"term_code": term_code, "term_name": term_name},
            )
