import re

import scrapy

from course_catalog_scrapy.items import CourseItem

TERM = "2026 Fall"
CREDITS_XPATH = (
    "//span[contains(@class,'class-div-header')][contains(.,'Credits')]"
    "/following-sibling::span[contains(@class,'class-div-info')][1]/text()"
)
NUM_RE = re.compile(r"\d+(?:\.\d+)?")

class UMassBostonSpider(scrapy.Spider):

    name = "umb"
    school_id = "3037211"
    slug = "university_of_massachusetts-boston__3037211__cc"
    allowed_domains = ["courses.umb.edu"]
    start_urls = [f"https://courses.umb.edu/course_catalog/subjects/{TERM}"]
    custom_settings = {
        "USER_AGENT": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "ROBOTSTXT_OBEY": False,
    }

    def parse(self, response):
        for href in response.css("a::attr(href)").getall():
            if "/course_catalog/courses/" not in href:
                continue
            if "/courses/ugrd_" in href:
                graduate_type = "Undergraduate"
            elif "/courses/grd_" in href:
                graduate_type = "Graduate"
            else:
                continue
            yield response.follow(
                href, callback=self.parse_subject,
                cb_kwargs={"graduate_type": graduate_type},
            )

    def parse_subject(self, response, graduate_type):
        for a in response.css("h4 a"):
            href = a.css("::attr(href)").get() or ""
            if "/course_catalog/course_info/" not in href:
                continue
            seg = href.split("/course_info/", 1)[1]
            seg = seg.split("_", 1)[1] if "_" in seg else seg
            dept = seg.split("_2026", 1)[0].strip()
            number = seg.rsplit("_", 1)[1].strip() if "_" in seg else ""
            code = f"{dept} {number}".strip()
            full = " ".join((a.css("::text").get() or "").split())
            title = full[len(code):].strip() if full.startswith(code) else full
            yield response.follow(
                href, callback=self.parse_course,
                cb_kwargs={"dept": dept, "code": code, "title": title,
                           "graduate_type": graduate_type},
            )

    def parse_course(self, response, dept, code, title, graduate_type):
        info = response.xpath(CREDITS_XPATH).get() or ""
        m = NUM_RE.search(info)
        yield CourseItem(
            school_id=self.school_id,
            department_code=dept,
            course_code=code,
            course_title=title,
            credits=m.group(0) if m else "",
            graduate_type=graduate_type,
            term=TERM,
            academic_year="",
            source_url=response.url,
        )
