import re

import scrapy

from course_catalog_scrapy.items import CourseItem, year_from_page

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CODE_RE = re.compile(r"^([A-Z]{2,6})[\s\-]*\d")


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


class CourseTeaserSpider(scrapy.Spider):
    # Modern Campus / Drupal "course-teaser" catalogs: paginated /classes?page=N
    # (50/page), each row a.course-teaser-badge (code) + h2.course-teaser-title +
    # div.course-teaser-credits.
    custom_settings = {"ROBOTSTXT_OBEY": False, "DOWNLOAD_DELAY": 0.25,
                       "CONCURRENT_REQUESTS": 4, "USER_AGENT": UA}
    base = None
    classes_path = "/classes"
    max_pages = 80
    academic_year = ""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.seen = set()

    def start_requests(self):
        # the /classes pages carry no year; the catalog home <title> does
        # (e.g. "College Catalog 2026-2027") -> read it first.
        yield scrapy.Request(self.base + "/", callback=self.parse_home,
                             dont_filter=True)

    def parse_home(self, response):
        self.academic_year = year_from_page(response.text)
        yield scrapy.Request(f"{self.base}{self.classes_path}?page=0",
                             callback=self.parse, cb_kwargs={"page": 0})

    def parse(self, response, page):
        rows = response.css("div.views-row")
        new = 0
        for row in rows:
            code = _norm(" ".join(row.css("a.course-teaser-badge ::text").getall()))
            title = _norm(" ".join(row.css("h2.course-teaser-title ::text").getall()))
            m = CODE_RE.match(code)
            if not m or not title or code in self.seen:
                continue
            self.seen.add(code)
            new += 1
            yield CourseItem(
                school_id=self.school_id, department_code=m.group(1),
                course_code=code, course_title=title,
                graduate_type="", term="", academic_year=self.academic_year,
                source_url=f"{self.base}{self.classes_path}",
            )
        if rows and new and page < self.max_pages:
            yield scrapy.Request(f"{self.base}{self.classes_path}?page={page + 1}",
                                 callback=self.parse, cb_kwargs={"page": page + 1})


class NHTISpider(CourseTeaserSpider):
    name = "nhti"
    school_id = "3059957"
    slug = "nhti-concord's_community_college__3059957__cc"
    allowed_domains = ["catalog.nhti.edu"]
    base = "https://catalog.nhti.edu"


class NorthwestNazareneSpider(CourseTeaserSpider):
    name = "northwest_nazarene"
    school_id = "3022108"
    slug = "northwest_nazarene_university__3022108__cc"
    allowed_domains = ["catalog.nnu.edu"]
    base = "https://catalog.nnu.edu"


class FullSailSpider(CourseTeaserSpider):
    name = "full_sail"
    school_id = "3012531"
    slug = "full_sail_university__3012531__cc"
    allowed_domains = ["catalog.fullsail.edu"]
    base = "https://catalog.fullsail.edu"


class OakwoodSpider(CourseTeaserSpider):
    name = "oakwood"
    school_id = "2987568"
    slug = "oakwood_university__2987568__cc"
    allowed_domains = ["catalog.oakwood.edu"]
    base = "https://catalog.oakwood.edu"


class CravenSpider(CourseTeaserSpider):
    name = "craven"
    school_id = "3055614"
    slug = "craven_community_college__3055614__cc"
    allowed_domains = ["catalog.cravencc.edu"]
    base = "https://catalog.cravencc.edu"
    classes_path = "/courses"


class CourseTeaserTableSpider(CourseTeaserSpider):
    # Clean Catalog "course-teaser-table" layout: rows under
    # div.course-teaser-table-label a (code), h2.course-teaser-table-title (title),
    # div.course-teaser-table-credits span.credits (credits). Supports several
    # (base, path, graduate_type) sources merged into one CSV.
    sources = []

    def start_requests(self):
        yield scrapy.Request(self.sources[0][0] + "/", callback=self.parse_home,
                             dont_filter=True)

    def parse_home(self, response):
        self.academic_year = year_from_page(response.text)
        for base, path, gt in self.sources:
            yield scrapy.Request(f"{base}{path}?page=0", callback=self.parse,
                                 cb_kwargs={"page": 0, "base": base, "path": path,
                                            "gt": gt})

    def parse(self, response, page, base=None, path=None, gt=""):
        rows = response.css("div.views-row")
        new = 0
        for row in rows:
            code = _norm(" ".join(
                row.css("div.course-teaser-table-label a ::text").getall()))
            title = _norm(" ".join(
                row.css("h2.course-teaser-table-title a span.field__item ::text").getall()))
            m = CODE_RE.match(code)
            if not m or not title or code in self.seen:
                continue
            self.seen.add(code)
            new += 1
            yield CourseItem(
                school_id=self.school_id, department_code=m.group(1),
                course_code=code, course_title=title,
                graduate_type=gt, term="", academic_year=self.academic_year,
                source_url=f"{base}{path}",
            )
        if rows and new and page < self.max_pages:
            yield scrapy.Request(f"{base}{path}?page={page + 1}", callback=self.parse,
                                 cb_kwargs={"page": page + 1, "base": base,
                                            "path": path, "gt": gt})


class SunyCorningSpider(CourseTeaserSpider):
    name = "suny_corning"
    school_id = "3067459"
    slug = "suny_corning_community_college__3067459__cc"
    allowed_domains = ["corning.cleancatalog.net"]
    base = "https://corning.cleancatalog.net"
    classes_path = "/classes"


class SwauSpider(CourseTeaserSpider):
    # Clean Catalog bootstrap-column layout: code in the first <a><span> of the row,
    # title in span.field--name-field-item. UG + grad subdomains merged.
    name = "swau"
    school_id = "3094146"
    slug = "southwestern_adventist_university__3094146__cc"
    allowed_domains = ["swau.edu"]
    sources = [("https://catalog.swau.edu", "/classes", "Undergraduate"),
               ("https://grad-catalog.swau.edu", "/classes", "Graduate")]

    def start_requests(self):
        yield scrapy.Request(self.sources[0][0] + "/", callback=self.parse_home,
                             dont_filter=True)

    def parse_home(self, response):
        self.academic_year = year_from_page(response.text)
        for base, path, gt in self.sources:
            yield scrapy.Request(f"{base}{path}?page=0", callback=self.parse,
                                 cb_kwargs={"page": 0, "base": base, "path": path,
                                            "gt": gt})

    def parse(self, response, page, base=None, path=None, gt=""):
        rows = response.css("div.views-row")
        new = 0
        for row in rows:
            spans = [_norm(t) for t in row.css("a span::text").getall()]
            code = next((s for s in spans if CODE_RE.match(s)), "")
            title = _norm(" ".join(
                row.css("span.field--name-field-item::text").getall()))
            m = CODE_RE.match(code)
            if not m or not title or code in self.seen:
                continue
            self.seen.add(code)
            new += 1
            yield CourseItem(
                school_id=self.school_id, department_code=m.group(1),
                course_code=code, course_title=title,
                graduate_type=gt, term="", academic_year=self.academic_year,
                source_url=f"{base}{path}",
            )
        if rows and new and page < self.max_pages:
            yield scrapy.Request(f"{base}{path}?page={page + 1}", callback=self.parse,
                                 cb_kwargs={"page": page + 1, "base": base,
                                            "path": path, "gt": gt})


class AlfredSpider(CourseTeaserTableSpider):
    name = "alfred"
    school_id = "3067170"
    slug = "alfred_university__3067170__cc"
    allowed_domains = ["alfred.edu"]
    sources = [
        ("https://undergraduatecatalog.alfred.edu", "/undergraduate-courses",
         "Undergraduate"),
        ("https://graduatecatalog.alfred.edu", "/graduate-courses", "Graduate"),
    ]


class VillanovaSpider(CourseTeaserTableSpider):
    name = "villanova"
    school_id = "3083491"
    slug = "villanova_university__3083491__cc"
    allowed_domains = ["live-villanova-catalog.cleancatalog.io"]
    sources = [("https://live-villanova-catalog.cleancatalog.io", "/classes", "")]
