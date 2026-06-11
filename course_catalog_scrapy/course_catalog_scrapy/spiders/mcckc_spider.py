import re

import scrapy

from course_catalog_scrapy.items import CourseItem

TENANT = "mcckc.elumenapp.com"
API = "https://api-prod.elumenapp.com/catalog/sites/publish/content/{key}?tenant=" + TENANT
SITE = "https://mcckc.elumenapp.com/catalog/"
CODE_RE = re.compile(r"^([A-Z]{2,5})\s?\d")
CREDITS_RE = re.compile(r"([\d.]+)\s*Credits?", re.I)
YEAR_RE = re.compile(r"20\d\d-20\d\d")

def content_url(route):
    return API.format(key=route.replace("/", ","))

class McckcSpider(scrapy.Spider):
    name = "mcckc"
    school_id = "3050281"
    slug = "metropolitan_community_college-kansas_city__3050281__cc"
    allowed_domains = ["api-prod.elumenapp.com", "mcckc.elumenapp.com"]
    custom_settings = {"DOWNLOAD_DELAY": 0.3, "CONCURRENT_REQUESTS": 6}

    def start_requests(self):
        yield scrapy.Request(content_url("2026-2027/courses"), callback=self.parse_courses)

    def parse_courses(self, response):
        for route in sorted(set(re.findall(r"2026-2027/department/[a-z0-9-]+", response.text))):
            yield scrapy.Request(content_url(route), callback=self.parse_department)

    def parse_department(self, response):
        for a in response.css("a.navitem"):
            text = " ".join(t.strip() for t in a.css("span.navitem-x-text::text").getall() if t.strip())
            href = a.attrib.get("href", "")
            if not text or "/course/" not in href:
                continue
            code, _, title = text.partition(" - ")
            code = code.strip()
            if not CODE_RE.match(code):
                continue
            yield scrapy.Request(
                content_url(href),
                callback=self.parse_course,
                cb_kwargs={"code": code, "title": title.strip(), "src": SITE + href},
            )

    def parse_course(self, response, code, title, src):
        cm = CREDITS_RE.search(response.text)
        ym = YEAR_RE.search(response.text)
        dm = CODE_RE.match(code)
        yield CourseItem(
            school_id=self.school_id,
            department_code=dm.group(1) if dm else code.split()[0],
            course_code=code,
            course_title=title,
            credits=cm.group(1) if cm else "",
            graduate_type="Undergraduate",
            term="",
            academic_year=ym.group(0) if ym else "",
            source_url=src,
        )
