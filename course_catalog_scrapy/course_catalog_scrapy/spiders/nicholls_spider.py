import re

import scrapy

from course_catalog_scrapy.items import CourseItem

SUBJ_RE = re.compile(r"/catalog-2026-2027/courses_of_instruction/[^/#?]+/?$")
FULL_RE = re.compile(r"^([A-Z]{2,5}\s?\d{3}[A-Z]?)[.\s]+(.*?)\.?\s+(\d+(?:\.\d+)?)\s*-\s*\d+\s*-\s*\d+")
STRONG_RE = re.compile(r"^([A-Z]{2,5}\s?\d{3}[A-Z]?)\.?\s*(.*)$")
YEAR_RE = re.compile(r"20\d\d-20?\d\d")


class NichollsSpider(scrapy.Spider):
    name = "nicholls"
    school_id = "3035086"
    slug = "nicholls_state_university__3035086__cc"
    allowed_domains = ["nicholls.edu"]
    start_urls = ["https://www.nicholls.edu/catalog-2026-2027/courses_of_instruction/"]

    def parse(self, response):
        seen = set()
        for href in response.css("a::attr(href)").getall():
            clean = href.split("#")[0]
            if SUBJ_RE.search(clean) and clean not in seen:
                seen.add(clean)
                yield response.follow(clean, callback=self.parse_subject)

    def parse_subject(self, response):
        ym = YEAR_RE.search(response.text)
        academic_year = ym.group(0) if ym else ""
        for p in response.css("div.elementor-widget-container p"):
            ptext = " ".join(t.strip() for t in p.css("::text").getall() if t.strip())
            m = FULL_RE.match(ptext)
            if m:
                code, title, credits = m.group(1).strip(), m.group(2).strip().rstrip("."), m.group(3)
            else:
                strong = " ".join(t.strip() for t in p.css("strong::text").getall() if t.strip())
                sm = STRONG_RE.match(strong)
                if not sm:
                    continue
                code, title, credits = sm.group(1).strip(), sm.group(2).strip().rstrip("."), ""
            yield CourseItem(
                school_id=self.school_id,
                department_code=code.split()[0],
                course_code=code,
                course_title=title,
                credits=credits,
                graduate_type="",
                term="",
                academic_year=academic_year,
                source_url=response.url,
            )
