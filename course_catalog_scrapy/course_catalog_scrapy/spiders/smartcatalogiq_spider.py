import re
from urllib.parse import urlparse

import scrapy

from course_catalog_scrapy.items import CourseItem, year_from_page, year_from_url

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CODE_RE = re.compile(r"^[A-Z]{2,6}\s?\d{2,4}[A-Z]?$")


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


class SmartCatalogIQSpider(scrapy.Spider):
    # SmartCatalogIQ (newer, server-rendered): a courses index lists subject
    # pages; each subject page links its courses as <a><span>CODE</span> Title</a>.
    custom_settings = {"ROBOTSTXT_OBEY": False, "DOWNLOAD_DELAY": 0.2,
                       "CONCURRENT_REQUESTS": 6, "USER_AGENT": UA}
    courses_index = None

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.seen = set()

    def start_requests(self):
        yield scrapy.Request(self.courses_index, callback=self.parse_index)

    def parse_index(self, response):
        base = urlparse(self.courses_index).path.rstrip("/")
        seen = set()
        for href in response.css("a::attr(href)").getall():
            p = urlparse(response.urljoin(href.split("#")[0].split("?")[0])).path
            if p.startswith(base + "/"):
                rest = p[len(base) + 1:].strip("/")
                if rest and "/" not in rest and rest not in seen:
                    seen.add(rest)
                    yield response.follow(p, callback=self.parse_subject)

    def parse_subject(self, response):
        academic_year = year_from_page(response.text) or year_from_url(response.url)
        for a in response.css("a"):
            code = _norm(a.css("span::text").get() or "")
            if not CODE_RE.match(code) or code in self.seen:
                continue
            full = _norm(" ".join(a.css("::text").getall()))
            title = full[len(code):].strip(" .:-–—") if full.startswith(code) else full
            if len(title) < 2:
                continue
            self.seen.add(code)
            yield CourseItem(
                school_id=self.school_id, department_code=code.split()[0],
                course_code=code, course_title=title, credits="",
                graduate_type="", term="", academic_year=academic_year,
                source_url=response.url,
            )


class HebrewUnionSpider(SmartCatalogIQSpider):
    name = "hebrew_union"
    school_id = "3067520"
    slug = "hebrew_union_college-jewish_institute_of_religion__3067520__cc"
    allowed_domains = ["huc.smartcatalogiq.com"]
    courses_index = "https://huc.smartcatalogiq.com/en/current/academic-catalog/courses"


class CentralConnSpider(SmartCatalogIQSpider):
    name = "central_conn"
    school_id = "3009606"
    slug = "central_connecticut_state_university__3009606__cc"
    allowed_domains = ["ccsu.smartcatalogiq.com"]
    courses_index = "https://ccsu.smartcatalogiq.com/en/current/undergraduate-graduate-catalog/all-courses"
