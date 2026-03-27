import re
from datetime import datetime, timezone

import scrapy

from scc_syllabi_scrapy.items import SccSyllabusItem

CATALOG_BASE = "https://catalog.sccsc.edu"
LISTING_URL = (
    f"{CATALOG_BASE}/content.php?catoid=26&navoid=1810"
    "&filter%5Bitem_type%5D=3&filter%5Bonly_active%5D=1&filter%5B3%5D=1"
)
TOTAL_PAGES = 8

SCHOOL_ID = "3088556"

class SccSyllabiSpider(scrapy.Spider):
    name = "scc_syllabi"
    allowed_domains = ["catalog.sccsc.edu"]

    def __init__(self, target_depts=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._target_depts = (
            set(d.strip().upper() for d in target_depts.split(",") if d.strip())
            if target_depts else None
        )
        if self._target_depts:
            self.logger.info(f"Filtering to depts: {self._target_depts}")

    def start_requests(self):
        for page in range(1, TOTAL_PAGES + 1):
            url = f"{LISTING_URL}&filter%5Bcpage%5D={page}#acalog_template_course_filter"
            yield scrapy.Request(url, callback=self.parse_course_listing,
                                cb_kwargs={"page": page})

    def parse_course_listing(self, response, page):
        current_dept_name = None

        for el in response.css("td.block_content h2, "
                               "td.block_content a[href*='preview_course_nopop.php']"):
            if el.root.tag == "h2":
                current_dept_name = el.css("::text").get("").strip()
                continue

            href = el.attrib.get("href", "")
            text = el.css("::text").get("").strip()
            if not text or "preview_course_nopop.php" not in href:
                continue

            dept_code, course_num, course_title = self._parse_course_text(text)
            if not dept_code:
                self.logger.debug(f"Could not parse course text: {text!r}")
                continue

            if self._target_depts and dept_code not in self._target_depts:
                continue

            course_code = f"{dept_code}-{course_num}"
            dept_name = current_dept_name or dept_code

            yield scrapy.Request(
                response.urljoin(href),
                callback=self.parse_course,
                cb_kwargs={
                    "dept_code": dept_code,
                    "dept_name": dept_name,
                    "course_code": course_code,
                    "course_title": course_title,
                },
            )

        self.logger.info(f"Parsed listing page {page}")

    def parse_course(self, response, dept_code, dept_name,
                     course_code, course_title):
        now = datetime.now(timezone.utc).isoformat()

        yield SccSyllabusItem(
            school_id=SCHOOL_ID,
            term_code="",
            term="",
            department_code=dept_code,
            department_name=dept_name,
            course_code=course_code,
            course_titel=course_title,
            section_code="",
            instructor="",
            syllabus_filename="",
            syllabus_file_format="",
            syllabus_filepath_local="",
            syllabus_filesize="",
            syllabus_file_source_url=response.url,
            source_url=response.url,
            crawled_on=now,
            downloaded_on="",
            _syllabus_html=response.text,
        )

    @staticmethod
    def _parse_course_text(text):
        match = re.match(
            r"^([A-Z]{2,5})\s+(\d{3}[A-Z]?)\s*[-\u2013]\s*(.+)$",
            text.strip(), re.IGNORECASE,
        )
        if match:
            return match.group(1).upper(), match.group(2), match.group(3).strip()
        return None, None, None
