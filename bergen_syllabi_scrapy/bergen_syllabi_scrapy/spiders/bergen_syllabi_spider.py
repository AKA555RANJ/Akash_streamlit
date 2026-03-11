import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import scrapy

from bergen_syllabi_scrapy.items import BergenSyllabusItem

CATALOG_BASE = "https://catalog.bergen.edu"
COURSE_LIST_URL = f"{CATALOG_BASE}/content.php"
LASERFICHE_SEARCH_TEMPLATE = (
    "https://lf.bergen.edu/WebLink/Search.aspx?searchcommand="
    "{{[Syllabus]:[Course_Code]=%22{course_code}%22}}"
    "%20%26%20{{LF:LookIn=%22\\Syllabus%22}}"
)

SCHOOL_ID = "3061268"


def _build_page_url(page_num):
    params = {
        "catoid": "8",
        "navoid": "368",
        "filter[cpage]": str(page_num),
        "filter[item_type]": "3",
        "filter[only_active]": "1",
        "filter[3]": "1",
    }
    return f"{COURSE_LIST_URL}?{urlencode(params)}"


def _parse_course_code(text):
    text = text.strip()
    match = re.match(r"^([A-Z]{2,5}-\d{3}[A-Z]?)\s+(.+)$", text)
    if match:
        code = match.group(1)
        title = match.group(2).strip()
        dept = code.split("-")[0]
        return code, title, dept
    return None, None, None


class BergenSyllabiSpider(scrapy.Spider):
    name = "bergen_syllabi"
    allowed_domains = ["catalog.bergen.edu", "lf.bergen.edu"]

    custom_settings = {}

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider._max_items = crawler.settings.getint("CLOSESPIDER_ITEMCOUNT", 0)
        spider._items_yielded = 0
        return spider

    def __init__(self, target_depts=None, max_pages=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._target_depts = (
            set(d.strip().upper() for d in target_depts.split(",") if d.strip())
            if target_depts else None
        )
        self._max_pages = int(max_pages) if max_pages else None

        if self._target_depts:
            self.logger.info(f"Filtering to depts: {self._target_depts}")

    def start_requests(self):
        yield scrapy.Request(
            _build_page_url(1),
            callback=self.parse_course_list,
            cb_kwargs={"page_num": 1},
        )

    def parse_course_list(self, response, page_num):
        course_links = response.css('a[href*="preview_course_nopop.php?catoid=8&coid="]')

        if not course_links:
            self.logger.warning(f"No course links found on page {page_num}")
            return

        self.logger.info(f"Page {page_num}: found {len(course_links)} course links")

        for link in course_links:
            if self._max_items and self._items_yielded >= self._max_items:
                self.logger.info(f"Reached CLOSESPIDER_ITEMCOUNT={self._max_items}")
                return

            text = link.css("::text").get("").strip()
            href = link.attrib.get("href", "")

            course_code, course_title, dept = _parse_course_code(text)
            if not course_code:
                self.logger.debug(f"Skipping unparseable entry: {text!r}")
                continue

            if self._target_depts and dept not in self._target_depts:
                continue

            detail_url = response.urljoin(href)

            lf_url = LASERFICHE_SEARCH_TEMPLATE.format(course_code=course_code)

            now = datetime.now(timezone.utc).isoformat()

            item = BergenSyllabusItem(
                school_id="3061268",
                term_code="",
                term="",
                department_code=dept,
                department_name="",
                course_code=course_code,
                course_titel=course_title,
                section_code="",
                instructor="",
                syllabus_filename="",
                syllabus_file_format="",
                syllabus_filepath_local="",
                syllabus_filesize="",
                syllabus_file_source_url=lf_url,
                source_url=detail_url,
                crawled_on=now,
                downloaded_on="",
            )
            self._items_yielded += 1
            yield item

        next_page = page_num + 1
        if self._max_pages and next_page > self._max_pages:
            self.logger.info(f"Reached max_pages={self._max_pages}")
            return
        
        has_next = self._has_next_page(response, next_page)
        if has_next:
            self.logger.info(f"Following to page {next_page}")
            yield scrapy.Request(
                _build_page_url(next_page),
                callback=self.parse_course_list,
                cb_kwargs={"page_num": next_page},
            )

    def _has_next_page(self, response, next_page_num):
        page_links = response.css("a[href*='filter%5Bcpage%5D='], a[href*='filter[cpage]=']")
        for link in page_links:
            href = link.attrib.get("href", "")
            text = link.css("::text").get("").strip()
            if text == str(next_page_num):
                return True
            if f"cpage%5D={next_page_num}" in href or f"cpage]={next_page_num}" in href:
                return True


        pagination_text = response.css("body").re(r"Page:.*")
        if pagination_text:
            for pt in pagination_text:
                if str(next_page_num) in pt:
                    return True

        return False
