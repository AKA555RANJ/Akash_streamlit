import re
from datetime import datetime, timezone

import scrapy

from dtcc_syllabi_scrapy.items import DtccSyllabusItem

CATALOG_BASE = "https://dtcc.smartcatalogiq.com"
COURSES_URL = f"{CATALOG_BASE}/en/current/catalog/courses/"

SCHOOL_ID = "2984303"

class DtccSyllabiSpider(scrapy.Spider):
    name = "dtcc_syllabi"
    allowed_domains = ["dtcc.smartcatalogiq.com"]

    custom_settings = {}

    def __init__(self, target_depts=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._target_depts = (
            set(d.strip().upper() for d in target_depts.split(",") if d.strip())
            if target_depts else None
        )
        if self._target_depts:
            self.logger.info(f"Filtering to depts: {self._target_depts}")

    def start_requests(self):
        yield scrapy.Request(COURSES_URL, callback=self.parse_departments)

    def parse_departments(self, response):
        dept_links = response.css('a[href*="/en/current/catalog/courses/"]')

        count = 0
        for link in dept_links:
            href = link.attrib.get("href", "")
            text = link.css("::text").get("").strip()
            path_after_courses = href.rstrip("/").split("/courses/")[-1]
            if not path_after_courses or "/" in path_after_courses:
                continue
            dept_code, dept_name = self._parse_dept_text(text)
            if not dept_code:
                self.logger.debug(f"Skipping unparseable dept link: {text!r}")
                continue

            if self._target_depts and dept_code not in self._target_depts:
                continue

            count += 1
            yield scrapy.Request(
                response.urljoin(href),
                callback=self.parse_department,
                cb_kwargs={"dept_code": dept_code, "dept_name": dept_name},
            )

        self.logger.info(f"Found {count} department(s) to crawl")

    def parse_department(self, response, dept_code, dept_name):
        course_links = response.css("a[href]")

        count = 0
        for link in course_links:
            href = link.attrib.get("href", "")
            if not re.search(r"/courses/[^/]+/\d+/[^/]+/?$", href):
                continue

            text = link.css("::text").get("").strip()
            if not text:
                continue

            count += 1
            yield scrapy.Request(
                response.urljoin(href),
                callback=self.parse_course,
                cb_kwargs={"dept_code": dept_code, "dept_name": dept_name},
            )

        self.logger.info(f"Dept {dept_code}: found {count} course link(s)")

    def parse_course(self, response, dept_code, dept_name):
        h1_parts = response.css("h1 ::text").getall()
        h1 = " ".join(p.strip() for p in h1_parts if p.strip())
        course_code, course_title = self._parse_h1(h1)
        if not course_code:
            self.logger.warning(f"Could not parse course h1: {h1!r}")
            return

        syllabus_url = response.url.rstrip("/") + "/?defined_custom_rendering=true"

        yield scrapy.Request(
            syllabus_url,
            callback=self.parse_syllabus,
            cb_kwargs={
                "dept_code": dept_code,
                "dept_name": dept_name,
                "course_code": course_code,
                "course_title": course_title,
                "source_url": response.url,
            },
        )

    def parse_syllabus(self, response, dept_code, dept_name,
                       course_code, course_title, source_url):
        now = datetime.now(timezone.utc).isoformat()

        syllabus_html = response.text

        yield DtccSyllabusItem(
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
            crawled_on=now,
            downloaded_on="",
            _syllabus_html=syllabus_html,
        )

    @staticmethod
    def _parse_dept_text(text):
        match = re.match(r"^([A-Z]{2,5})\s*[-\u2013]\s*(.+)$", text, re.IGNORECASE)
        if match:
            return match.group(1).upper(), match.group(2).strip()
        return None, None

    @staticmethod
    def _parse_h1(h1_text):
        match = re.match(r"^([A-Z]{2,5})\s+(\d{3}[A-Z]?)\s+(.+)$", h1_text, re.IGNORECASE)
        if match:
            code = f"{match.group(1).upper()}-{match.group(2)}"
            title = match.group(3).strip()
            return code, title
        return None, None
