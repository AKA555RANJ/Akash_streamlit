import re
from urllib.parse import urlparse

import scrapy

from course_catalog_scrapy.items import CourseItem, year_from_url, year_from_page

# dept code: 1+ uppercase tokens that may contain '&' (A&S, T&L) and may be
# space-separated (MUS HIST), up to ~9 chars each, then the course number.
CODE_RE = re.compile(
    r"^([A-Z][A-Z&]{0,8}(?:\s[A-Z][A-Z&]{0,8})?)[\s\-]*(\d{2,4}[A-Z0-9]*)")
XLIST_RE = re.compile(r"^/\s*[A-Z]{2,6}\s*\d[\w]*\.?\s*")
DUAL_RE = re.compile(r"^/\s*\d{2,4}[A-Z]?\b\.?\s*")
HOURS_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)(?:\s*(?:to|through|-|–|—)\s*(\d+(?:\.\d+)?))?")
CRED_RE = re.compile(
    r"(\d+(?:\.\d+)?)(?:\s*(?:to|through|-|–|—)\s*(\d+(?:\.\d+)?))?"
    r"\s*(?:credits?|units?|hours?|hrs?|s\.h\.|cr\.?)\b", re.I)
TRAIL_CRED_RE = re.compile(
    r"(?i)[\s:·–—-]*\b(?:credits?|units?|hours?|hrs?|cr)\b[\s:.]*$")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

def _norm(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()

def _rng(m):
    return (m.group(1) + ("-" + m.group(2) if m.group(2) else "")) if m else ""

def _hours(text):
    t = text or ""
    triple = re.search(r"\b\d+(?:\.\d+)?-\d+(?:\.\d+)?-(\d+(?:\.\d+)?)\b", t)
    if triple:
        return triple.group(1)
    return _rng(HOURS_NUM_RE.search(t))

def _code_dept(code_txt):
    m = CODE_RE.match(code_txt)
    if m:
        return m.group(1), _norm(m.group(1) + " " + m.group(2))
    parts = code_txt.split()
    return (parts[0] if parts and parts[0].isalpha() else ""), code_txt


def parse_courseblock(b):
    code_txt = _norm(" ".join(b.css("span.detail-code ::text").getall()))
    if code_txt:
        title = re.sub(r"^[\s.:·–—-]+", "", _norm(" ".join(b.css("span.detail-title ::text").getall())))
        hours = _norm(" ".join(b.css('span[class*="detail-"][class*="hours"] ::text').getall()))
        dept, code = _code_dept(code_txt)
        credits = _hours(hours)
        if not credits:                              # credits as free text in courseblockextra
            cm = CRED_RE.search(_norm(" ".join(b.css("div.courseblockextra ::text, p.courseblockextra ::text").getall())))
            credits = _rng(cm) if cm else ""
        return dept, code, title, credits

    cbc = _norm(" ".join(b.css("span.courseblockcode ::text").getall()))
    if cbc:
        title = re.sub(r"^[\s.:·–—-]+", "", _norm(" ".join(
            b.css("span.courseblock__title ::text").getall())))
        if not title:                                # title sits in p.courseblocktitle after the code span
            full = _norm(" ".join(b.css(
                "p.courseblocktitle ::text, h3.courseblocktitle ::text").getall()))
            mc = CODE_RE.match(full)
            title = re.sub(r"^[\s.:·–—-]+", "", full[mc.end():]) if mc else full
        hours = _norm(" ".join(b.css(
            'span[class*="courseblock"][class*="hours"] ::text, '
            'span[class*="detail-"][class*="hours"] ::text').getall()))
        dept, code = _code_dept(cbc)
        return dept, code, title, _hours(hours)

    ct = _norm(" ".join(b.css("span.coursetitle ::text").getall()))
    if ct:
        ch = _norm(" ".join(b.css(
            "span.coursehours ::text, span.courseblockhours ::text, "
            "span.courseblockcredits ::text").getall()))
        m = CODE_RE.match(ct)
        dept = m.group(1) if m else ""
        code = _norm(m.group(1) + " " + m.group(2)) if m else ct
        title = DUAL_RE.sub("", re.sub(r"^[\s.:·–—-]+", "", _norm(ct[m.end():]))).rstrip(" .") if m else ct
        return dept, code, title, _hours(ch)

    full = _norm("".join(b.css("p.courseblocktitle ::text, h3.courseblocktitle ::text").getall()))
    m = CODE_RE.match(full)
    if not m:
        return "", "", "", ""
    dept, code = m.group(1), _norm(m.group(1) + " " + m.group(2))
    rest = XLIST_RE.sub("", full[m.end():].lstrip(" .:–—-·")).lstrip(" .:–—-·")
    rest = DUAL_RE.sub("", rest).lstrip(" .:–—-·")
    if "|" in rest:                                  # pipe-delimited: TITLE | N hours
        segs = [s.strip() for s in rest.split("|") if s.strip()]
        title = segs[0] if segs else rest
        credits = _hours(segs[-1]) if len(segs) > 1 and re.search(r"\d", segs[-1]) else ""
    else:
        cm = CRED_RE.search(rest)
        credits = _rng(cm) if cm else ""
        title = rest[:cm.start()] if cm else rest
    title = TRAIL_CRED_RE.sub("", title).strip(" .:–—-·")
    if not credits:                                  # credits in a sibling <p class="courseblock">
        cm2 = CRED_RE.search(_norm(" ".join(b.css("p.courseblock ::text").getall())))
        credits = _rng(cm2) if cm2 else ""
    return dept, code, title, credits

class CourseLeafSpider(scrapy.Spider):

    custom_settings = {"ROBOTSTXT_OBEY": False, "DOWNLOAD_DELAY": 0.25,
                       "CONCURRENT_REQUESTS": 6, "USER_AGENT": UA}
    start_pages = []

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.seen = set()

    def start_requests(self):
        for url, gt in self.start_pages:
            yield scrapy.Request(url, callback=self.parse_index,
                                 cb_kwargs={"index_url": url, "graduate_type": gt})

    def parse_index(self, response, index_url, graduate_type):
        if response.css("div.courseblock"):
            yield from self._emit(response, graduate_type)
            return
        idx = urlparse(index_url)
        base = idx.path
        if not base.endswith("/"):
            base += "/"
        seen = set()
        for href in response.css("a::attr(href)").getall():
            h = href.split("#")[0].split("?")[0]
            path = urlparse(response.urljoin(h)).path
            if path.startswith(base) and path != base:
                rest = path[len(base):].strip("/")
                if rest and "/" not in rest and "." not in rest and rest not in seen:
                    seen.add(rest)
                    # follow subject pages on the index's own host (CourseLeaf
                    # indexes sometimes link a subject to a sibling catalog host)
                    yield response.follow(f"{idx.scheme}://{idx.netloc}{path}",
                                          callback=self._emit_cb,
                                          cb_kwargs={"graduate_type": graduate_type})

    def _emit_cb(self, response, graduate_type):
        yield from self._emit(response, graduate_type)

    def _emit(self, response, graduate_type):
        academic_year = year_from_page(response.text) or year_from_url(response.url)
        for b in response.css("div.courseblock"):
            dept, code, title, credits = parse_courseblock(b)
            if not code or len(title.strip()) < 2 or code in self.seen or not re.search(r"\d", code):
                continue
            self.seen.add(code)
            yield CourseItem(
                school_id=self.school_id, department_code=dept, course_code=code,
                course_title=title, credits=credits, graduate_type=graduate_type,
                term="", academic_year=academic_year, source_url=response.url,
            )

class UIUCSpider(CourseLeafSpider):
    name = "uiuc"
    school_id = "3023894"
    slug = "university_of_illinois_urbana-champaign__3023894__cc"
    allowed_domains = ["catalog.illinois.edu"]
    start_pages = [("https://catalog.illinois.edu/courses-of-instruction/", "")]

class CSUSanBernardinoSpider(CourseLeafSpider):
    name = "csu_san_bernardino"
    school_id = "2996062"
    slug = "california_state_university-san_bernardino__2996062__cc"
    allowed_domains = ["catalog.csusb.edu"]
    start_pages = [("https://catalog.csusb.edu/coursesaz/", "")]

class CSUBakersfieldSpider(CourseLeafSpider):
    name = "csu_bakersfield"
    school_id = "2996060"
    slug = "california_state_university-bakersfield__2996060__cc"
    allowed_domains = ["catalog.csub.edu"]
    start_pages = [("https://catalog.csub.edu/course-descriptions/", "")]

class NorthernIowaSpider(CourseLeafSpider):
    name = "northern_iowa"
    school_id = "3020616"
    slug = "university_of_northern_iowa__3020616__cc"
    allowed_domains = ["catalog.uni.edu"]
    start_pages = [("https://catalog.uni.edu/courses/", "")]

class LMUSpider(CourseLeafSpider):
    name = "lmu"
    school_id = "3006182"
    slug = "loyola_marymount_university__3006182__cc"
    allowed_domains = ["bulletin.lmu.edu"]
    start_pages = [("https://bulletin.lmu.edu/course-descriptions/", "")]

class ColumbusStateSpider(CourseLeafSpider):
    name = "columbus_state"
    school_id = "3017973"
    slug = "columbus_state_university__3017973__cc"
    allowed_domains = ["catalog.columbusstate.edu"]
    start_pages = [("https://catalog.columbusstate.edu/course-descriptions/", "")]

class CSUDominguezSpider(CourseLeafSpider):
    name = "csu_dominguez"
    school_id = "2996065"
    slug = "california_state_university-dominguez_hills__2996065__cc"
    allowed_domains = ["catalog.csudh.edu"]
    start_pages = [("https://catalog.csudh.edu/courses/", "")]


class StLouisCCSpider(CourseLeafSpider):
    name = "st_louis_cc"
    school_id = "3050288"
    slug = "saint_louis_community_college__3050288__cc"
    allowed_domains = ["catalog.stlcc.edu"]
    start_pages = [("https://catalog.stlcc.edu/course-descriptions/courses/", "")]


class CSUChicoSpider(CourseLeafSpider):
    name = "csu_chico"
    school_id = "2996064"
    slug = "california_state_university-chico__2996064__cc"
    allowed_domains = ["catalog.csuchico.edu"]
    start_pages = [("https://catalog.csuchico.edu/courses/", "")]


class UCDavisSpider(CourseLeafSpider):
    name = "uc_davis"
    school_id = "2996091"
    slug = "university_of_california-davis__2996091__cc"
    allowed_domains = ["catalog.ucdavis.edu"]
    start_pages = [("https://catalog.ucdavis.edu/courses-subject-code/", "")]


class PaceSpider(CourseLeafSpider):
    name = "pace"
    school_id = "3067276"
    slug = "pace_university__3067276__cc"
    allowed_domains = ["catalog.pace.edu"]
    start_pages = [
        ("https://catalog.pace.edu/undergraduate/courses-a-z/", "Undergraduate"),
        ("https://catalog.pace.edu/graduate/courses-a-z/", "Graduate"),
    ]


class CUDenverSpider(CourseLeafSpider):
    name = "cu_denver"
    school_id = "3007318"
    slug = "university_of_colorado_denver__3007318__cc"
    allowed_domains = ["catalog.ucdenver.edu"]
    start_pages = [
        ("https://catalog.ucdenver.edu/cu-denver/undergraduate/courses-a-z/", "Undergraduate"),
        ("https://catalog.ucdenver.edu/cu-denver/graduate/courses-a-z/", "Graduate"),
    ]


class TexasSouthernSpider(CourseLeafSpider):
    name = "texas_southern"
    school_id = "3102818"
    slug = "texas_southern_university__3102818__cc"
    allowed_domains = ["catalog.tsu.edu"]
    start_pages = [
        ("https://catalog.tsu.edu/undergraduate/course-descriptions/", "Undergraduate"),
        ("https://catalog.tsu.edu/graduate/course-descriptions/", "Graduate"),
    ]


class USCColumbiaSpider(CourseLeafSpider):
    name = "usc_columbia"
    school_id = "3088564"
    slug = "university_of_south_carolina-columbia__3088564__cc"
    allowed_domains = ["academicbulletins.sc.edu"]
    start_pages = [
        ("https://academicbulletins.sc.edu/undergraduate/course-descriptions/", "Undergraduate"),
        ("https://academicbulletins.sc.edu/graduate/course-descriptions/", "Graduate"),
    ]


class GreenvilleTechSpider(CourseLeafSpider):
    name = "greenville_tech"
    school_id = "3088551"
    slug = "greenville_technical_college__3088551__cc"
    allowed_domains = ["catalog.gvltec.edu"]
    start_pages = [("https://catalog.gvltec.edu/course-descriptions/", "")]


class TAMUCorpusChristiSpider(CourseLeafSpider):
    name = "tamu_corpus_christi"
    school_id = "3094270"
    slug = "texas_a_and_m_university-corpus_christi__3094270__cc"
    allowed_domains = ["catalog.tamucc.edu"]
    start_pages = [
        ("https://catalog.tamucc.edu/undergraduate/courses-az/", "Undergraduate"),
        ("https://catalog.tamucc.edu/graduate/courses-az/", "Graduate"),
    ]


class FrederickCCSpider(CourseLeafSpider):
    name = "frederick_cc"
    school_id = "3039667"
    slug = "frederick_community_college__3039667__cc"
    allowed_domains = ["frederick-public.courseleaf.com"]
    start_pages = [("https://frederick-public.courseleaf.com/credit-course-descriptions/", "")]


class CalPolySpider(CourseLeafSpider):
    name = "cal_poly"
    school_id = "2996059"
    slug = "california_polytechnic_state_university__2996059__cc"
    allowed_domains = ["catalog.calpoly.edu"]
    start_pages = [("https://catalog.calpoly.edu/courses/", "")]


class CuyahogaSpider(CourseLeafSpider):
    name = "cuyahoga"
    school_id = "3073727"
    slug = "cuyahoga_community_college_district__3073727__cc"
    allowed_domains = ["catalog.tri-c.edu"]
    start_pages = [("https://catalog.tri-c.edu/course-descriptions/", "")]


class DePaulSpider(CourseLeafSpider):
    name = "depaul"
    school_id = "3027769"
    slug = "depaul_university__3027769__cc"
    allowed_domains = ["catalog.depaul.edu"]
    start_pages = [("https://catalog.depaul.edu/course-descriptions/", "")]


class StarkStateSpider(CourseLeafSpider):
    name = "stark_state"
    school_id = "3073939"
    slug = "stark_state_college__3073939__cc"
    allowed_domains = ["catalog.starkstate.edu"]
    start_pages = [("https://catalog.starkstate.edu/course-descriptions/", "")]


class MoorparkSpider(CourseLeafSpider):
    name = "moorpark"
    school_id = "2996015"
    slug = "moorpark_college__2996015__cc"
    allowed_domains = ["catalog.vcccd.edu"]
    start_pages = [("https://catalog.vcccd.edu/moorpark/programs-courses/", "")]


class UTEPSpider(CourseLeafSpider):
    name = "utep"
    school_id = "3094301"
    slug = "the_university_of_texas_at_el_paso__3094301__cc"
    allowed_domains = ["catalog.utep.edu"]
    start_pages = [
        ("https://catalog.utep.edu/undergrad/course-descriptions/", "Undergraduate"),
        ("https://catalog.utep.edu/grad/course-descriptions/", "Graduate"),
    ]


class QuinnipiacSpider(CourseLeafSpider):
    name = "quinnipiac"
    school_id = "3009579"
    slug = "quinnipiac_university__3009579__cc"
    allowed_domains = ["catalog.qu.edu"]
    start_pages = [
        ("https://catalog.qu.edu/courses-undergraduate/", "Undergraduate"),
        ("https://catalog.qu.edu/courses-graduate/", "Graduate"),
    ]


class UConnSpider(CourseLeafSpider):
    name = "uconn"
    school_id = "3009591"
    slug = "university_of_connecticut-stamford__3009591__cc"
    allowed_domains = ["catalog.uconn.edu"]
    start_pages = [
        ("https://catalog.uconn.edu/undergraduate/courses/", "Undergraduate"),
        ("https://catalog.uconn.edu/graduate/courses/", "Graduate"),
    ]


class UtahTechSpider(CourseLeafSpider):
    name = "utah_tech"
    school_id = "3104284"
    slug = "dixie_state_university__3104284__cc"
    allowed_domains = ["catalog.utahtech.edu"]
    start_pages = [("https://catalog.utahtech.edu/courses/", "")]


class MiraCostaSpider(CourseLeafSpider):
    name = "miracosta"
    school_id = "2995709"
    slug = "miracosta_college__2995709__cc"
    allowed_domains = ["catalog.miracosta.edu"]
    start_pages = [("https://catalog.miracosta.edu/disciplines/", "")]


class UConnWaterburySpider(CourseLeafSpider):
    name = "uconn_waterbury"
    school_id = "3009589"
    slug = "university_of_connecticut-waterbury_campus__3009589__cc"
    allowed_domains = ["catalog.uconn.edu"]
    start_pages = [
        ("https://catalog.uconn.edu/undergraduate/courses/", "Undergraduate"),
        ("https://catalog.uconn.edu/graduate/courses/", "Graduate"),
    ]


class LewisClarkSpider(CourseLeafSpider):
    name = "lewis_clark"
    school_id = "3080121"
    slug = "lewis_&_clark_college__3080121__cc"
    allowed_domains = ["docs.lclark.edu"]
    start_pages = [
        ("https://docs.lclark.edu/undergraduate/", "Undergraduate"),
        ("https://docs.lclark.edu/graduate/", "Graduate"),
    ]
