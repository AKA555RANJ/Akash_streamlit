import re

import scrapy

from course_catalog_scrapy.items import CourseItem
from course_catalog_scrapy.utils import term_decision

# Course heading looks like "AAC 200 - Topics in Arts Administration ...".
COURSE_CODE_RE = re.compile(r"^([A-Z]{2,5})\s?(\d{3}[A-Z]?)\b")
# Credits appear in the description, e.g. "3 credit(s)." or "1-3 credits".
CREDITS_RE = re.compile(r"(\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?)\s*credit", re.I)
YEAR_RE = re.compile(r"\d{4}-\d{4}")


class SouthernCtSpider(scrapy.Spider):
    name = "southern_ct"
    school_id = "3009619"
    slug = "southern_connecticut_state_university__3009619__cc"
    allowed_domains = ["catalog.southernct.edu"]

    start_urls_by_type = {
        "Undergraduate": "https://catalog.southernct.edu/undergraduate/courses.html",
        "Graduate": "https://catalog.southernct.edu/graduate/courses.html",
    }

    def start_requests(self):
        for graduate_type, url in self.start_urls_by_type.items():
            yield scrapy.Request(
                url,
                callback=self.parse,
                cb_kwargs={"graduate_type": graduate_type},
            )

    def _academic_year(self, response):
        # Prefer the breadcrumb / selected subnav link text, fall back to page text.
        candidates = response.css(
            "nav#breadcrumbs a::text, ul.prevnav li.selected a::text"
        ).getall()
        for text in candidates:
            m = YEAR_RE.search(text)
            if m:
                return m.group(0)
        m = YEAR_RE.search(response.text)
        return m.group(0) if m else ""

    def parse(self, response, graduate_type):
        academic_year = self._academic_year(response)
        if not academic_year:
            self.logger.warning(f"No academic_year found on {response.url}")

        boxes = response.css("div.course-box")
        self.logger.info(f"{response.url}: {len(boxes)} course boxes")

        for box in boxes:
            heading = " ".join(
                t.strip() for t in box.css("h2 ::text").getall() if t.strip()
            )
            if not heading:
                continue

            code_match = COURSE_CODE_RE.match(heading)
            if not code_match:
                self.logger.debug(f"Skipping unparseable heading: {heading!r}")
                continue

            department_code = code_match.group(1)
            course_code = f"{code_match.group(1)} {code_match.group(2)}"

            # Title is everything after the first " - " separator.
            title = ""
            if " - " in heading:
                title = heading.split(" - ", 1)[1].strip()

            credits_text = " ".join(
                t.strip() for t in box.css("p.course-credits ::text").getall() if t.strip()
            )
            credits_match = CREDITS_RE.search(credits_text)
            credits = credits_match.group(1).replace(" ", "") if credits_match else ""

            # "Last Term Offered: Spring 2027" -> "Spring 2027"
            term_text = " ".join(
                t.strip() for t in box.css("p.last-term-offered ::text").getall() if t.strip()
            )
            last_term = term_text.split(":", 1)[1].strip() if ":" in term_text else term_text
            # Single-year catalog: drop courses whose last term is outside 2026-2027
            # (keep 2026-2027 terms and not-yet-offered/new courses).
            keep, term = term_decision(last_term, academic_year)
            if not keep:
                continue

            box_id = box.attrib.get("id", "")
            source_url = f"{response.url}#{box_id}" if box_id else response.url

            yield CourseItem(
                school_id=self.school_id,
                department_code=department_code,
                course_code=course_code,
                course_title=title,
                credits=credits,
                graduate_type=graduate_type,
                term=term,
                academic_year=academic_year,
                source_url=source_url,
            )
