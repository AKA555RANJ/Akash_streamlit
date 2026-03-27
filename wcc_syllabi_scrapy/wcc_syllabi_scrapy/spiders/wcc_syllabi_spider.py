import re
from datetime import datetime, timezone

import scrapy

from wcc_syllabi_scrapy.items import WccSyllabusItem

BASE_URL = "https://www.wccnet.edu"
INDEX_URL = (
    f"{BASE_URL}/mywcc/faculty-staff/curriculum/"
    "course-program-data/syllabi/"
)

SCHOOL_ID = "3042636"

class WccSyllabiSpider(scrapy.Spider):
    name = "wcc_syllabi"
    allowed_domains = ["www.wccnet.edu"]

    def start_requests(self):
        yield scrapy.Request(INDEX_URL, callback=self.parse_index)

    def parse_index(self, response):
        links = response.css('a[href$=".php"]')
        for link in links:
            href = link.attrib.get("href", "")
            text = link.css("::text").get("").strip()
            if "/syllabi/" not in href or not text:
                continue
            dept_match = re.search(r"\(([A-Z]{2,5})\)", text)
            if not dept_match:
                continue
            dept_code = dept_match.group(1)
            dept_name = text.split("(")[0].strip()

            yield scrapy.Request(
                response.urljoin(href),
                callback=self.parse_discipline,
                cb_kwargs={
                    "dept_code": dept_code,
                    "dept_name": dept_name,
                },
            )

    def parse_discipline(self, response, dept_code, dept_name):
        now = datetime.now(timezone.utc).isoformat()

        rows = response.css("table tr")
        if rows:
            yield from self._parse_table(response, rows, dept_code,
                                         dept_name, now)
            return

        yield from self._parse_links(response, dept_code, dept_name, now)

    def _parse_table(self, response, rows, dept_code, dept_name, now):
        for row in rows:
            link = row.css("a[href$='.pdf']")
            if not link:
                continue
            href = link.attrib.get("href", "")
            text = link.css("::text").get("").strip()
            if not text or not href:
                continue

            course_code, course_title = self._parse_course_text(text, dept_code)

            date_text = row.css("td:last-child::text").get("").strip()

            pdf_url = response.urljoin(href)
            yield scrapy.Request(
                pdf_url,
                callback=self.save_pdf,
                cb_kwargs={
                    "dept_code": dept_code,
                    "dept_name": dept_name,
                    "course_code": course_code,
                    "course_title": course_title,
                    "source_url": response.url,
                    "crawled_on": now,
                },
            )

    def _parse_links(self, response, dept_code, dept_name, now):
        for link in response.css("a[href$='.pdf']"):
            href = link.attrib.get("href", "")
            text = link.css("::text").get("").strip()
            if not text or not href:
                continue

            course_code, course_title = self._parse_course_text(text, dept_code)

            pdf_url = response.urljoin(href)
            yield scrapy.Request(
                pdf_url,
                callback=self.save_pdf,
                cb_kwargs={
                    "dept_code": dept_code,
                    "dept_name": dept_name,
                    "course_code": course_code,
                    "course_title": course_title,
                    "source_url": response.url,
                    "crawled_on": now,
                },
            )

    def save_pdf(self, response, dept_code, dept_name, course_code,
                 course_title, source_url, crawled_on):
        yield WccSyllabusItem(
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
            source_url=source_url,
            crawled_on=crawled_on,
            downloaded_on="",
            _pdf_bytes=response.body,
        )

    @staticmethod
    def _parse_course_text(text, dept_code):
        cleaned = re.sub(r"\s+", " ", text.strip())
        match = re.match(
            r"^([A-Z]{2,5})\s*(\d{3}[A-Z]?)[\.\s]+(.+)$",
            cleaned, re.IGNORECASE,
        )
        if match:
            code = f"{match.group(1).upper()}-{match.group(2)}"
            title = match.group(3).strip()
            return code, title
        match2 = re.match(
            r"^([A-Z]{2,5})\s*(\d{3}[A-Z]?)\.?\s*$",
            cleaned, re.IGNORECASE,
        )
        if match2:
            code = f"{match2.group(1).upper()}-{match2.group(2)}"
            return code, ""
        return f"{dept_code}-UNKNOWN", cleaned
