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

## Batch 2026-06-21b (bundle-6): RS-15 rows 535-594 scan — 4 schools, 8,613 rows
Scanned Catalog-Data rows 535-594 (all already J-N filled). Scrapable in-scope candidates = the
I=TRUE rows on a platform we can do; all four below have col O (Spider Status) and R (Scraper Name)
empty (unowned). Trusted col K for the real platform.
- **Greenfield CC (3037197)** — Coursedog (tenant gcc_banner_sql, catalog Tq3vInBCVkfzBa5krhiu);
  336; academic_year 2026-2027 (displayName "2026-2027 Catalog"); body/effective derived from the
  catalog's coursesFilters (== the live SPA's filter; verified count match).
- **UNT Dallas (3094311)** — Coursedog (tenant untdallas_peoplesoft), TWO catalogs in one CSV:
  UG (iy0jnKLU4sRy9tAZl2Xg, 1204, graduate_type Undergraduate) + Grad (fXSWetEuBzJ3jRXSr0Tv, 346,
  Graduate) = 1550; per-catalog origin so UG rows -> undergrad.catalog.untdallas.edu, grad rows ->
  graduate.catalog.untdallas.edu; academic_year 2026-2027.
- **South Mountain CC (2990780)** — Maricopa district Coursedog (6th college; catalog
  xl2hM3DML8ekjw7BStjW, offerNumber 7 = inst SMC07); 6131 (identical bank to Rio Salado — Maricopa
  common course numbering); academic_year blank (year_from_url(origin), consistent with Mesa/PV/
  Scottsdale/Rio Salado); graduate_type Undergraduate.
- **Wilkes CC (3055652)** — PDF (L=PDF, CATALOG_2026_2027-2.pdf). WilkesSpider (pdf_catalog_spider.py):
  NC-community-college 2-column Course-Descriptions section. Geometric left/right half-crop (the
  shared gutter+top/3 path row-merged the two columns, corrupting titles/credits). Header regex
  "DEPT NNN Title <3-4 small ints>" with CREDIT = the LAST int (catalog legend: class/lab/[clinical]/
  credit). Section bounded dynamically from the "section contains descriptions of courses" intro
  page so the earlier program-requirement tables (same line format) are not scraped. 596 courses,
  104 subjects, 0 blank/dup; high-credit outliers (HEO 12, BLET/LET 110 37, NUR 8/10) verified
  legit. academic_year blank (URL "2026_2027" is underscore-separated -> year_from_url misses it,
  same as La Sierra/Regent). Confirms NC-CC catalogs with a real Course-Descriptions table ARE
  scrapable (vs degree-plan PDFs).
- NOT scraped from 535-594: 544 Pima Medical-Las Vegas (Vol XI national PDF = known not-scrapable);
  all other rows I=FALSE.

## Batch 2026-06-22 (bundle-7): RS-15 rows 595-677 scan — 4 schools, 2,634 rows
Scanned Catalog-Data rows 595-677 (595-654 filled, 655-677 still blank J-N = I=FALSE, not scraped).
Scrapable in-scope I=TRUE candidates (all O/R empty):
- **Alfred University (3067170)** — Clean Catalog, "course-teaser-table" layout (distinct from the
  course-teaser layout: selectors are div.course-teaser-table-label a / h2.course-teaser-table-title
  a span.field__item / div.course-teaser-table-credits span.credits). NEW CourseTeaserTableSpider
  base (modern_campus_spider.py). Two sources merged: undergraduatecatalog.alfred.edu/undergraduate-
  courses (Undergraduate, 1443) + graduatecatalog.alfred.edu/graduate-courses (Graduate, 282) = 1725;
  paginated ?page=0..N. academic_year blank (no year on page/URL).
- **Northeast Ohio Medical (3073781)** — Coursedog (tenant neomed_banner_sql, catalog
  AAiqrvKholCprlJDolzR "2026-2027 Catalog", 457); body/effective/year derived from coursesFilters/
  displayName; AY 2026-2027; fractional medical credits (0.5,1.5) preserved.
- **Northeastern Oklahoma A&M (3077922)** — PDF (NortheasternOklahomaSpider). Single-column
  descriptions; regex "DEPT NNNN Title  Class N[, Lab N], Cr. N" with credit = the Cr. value (4-digit
  course numbers). Section bounded by the all-caps "COURSE DESCRIPTIONS" header (TOC line is mixed
  case). 214; AY blank (URL "2025__2027" double-underscore -> year_from_url misses it).
- **Highland CC (3031374)** — PDF (HighlandSpider). "DEPT NNN Title [GE|SWT|^|@] (credits)" with
  1-2 letter dept codes (A=Art, BS=Biology); trailing transfer/age markers stripped. Section bounded
  by the "Indicates the number of credits" legend page (pages before it are program/requirement
  tables of the same format). 238; high-credit BS 240/246 (EMT 12/13) verified legit; AY 2025-2027
  (biennial, from URL).
- NOT scraped: 611 South Seattle (Web,PDF Seattle Colleges biennial), 614/632 Fortis Pensacola/
  Columbus (rolling national PDF = known not-scrapable). 655-677 = blank-fill rows (all I=FALSE).

## Batch 2026-06-22b (bundle-8): COMBINED 11-school delivery (13,374 rows)
Two new spiders this round (rows 692/701): **JamestownSpider** (Coursedog tenant suny_jcc_banner,
catalog h1vfdEhiUE1gsEtGuQyJ "SUNY JCC 2026-2027 College Catalog", 719/722) and **PlazaSpider**
(PDF pdf_catalog_spider.py; "DEPT NNN Title N credits", section-bounded by "COURSE DESCRIPTIONS";
300; one cosmetic title CR 104 -> "IV" from tab-split). SWAU (row 680) skipped = already present in
catalog_scrape_2627/.
bundle-8 merges OUR 6 (Alfred 1725, NEOMED 457, NEOAM 214, Highland 238, Jamestown 719, Plaza 300)
with 5 schools from the parallel `catalog_scrape_2627/` tool that were NOT already in our data,
NORMALIZED to the 12-col schema (dept/code |-split; credits parsed from "(N Credits)"/"Credits N",
blank for the acalog/clean-catalog ones that ship code/title only; academic_year=2026-2027 from the
filename; source_url from workbook col K; dedup by (dept,code)):
- UConn-Stamford 3009591 (CourseLeaf, 7445; the source also had a description column -> dropped to
  fit the schema, preserved in catalog_scrape_2627/),
- Lord Fairfax/Laurel Ridge 3106117 (Acalog, 486, credits blank),
- SUNY Corning 3067459 (Clean Catalog, 590, credits filled),
- SWAU 3094146 (Clean Catalog, 760, credits blank),
- SW Michigan 3042629 (Acalog, 440, credits blank).
EXCLUDED from the table-of-7 because already in our data: Craven (3055614, prior bundle) and Alfred
(3067170 - we used our own UG+grad 1725, not the tool's UG-only 1444). External schools carry no
HTML/PDF backups (not crawled by our pipeline).

## 2026-06-23 — schema change + full re-scrape/QC of 77 (bundle-9)
THREE manager/client-directed changes applied to ALL spiders:
1. **Credits dropped** -> 11-col schema (pipeline FIELDNAMES; Palomar + IU updated).
2. **academic_year from page** when shown (items.year_from_page): CourseLeaf "2026-2027 Edition",
   Clean Catalog home <title>, Maricopa catalog displayName, IU = AY of scraped terms. Fixes the
   client complaint (e.g. CSU Bakersfield/NHTI were blank, now 2026-2027).
3. **IU term coverage** = union all available AY terms (Summer 2026 + Fall 2026) — fixes the
   manager's "less than live" catch (IU-Bloomington 5027 -> 5414 vs mgr 5422; the 395 were Summer-
   only courses a single-term scrape missed).
LIVE-COMPLETENESS QC METHOD (to catch the manager's issue): compare to the SOURCE's own total, not
the prior count. Coursedog/Maricopa -> API listLength; Banner -> totalCount; CourseLeaf -> subjects
on the live index; term-scoped -> union terms. For any flagged gap, deep-diff live-unique-codes vs
ours to separate cross-list dedup from a real miss.
REAL under-collections found & fixed (both matched prior counts, so only the live check caught them):
- **Northern Iowa 1919 -> 2812 (+893)**: 40 subjects with 7-8 letter / two-word dept codes (THEATRE,
  TEACHING, MUS HIST) were dropped by CODE_RE [A-Z]{2,6}.
- **DePaul 8790 -> 9186 (+396)**: long codes + ampersand depts A&S, T&L.
  Fix: CODE_RE -> `[A-Z][A-Z&]{0,8}(?:\s[A-Z][A-Z&]{0,8})?` (long/two-word/&/single-letter). Re-scraped
  all 24 CourseLeaf; only UNI & DePaul changed (rest stable). Also Nicholls global dedup (1561->1527),
  Stark/CourseLeaf no-number guard.
3 external schools REBUILT as real spiders (were catalog_scrape_2627 CSVs): UConn-Stamford (CourseLeaf
UG+grad 7445), SUNY Corning (Clean Catalog 590), SWAU (Clean Catalog UG+grad 760) — match external
counts exactly + add academic_year/grad_type. Lord Fairfax + SW Michigan stay external (acalog anti-bot
beats FlareSolverr, 202/0 courses), normalized to 11-col. Excluded: Trenholm 2988057, School of
Architecture 2990789 (no data anywhere). bundle-9 = 77 schools / 238,659 rows.

## TERM POLICY (manager Atasi, 2026-06-23) + IU QA — see HANDOFF for full detail
Term-scoped APIs (IU iGPS, Banner SSB): scrape ALL available terms, union by code, tag each by its
proper AY (Fall2026=2026-2027; Spring/Summer2026=2025-2026). Catching up on terms missed since the
Oct-2025 run. QA'd the manager's 7 IU campuses: schema clean; 6 regionals = full 3-term union
(complete); Bloomington = Summer+Fall only. OPEN: re-tag Spring/Summer-2026 -> 2025-2026; re-pull
Bloomington Spring 2026; make banner_ssb (UC-Riverside/Yeshiva/Kutztown) + iu_igps multi-term with
per-term AY, then refresh the bundle.

## PDF scraping (probed all 34 in-scope PDFs 2026-06-21)
Column-aware pdfplumber: detect the 2-column gutter via the word x-gap (NOT page midpoint, which
splits codes like "HPE"+"458"); group words into visual lines; parse with a TIGHT regex (wordy
letter-led title + paren credits "(N units/cr)") to reject prereq lists / addresses / GPA examples.
SCRAPABLE (4): ENMU (`enmu_spider.py`, UG+grad, 1583), La Sierra (1410), Regent (2004),
Pacific Union (344) — `pdf_catalog_spider.py`. NOT SCRAPABLE (30): degree-plan/check-sheet/prereq
formatted (credits come out as page numbers/contact hours; codes scattered in requirement lists).
Examples: SIU, El Paso, SOWELA, MS Delta, Northeast, Solano, Crowder, Jackson, Moody, Pima ×3,
Fortis, Denver Nursing, Fox Valley, Ultimate Medical. Do not retry without per-PDF section logic.

## bundle-18: missing-courses QA fixes, batch 2 of 2 (2026-07-17)
Completes the 7-school "missing courses" QA batch (batch 1 = bundle-17: NNU 1546, NEO A&M 345).
- Pacific Union 2995723: 344 -> 699. Local PDF (server 403s downloads). Per-line parse, two regexes
  (compact program tables w/ credit boundary + description headers), plus wrapped-title join pass
  (head line w/ no digits + Title-Case continuation ending in credit, looks ahead 2 lines to skip
  column interleave) and a bare "GNRL 100 Campus Community." pass. Roman-numeral-glued credits
  ("Accounting I3") now keep the numeral. `pdf_extractors/puc_pdf.py`.
- Highland CC 3031374: 238 -> 592. Five formats: compact w/ credit, description, no-credit course
  list ("HIS202 Introduction to Ancient History*"), work-experience "Title ^ (N)", bare trailing
  credit; plus OSHA/EPA/KSPN cert-shorthand titles. Pages 30-37 hold a garbled transfer-articulation
  matrix (4-digit university codes, "(3"/"Hours)" fragments, doubled words) — excluded by BADFRAG
  guard. `pdf_extractors/highland_pdf.py`.
- Palomar 2995726: 932 -> 1102. Descriptions parse kept as pass 1 (authoritative titles); new pass 2
  reads program-requirement tables (bare units, titles wrap to next line — joined) which alone hold
  170 real courses (DNCE/CFT/KINE/ACR...). Single-letter C-ID cross-reference codes ("C 1001") are
  garbage — the 2-4 letter dept requirement excludes them. FIN 341 is NOT in the catalog (false QA
  flag). `pdf_extractors/palomar_pdf.py` extended.
- NEO A&M 3077922: 2 title fixes (PSYC 1113 cross-list bleed, ENGL 2653 truncation).
Completeness QC: line-start code universe vs captured = 0 unresolved for all 4 PDF schools
(remaining gaps classified as transfer-matrix/calendar noise). NNU re-verified live: 1546 = 1546
badges across all 3 catalogs (11 code-normalization diffs only: "300#W", cross-listed "A/B" codes).
Format QC all 5: schema/dept/code/dup/entities/dates all clean.

## bundle-18 update: full completeness pass on all 7 QA-flagged schools (2026-07-17)
Final counts: CRC 1411, FLC 985, Highland 592, NEO A&M 349, NNU 1546, PUC 775, Palomar 1102.
- Los Rios (CRC 873->1411, FLC 525->985): `los_rios_spider.py` read only the requirement tables;
  Work-Experience/Experimental courses (198/298/299/498/499) and hundreds more exist ONLY as
  "<h3>CODE Title</h3>" description blocks on the same program pages — h3 pass added. ARC/SCC share
  the spider and were re-crawled too (2549/1759, kept in data/, not in this bundle's scope).
  Live completeness probes (all program pages re-fetched): CRC 0 missing, FLC 0 missing.
- PUC 699->775: arranged courses ("CODE credit Arr") carry no inline title; pass 3 column-crops
  pages (word-x-gap gutters) and takes the Title-Case streak of the next line, w/ 2-line join and
  overrides for two uncroppable columns. Every dept's 495 = "Independent Study" (catalog p.23).
- NEO A&M 345->349: comma-multi-code lines ("AG 1111, 1211, 2111, 2211 Rodeo Activities") expanded;
  2 em-dash-truncated titles fixed (clean_course_title cuts at "—" ranges).
- Highland: 17 list-bleed titles fixed (leading OR/AND from alternative lists, trailing cross-list
  tokens); TITLE_OVERRIDES in highland_pdf.py for the 10 verified by eye.
- clean_course_title over-strips titles matching "N Hour..." (OSHA courses) — fixed by hand in the
  Los Rios CSVs; watch for it elsewhere.
QC gates all green: 40/41 flagged codes present (Palomar FIN 341 does NOT exist in the 2026-27 PDF
— false flag); completeness 0 unresolved vs source for all 7; format QC clean for all 7.
