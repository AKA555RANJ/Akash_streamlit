# Course Catalog Scrape Notes

Source: `Catalog-Data` sheet. In scope = `2026-2027 Catalog Available?` (col I) = TRUE
and `Type of Catalog` (col L) = `Web`. Each school scraped from its
`Catalog URL For AY2026-2027` (col K).

## academic_year policy
- `academic_year` is scraped from the page when the catalog shows it.
- If the page shows no explicit 2026-2027, `academic_year` is left blank (never
  hard-coded); course data is still scraped because col I = Yes and we crawl the
  col K AY2026-2027 URL. Such schools are flagged below as "year not on page".

## Status

| school_id | school | platform | status | rows | year on page | note |
|---|---|---|---|---|---|---|
| 3009619 | Southern Connecticut State University | Web View Rows | done | 2023 | yes (2026-2027) | UG+grad; term filtered to 2026-2027 + not-yet-offered |
| 3007266 | University of Northern Colorado | SmartCatalogIQ | done | 3333 | yes (2026-2027) | UG+grad subject pages; credits inline |
| 3035086 | Nicholls State University | Web View Rows | done | 1561 | yes (2026-2027) | 91 subject pages; credits = first of C-L-L triple; 40 blank credits (no triple) |
| 3091104 | Rhodes College | Web View Rows | done | 1420 | NO | year not on page (see note below); index + per-course detail pages for credits; term not exposed; site antibot rate-limits detail pages |
| 3050281 | Metropolitan CC-Kansas City | eLumen (SPA) | done | 939 | yes (2026-2027) | reverse-engineered eLumen JSON API (api-prod.elumenapp.com): courses -> departments -> course detail; credits inline |
| 3037159 | Williams College | class schedule (SPA) | done | 1378 | yes (2026-2027) | FlareSolverr-rendered /list/; section listing deduped to courses; credits NOT in listing (left blank); also has a PDF catalog |
| 2995726 | Palomar College | PDF (CurriQunet web unreachable) | done | 932 | yes (2026-2027) | web catalog (CurriQunet) network-unreachable; scraped the 2026-2027 PDF instead (pdf_extractors/palomar_pdf.py, column-aware); code/title/credits |
| 3037211 | University of Massachusetts-Boston | Web View Rows | done | 1569 | NO | UG+grad; 2026 Fall (col K); subjects -> listing -> course_info detail (credits in span.class-div-info); browser UA needed (default 403); year not on page |
| 2990776 | Mesa Community College | Coursedog (SPA JSON API) | done | 6149 | yes (2026-2027) | Maricopa district Coursedog; catalogId RQzc6b76uitYyaXJt27C, offerNumber=4; see Maricopa note below |
| 2990782 | Paradise Valley Community College | Coursedog (SPA JSON API) | done | 6149 | yes (2026-2027) | same Maricopa tenant; catalogId HirEuyo6daAN3xmWWf45, offerNumber=9 |
| 2990779 | Scottsdale Community College | Coursedog (SPA JSON API) | done | 6149 | yes (2026-2027) | RECOVERED (was UNDELIVERABLE); catalogId n1NpLQ9WGeg5jvC66ZRP, offerNumber=5 |
| 2995968 | American River College | Web View Rows (program tables) | done | 1579 | yes (2026-2027) | DERIVED: courses only in per-program requirement tables, deduped by code; no descriptions |
| 2996053 | Folsom Lake College | Web View Rows (program tables) | done | 525 | yes (2026-2027) | DERIVED: per-program tables, deduped; smallest Los Rios college |
| 2996026 | Sacramento City College | Web View Rows (program tables) | done | 1049 | yes (2026-2027) | DERIVED: per-program tables, deduped |
| 3023894 | University of Illinois Urbana-Champaign | CourseLeaf | done | 9452 | yes (2026-2027) | shared courseleaf_spider; index->subject |
| 3006182 | Loyola Marymount University | CourseLeaf | done | 4665 | yes (2026-2027) | modern detail-* span layout |
| 2996062 | California State University-San Bernardino | CourseLeaf | done | 4049 | NO | classic coursetitle/coursehours spans; year not on page |
| 2996065 | California State University-Dominguez Hills | CourseLeaf | done | 3035 | yes (2026-2027) | modern detail-* span layout |
| 2996060 | California State University-Bakersfield | CourseLeaf | done | 2461 | yes (2026-2027) | modern detail-* span layout |
| 3017973 | Columbus State University | CourseLeaf | done | 2349 | yes (2026-2027) | detail-coursehours lecture-lab-credit triple "(3-0-3)"->3 |
| 3020616 | University of Northern Iowa | CourseLeaf | done | 1919 | NO | free-text "CODE. Title — N hrs."; ~2% variable-credit blanks; year not on page |
| 2996015 | Moorpark College | CourseLeaf | done | 1106 | NO | VCCCD district catalog, /moorpark/ scope; modern detail-* layout; codes "ACCT M01" -> |ACCT/|M01; year not in URL |
| 3108870 | University of Washington-Seattle | static (crscat) | done | 15749 | NO | classic crscat: <a name><b>CODE NNN Title (credits)</b>; multi-word depts ("A A","ART H","C LIT"); 333 (~2%) variable/`*`-credit blanks; year not in URL |
| 3106023 | Emory & Henry College | Drupal (course-teaser) | done | 1074 | NO | /classes paginated ?page=0..N; course-teaser-badge/-title/-credits; 30 (~3%) blank credits; year not in URL |
| 3029130 | Ivy Tech Community College | acalog (catoid/navoid) | done | 2430 | yes (2026-2027) | listing-only per South College template; credits blank; academic_year from selected catalog option |
| 3088559 | Trident Technical College | acalog (catoid/navoid) | done | 1070 | yes (2026-2027) | listing-only; credits blank; year from catalog option |
| 2996069 | California State University-Long Beach | acalog (catoid/navoid) | done | 5346 | yes (2026-2027) | listing-only; credits blank; 61 pages; year from catalog option |
| 3061272 | Rowan College at Burlington County | Coursedog (SPA JSON API) | done | 801 | yes (2026-2027) | 2026-2027 catalog (YMcEJQ2ylMoKDthe71o7) NOT the live default; body derived from catalog object's coursesFilters; rows==API listLength |
| 3029187 | Indiana University-South Bend | IU iGPS (sisjee JSON API) | done | 1065 | NO | Fall 2026 term (strm 4268); term="Fall 2026"; gradtype from car; year not in URL |
| 3029189 | Indiana University-Northwest | IU iGPS (sisjee JSON API) | done | 801 | NO | inst IUNWA; same API |
| 3029186 | Indiana University-Kokomo | IU iGPS (sisjee JSON API) | done | 695 | NO | inst IUKOA |
| 3029190 | Indiana University-Southeast | IU iGPS (sisjee JSON API) | done | 831 | NO | inst IUSEA |
| 3029191 | Indiana University-East | IU iGPS (sisjee JSON API) | done | 638 | NO | inst IUEAA |
| 3029192 | Indiana University-Purdue Univ-Indianapolis | IU iGPS (sisjee JSON API) | done | 2737 | NO | inst IUINA |
| 3102815 | Rice University | Banner SWKSCAT (static HTML) | done | 6527 | yes (2026-2027) | full 2026-2027 catalog on one CATALIST page; td.cataCourse/cataTitle/credits; year from page title |

## Maricopa Coursedog note (Mesa, Paradise Valley, Scottsdale)
Maricopa CCD runs ONE Coursedog tenant (`maricopa_peoplesoft_direct`). Each college is a
separate catalog (distinct `catalogId`) selected by an `offerNumber` filter, served by a
public JSON API (`app.coursedog.com/api/v1/cm/<tenant>/courses/search/$filters`, POST, no
auth — gated on `Origin`/`Referer`). API reverse-engineered via Playwright network capture.
Because Maricopa uses **district-wide common course numbering**, all three colleges publish
an identical course bank (6149 rows; code/title/credits match exactly across colleges — the
institution differs: MCC04 / PVC09 / SCC05). The three CSVs therefore differ only by
`school_id` and `source_url`. `academic_year` = `2026-2027` parsed from the catalog
displayName ("26-27 <College> Catalog"). **Scope note:** HANDOFF s3 lists Coursedog as
EXCLUDED; these were scraped per explicit manager/user direction (corrected col K link).

## Los Rios note (American River, Folsom Lake, Sacramento City)
The "2026-2027 unofficial catalog preview" has NO standalone course-description listing and
no separate course catalog (the official home redirects to the preview). Courses appear only
inside per-program requirement tables (`Course Code | Course Title (units) | Units`). The
spider crawls every `list-of-programs/<program>` page and dedupes by course code. Result is
DERIVED and INCOMPLETE: only courses cited by some program's requirements, no descriptions,
credits = units (single value or range like `1-3`, taken from the Units cell or a trailing
`(N)`/`(1 - 4)` in the title), `graduate_type=Undergraduate`, `term` blank. Official catalog
expected ~Aug 2026.

## CourseLeaf batch (formerly excluded "AZ Sitemap") — `courseleaf_spider.py`
Per manager direction the platform-exclusion list was dropped; CourseLeaf catalogs are now
in scope. ONE shared spider (base `CourseLeafSpider` + per-school subclass) crawls the subject
index -> per-subject pages (single-page catalogs handled too), parsing `div.courseblock` across
the three CourseLeaf layouts: (1) modern theme `span.detail-code/detail-title/detail-hours[_html]
/detail-coursehours`; (2) classic `span.coursetitle` + `span.coursehours`; (3) free text in
`p.courseblocktitle`. Credits handle single ("3"), range ("1-3"), lecture-lab-credit triple
("(3-0-3)"->3), and keywords credit/unit/hour/hrs/cr. `academic_year`=2026-2027 only when that
string is on the page (else blank). Needs a browser UA. 7 done so far (paused at manager request):
UIUC, LMU, CSU San Bernardino, CSU Dominguez, CSU Bakersfield, Columbus State, Northern Iowa.

## Batch 2026-06-16b: 7 new schools (acalog + static + Drupal + Coursedog + CourseLeaf)
Scope note: acalog (`catoid=`/`navoid=`) was historically marked "skip", but the manager's
own schema template is an acalog school (`south_college__3091089__cc.csv` / `3091089.zip`
in ~/Downloads — South College catoid=8&navoid=413). So acalog IS in scope; that template
defines the exact acalog output (listing-only, credits blank, academic_year from the catalog
name). The old §11/§8 "skip catoid" lines are stale (superseded by the §8b exclusion-drop).

- **acalog** (`acalog_spider.py`, base `AcalogSpider` + Ivy Tech / Trident / CSULB): paginate
  `content.php?catoid=&navoid=&filter[cpage]=N` (URL-encoded `filter%5Bcpage%5D`), stop when a
  page yields 0 new courses. Parse each `a[href*="preview_course"][href*="coid="]` anchor text
  `CODE<nbsp>-<nbsp>Title` (or `CODE Title` for South) -> code+title. credits BLANK (listing
  page shows none; matches manager template), graduate_type/term BLANK. academic_year from the
  selected catalog `<option>` ("2026-2027 Catalog" -> 2026-2027; South was "2026-2028").
  source_url = base navoid URL (no cpage); HTML backup is per-page (1 gz per cpage). Backup
  gz-file count == pagination max (Ivy 25, Trident 11, CSULB 61) = completeness check passed.
- **UW-Seattle** (`uw_seattle_spider.py`): index `/students/crscat/` -> relative `<subj>.html`
  pages (deduped, skip glossary/search). UW HTML is invalid (`<a name><p><b>...`), so match
  course headers by regex over every `<b>` text: `DEPT NNN Title (credits)`. DEPT may contain
  spaces ("A A","ART H","C LIT","B ECON"); number is 3 digits. credits = last parenthetical
  ("(5)","(1-5)","(2, max. 4)" -> first number/range; "(*, max. N)" -> blank/N). year not in URL.
- **Emory & Henry** (`emory_henry_spider.py`): Drupal `course-teaser` view, server-rendered,
  paginated `/classes?page=0..N` (50/page). Per row: `a.course-teaser-badge` (code),
  `h2.course-teaser-title a` (title), `div.course-teaser-credits span.credits` (credits). Stop
  when a page yields no new rows. year not in URL.
- **Rowan @ Burlington (Coursedog)**: the live site (`rcbc.catalog.prod.coursedog.com`)
  DEFAULTS to the 2025-2026 catalog; the 2026-2027 catalog (`YMcEJQ2ylMoKDthe71o7`) is NOT
  loadable in the live SPA, so its curated course filter can't be captured by network sniffing.
  Instead the spider GETs `/ca/<tenant>/catalogs/<catalogId>` and builds the search body from
  the catalog object's own `coursesFilters` (147 filters), with effective date = catalog
  `effectiveStartDate` (2026-07-01) and academic_year from `displayName`. CoursedogSpider now
  derives body/effective/academic_year from the catalog object whenever a subclass leaves
  `body = None` (backward-compatible; existing subclasses set `body` so are unaffected).
  rows (801) == API listLength = complete.
- **Angelina College (3094051) — DROPPED**: Coursedog tenant `angelina_jenzabar`, but the
  course-search API returns `listLength: 0` for every catalog (incl. the live default page) —
  the Coursedog course bank is empty; courses are not served via the cm/courses API.
  UNDELIVERABLE via the clean Coursedog path. Replaced with CSULB (acalog).

## Batch 2026-06-17: 6 Indiana University campuses + Rice (IU iGPS + Banner SWKSCAT)
SELECTION RULE (manager-corrected): a candidate must be I=TRUE, L=Web, NOT already scraped,
**col O (Spider Status) empty AND col R (Scraper Name) NOT Admin/Akash** (avoid claimed work).
After applying this to `Course Catalog - Rational Solver-14.xlsx`, every clean/easy platform
(CourseLeaf, acalog, populated Coursedog, static) was already scraped or owned by Admin/Akash;
the only unassigned in-scope rows were dynamic SPAs / blocked sites. The IU sisjee app (6
campuses) + Rice were crackable cleanly.

- **IU iGPS** (`iu_igps_spider.py`, 6 campuses): public JSON API at
  `sisjee.iu.edu/sisigps-prd/web/igps/course/search/`. `GET terms.json?inst=<INST>` ->
  [{descr,strm}]; `POST courses.json` body `{"inst":<INST>,"strm":<strm>,"filters":{},"from":N}`
  -> {count, courses:[{subject,catalogNumber,title,minCredits,maxCredits,car,...}]} (50/page,
  paginate `from`). Term-scoped class search that returns COURSE-level rows (sections collapsed);
  scrape Fall 2026 (strm 4268) = entry term of AY2026-2027. inst codes: IUSBA/IUNWA/IUKOA/IUSEA/
  IUEAA/IUINA. dept=subject (e.g. AHSC-A), credits=min/max, graduate_type from car (UGRD/GRAD),
  term="Fall 2026", academic_year BLANK (term not URL, per policy). Titles are ALL-CAPS at source
  (kept as-is). Reverse-engineered by driving the Angular form via Playwright (campus->term->search).
- **Rice** (`rice_spider.py`): Banner SWKSCAT static HTML. ONE page
  `courses.rice.edu/admweb/!SWKSCAT.cat?p_action=CATALIST` lists the entire 2026-2027 catalog
  (6527 courses). Per `<tr>`: `td.cataCourse a` (code "AAAS 110"), `td.cataTitle` (ALL-CAPS title),
  `td.credits`. academic_year=2026-2027 from page <title> "Course Catalog - 2026-2027" (authoritative
  catalog year, same precedent as acalog catalog-name). graduate_type/term blank.

## Notes for "year not on page" schools
Standard note: "2026-2027 not explicitly shown on the catalog page; scraped whatever
was available at the Catalog URL For AY2026-2027 (col K), which is flagged 2026-2027
Catalog Available = Yes (col I)."

- **Rhodes College (3091104)** — academic_year left blank: no 2026-2027 string appears
  on the courses index or the per-course detail pages. Scraped from col K
  (`https://catalog.rhodes.edu/courses`), col I = Yes. Term also not exposed.
- **University of Massachusetts-Boston (3037211)** — academic_year left blank: the pages
  expose only the term ("2026 Fall", the col K term) with no 2026-2027 string. Scraped
  from col K, col I = Yes. `term` = `2026 Fall`.

## Excluded after FlareSolverr inspection (actually CourseLeaf)
These were labeled "Web View Rows" but the rendered page is CourseLeaf -> out of scope:
- CSU Chico (2996064) — courseleaf (was hidden behind Cloudflare)
- RIT (3067286) — courseleaf (served 2025-2026)

## Web catalog UNREACHABLE from this environment (network-level block)
CurriQunet (curriqunet.com) and Maricopa (curriculum.maricopa.edu) refuse/time out for
every tool here (curl=000, FlareSolverr, headless+headful Playwright). PDF fallback used
where a 2026-2027 PDF exists:
- Palomar (2995726) — DONE via 2026-2027 PDF (web is CurriQunet, blocked).
- Chaffey (2995976) — NO 2026-2027 PDF published (catalog page lists PDFs only thru
  2025-2026; 2026-2027 is CurriQunet-only) -> UNDELIVERABLE from this environment.
- Riverside City (2996025) — NO 2026-2027 PDF (CurriQunet-only) -> UNDELIVERABLE here.
- ~~Scottsdale (2990779)~~ — **RECOVERED**: its 2026-2027 catalog is on the Maricopa
  Coursedog (`scottsdalecc.catalog.maricopa.edu`), which IS reachable (only the old
  `curriculum.maricopa.edu` URL was blocked). Done — see Maricopa Coursedog note above.
Chaffey & Riverside still need a different network/IP (where curriqunet.com resolves).

## Remaining target schools — ALL RESOLVED
- Mesa CC (2990776), Paradise Valley (2990782), Scottsdale (2990779): DONE via Maricopa
  Coursedog JSON API (the col K link for Mesa was corrected to the Coursedog catalog).
- UMass Boston (3037211): DONE — static multi-level catalog (courses.umb.edu).
- Los Rios (American River 2995968, Folsom Lake 2996053, Sacramento City 2996026): DONE
  via deduped program-table scrape (derived/incomplete — see Los Rios note above).
- Still UNDELIVERABLE here: Chaffey (2995976), Riverside (2996025) — CurriQunet network block.

## Tooling notes
- FlareSolverr (localhost:8191) used for Cloudflare/403 sites (Williams) and to unmask
  CSU Chico/RIT as CourseLeaf.
- Playwright (system Chrome via channel="chrome") used to capture SPA APIs; revealed
  the eLumen JSON API which the mcckc spider now calls directly.

## Batches 2026-06-19 → 06-21 (RS-15; see HANDOFF §8 for full per-school list)
Selection: I=TRUE, col R (Scraper Name) NOT Admin/Akash, col O empty, not AZ Sitemap, not in
data/. CHECK COL K for the real platform — col M (Sub Type) labels are unreliable.
- Banner 9 SSB (`banner_ssb_spider.py`): UC-Riverside, Yeshiva, Kutztown (mepCode). courseSearch
  catalog API. html.unescape titles; drop "----" placeholders (courseNumber has no digit).
- ASU-Downtown (`asu_spider.py`): public course microservice, Authorization "Bearer null".
- Columbia (`columbia_spider.py`): Directory of Classes; subject pages MIX subjects -> take subject
  code from the section link, not the page filename.
- Course-teaser / Clean Catalog (`modern_campus_spider.py`): NHTI, Northwest Nazarene, Full Sail,
  Oakwood (/classes), Craven (/courses). Same engine as Emory.
- Coursedog (`coursedog_spider.py`): Whitman, Eastern Arizona, Midland (UG+grad), Rowan.
  _credits FIX: use creditHours.value / numberOfCredits when min/max=0 (Anthology). Empty catalogs
  (skip): Angelina, Trocaire.
- Mid Michigan (`mid_michigan_spider.py`): accordion buttons "DEPT.NUM Title CR (lec-lab)".
- IU iGPS add: Bloomington (IUBLA). Rice: Banner SWKSCAT static.

## PDF scraping (probed all 34 in-scope PDFs 2026-06-21)
Column-aware pdfplumber: detect the 2-column gutter via the word x-gap (NOT page midpoint, which
splits codes like "HPE"+"458"); group words into visual lines; parse with a TIGHT regex (wordy
letter-led title + paren credits "(N units/cr)") to reject prereq lists / addresses / GPA examples.
SCRAPABLE (4): ENMU (`enmu_spider.py`, UG+grad, 1583), La Sierra (1410), Regent (2004),
Pacific Union (344) — `pdf_catalog_spider.py`. NOT SCRAPABLE (30): degree-plan/check-sheet/prereq
formatted (credits come out as page numbers/contact hours; codes scattered in requirement lists).
Examples: SIU, El Paso, SOWELA, MS Delta, Northeast, Solano, Crowder, Jackson, Moody, Pima ×3,
Fortis, Denver Nursing, Fox Valley, Ultimate Medical. Do not retry without per-PDF section logic.
