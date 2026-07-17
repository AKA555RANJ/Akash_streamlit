import re

import scrapy

from course_catalog_scrapy.items import CourseItem, year_from_url

YEAR_RE = re.compile(r"20\d\d-20\d\d")
CODE_RE = re.compile(r"^[A-Z]{2,5}\s+\d{2,4}[A-Z]?$")
TITLE_UNITS_RE = re.compile(
    r"\s*\(\s*(\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?)\s*\)\s*$"
)
PROGRAM_HREF_RE = re.compile(
    r"/2026-2027-unofficial-catalog-preview/programs-of-study/list-of-programs/[^/]+$"
)
H3_COURSE_RE = re.compile(r"^([A-Z]{2,6})\s+(\d{2,4}[A-Z]?)\s+([A-Z].{2,90})$")

class LosRiosSpider(scrapy.Spider):

    host = None
    custom_settings = {"ROBOTSTXT_OBEY": False}

    def start_requests(self):
        self.seen = set()
        url = (f"https://{self.host}/2026-2027-unofficial-catalog-preview"
               "/programs-of-study/list-of-programs")
        yield scrapy.Request(url, callback=self.parse_index)

    def parse_index(self, response):
        seen_links = set()
        for href in response.css("a::attr(href)").getall():
            href = href.split("#")[0].split("?")[0]
            if PROGRAM_HREF_RE.search(href) and href not in seen_links:
                seen_links.add(href)
                yield response.follow(href, callback=self.parse_program)

    def parse_program(self, response):
        academic_year = year_from_url(response.url)
        for tr in response.css("tr"):
            cells = {}
            for td in tr.css("td[data-th]"):
                key = (td.attrib.get("data-th") or "").strip()
                val = " ".join(t.strip() for t in td.css("::text").getall() if t.strip())
                cells[key] = val
            code = cells.get("Course Code", "").strip()
            if not CODE_RE.match(code) or code in self.seen:
                continue
            self.seen.add(code)
            title = cells.get("Course Title", "").strip()
            units = cells.get("Units", "").strip()
            m = TITLE_UNITS_RE.search(title)
            if m:
                title = TITLE_UNITS_RE.sub("", title).strip()
                if not units:
                    units = re.sub(r"\s*-\s*", "-", m.group(1))
            yield CourseItem(
                school_id=self.school_id,
                department_code=code.split()[0],
                course_code=code,
                course_title=title,
                credits=units,
                graduate_type="Undergraduate",
                term="",
                academic_year=academic_year,
                source_url=response.url,
            )
        # course-description blocks: "<h3>ACCT 499 Experimental Offering in
        # Accounting</h3>". Work-experience / experimental courses (198/298/
        # 299/498/499) appear ONLY here, never in the requirement tables.
        for h3 in response.css("h3::text").getall():
            m = H3_COURSE_RE.match(h3.strip())
            if not m:
                continue
            code = f"{m.group(1)} {m.group(2)}"
            if code in self.seen:
                continue
            self.seen.add(code)
            yield CourseItem(
                school_id=self.school_id,
                department_code=m.group(1),
                course_code=code,
                course_title=m.group(3).strip(),
                credits="",
                graduate_type="Undergraduate",
                term="",
                academic_year=academic_year,
                source_url=response.url,
            )

class AmericanRiverSpider(LosRiosSpider):
    name = "american_river"
    school_id = "2995968"
    slug = "american_river_college__2995968__cc"
    host = "arc.losrios.edu"
    allowed_domains = ["arc.losrios.edu"]

class FolsomLakeSpider(LosRiosSpider):
    name = "folsom_lake"
    school_id = "2996053"
    slug = "folsom_lake_college__2996053__cc"
    host = "flc.losrios.edu"
    allowed_domains = ["flc.losrios.edu"]

class SacramentoCitySpider(LosRiosSpider):
    name = "sacramento_city"
    school_id = "2996026"
    slug = "sacramento_city_college__2996026__cc"
    host = "scc.losrios.edu"
    allowed_domains = ["scc.losrios.edu"]


class CosumnesRiverSpider(LosRiosSpider):
    name = "cosumnes_river"
    school_id = "2995983"
    slug = "cosumnes_river_college__2995983__cc"
    host = "crc.losrios.edu"
    allowed_domains = ["crc.losrios.edu"]
