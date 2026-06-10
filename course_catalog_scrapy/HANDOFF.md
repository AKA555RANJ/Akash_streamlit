# Course Catalog Scraper — Handoff / Session Guide

Single source of truth for resuming this work in a fresh session. Read this first,
then `SCRAPE_NOTES.md` (per-school status log).

---

## 1. Goal
Scrape 2026-2027 **course-catalog** data for colleges whose catalog is available as a
**web** version, one dedicated scraper per school, into a fixed CSV schema.

## 2. Source of truth
Workbook: `/Users/akashranjan/Downloads/Course Catalog - Rational Solver-10.xlsx`
Sheet: **`Catalog-Data`** (~1,768 rows). Relevant columns:

| Col | Field |
|---|---|
| A | school_id (7-digit) |
| B | university_name |
| E | File Name = folder **slug** (ends in `__cc`) |
| I | `2026-2027 Catalog Available?` (TRUE/FALSE) |
| J | Catalog Home Page |
| K | Catalog URL For AY2026-2027 |
| L | Type of Catalog (`Web` / `PDF` / `Web, PDF`) |
| M | Sub Type (platform: AZ Sitemap, Web View Rows, Coursedog, Catod_Navoid, Selfservice, Class Search, CurriQunet, eLumen, SmartCatalogIQ, …) |
| O | Spider Status |
| P | Last Crawled On |

Read it with openpyxl via **system** `python3` (has openpyxl); the venv may not.

## 3. Scope rules (manager-confirmed)
- In scope: **col I = TRUE** AND **col L == "Web"** exactly (skip `PDF` and `Web, PDF`).
- **EXCLUDE** these platforms (col M): `Class Search` (course-search), `Catod_Navoid`
  (acalog catoid/navoid), `AZ Sitemap` (= CourseLeaf), `Coursedog`.
  - **Exclusion DROPPED (manager-directed, see §8b):** the platform-exclusion list is no
    longer in force — previously-excluded platforms (Coursedog, CourseLeaf, acalog, …) are
    now in scope. Coursedog (Mesa/PV/Scottsdale) and CourseLeaf (7 schools) already scraped.
- **Targets**: `Web View Rows`, `CurriQunet`, `eLumen`, `SmartCatalogIQ`, plus genuine
  static blank-Sub-Type rows. `Selfservice` (Banner/Ellucian) = skip.
- Always verify the real platform: some "Web View Rows" rows are CourseLeaf hidden behind
  Cloudflare — render with FlareSolverr and check before building (CSU Chico, RIT were
  unmasked as CourseLeaf and excluded).

## 4. Output schema — `CourseItem` (9 fields, fixed order)
`school_id, department_code, course_code, course_title, credits, graduate_type, term,
academic_year, source_url`

### CSV conventions (manager-confirmed — see feedback memory)
- **Split** the scraped code: `department_code` = letters, `course_code` = number only.
  Done in the **shared pipeline** (`format_dept_code`), NOT in spiders.
- **Leading `|`**: store `|AAC` and `|200` (the `|` forces text so `010` is not coerced
  to `10`). PDF extractors import the same `format_dept_code` helper.
- `school_id` = 7-digit col A.
- `graduate_type` = `Undergraduate` / `Graduate` when known, else blank.
- `term` = blank unless the page exposes it. **Term-selection logic must live INSIDE the
  spider** (not a shared util) — at 100+ spiders a shared term module becomes unmanageable.
- **academic_year policy**: scrape from the page when present. If the page shows no explicit
  2026-2027, leave it **blank** (never hard-code), still scrape (col I = Yes + we crawl the
  col K AY2026-2027 URL), and add a note in `SCRAPE_NOTES.md`.
- CSV path: `data/<col-E-slug>/<col-E-slug>.csv`.

## 5. Architecture
ONE shared Scrapy project, ONE shared pipeline. Only the per-school spider file changes.
```
course_catalog_scrapy/
  scrapy.cfg
  course_catalog_scrapy/
    items.py          # CourseItem
    settings.py       # ROBOTSTXT_OBEY, DOWNLOAD_DELAY=1, asyncio reactor, CsvExportPipeline
    pipelines.py      # CsvExportPipeline + format_dept_code()  <-- shared, do not fork per school
    spiders/<school>_spider.py   # one per school
  pdf_extractors/<school>_pdf.py # standalone pdfplumber scripts (import format_dept_code)
  SCRAPE_NOTES.md     # per-school status
  HANDOFF.md          # this file
```

## 6. Environment
- venv: `/Users/akashranjan/Akash_streamlit/.venv_catalog` (python 3.9.6, Scrapy 2.13.4,
  pdfplumber, playwright). System `python3` has openpyxl but NOT scrapy.
- Run a spider: `cd course_catalog_scrapy && ../.venv_catalog/bin/scrapy crawl <name>`
  - Smoke test: add `-s CLOSESPIDER_ITEMCOUNT=20` (note: single-page spiders ignore it).
  - Gentle (rate-limited sites): `-s DOWNLOAD_DELAY=2 -s CONCURRENT_REQUESTS=1`.
- Run a PDF extractor: `.venv_catalog/bin/python course_catalog_scrapy/pdf_extractors/<x>.py`
- **FlareSolverr** (for Cloudflare/403 and to render/inspect): already runs at
  `http://localhost:8191`. Start (user's macOS setup):
  ```
  export PATH="/opt/homebrew/bin:$PATH"
  export CHROME_EXE_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  export HEADLESS=false
  python3.12 -m flaresolverr
  ```
  Call: `POST http://localhost:8191/v1 {"cmd":"request.get","url":..,"maxTimeout":80000}`.
  `solution.response` is the rendered HTML string (for JSON endpoints it is parsed
  dict/list). Use sequentially (one request at a time).
- **Playwright**: `.venv_catalog`, launch with `channel="chrome"` (system Chrome, no
  download). Headless works for normal SPAs; Cloudflare sites need FlareSolverr instead.

## 7. Techniques by catalog type (decision tree)
1. **Static HTML, all on one/few pages** → plain Scrapy (Southern CT, UNCO, Nicholls).
2. **Index → detail pages** for missing fields → follow links (Rhodes: credits on detail).
3. **SPA** → use Playwright to capture the JSON/XHR API, then hit the API directly with
   Scrapy/requests (eLumen: `api-prod.elumenapp.com`).
4. **Cloudflare / 403** → FlareSolverr renders it; the spider can POST to FlareSolverr in
   `start_requests` and parse `solution.response` (Williams).
5. **Web unreachable (network/TLS block)** → look for a reachable **2026-2027 PDF** on the
   school's own domain; parse with pdfplumber **column-aware** (crop left/right halves —
   `page.crop((0,0,w/2,h))` and `(w/2,0,w,h)`) to avoid 2-column text merging (Palomar).
6. If no reachable current source exists → mark UNDELIVERABLE in notes, hand to manager.

## 8. Status — 21 scraped (original 18-target set: 14 scraped · 2 excluded · 2 undeliverable;
## PLUS 7 from the dropped-exclusion expansion, see §8b)
SCRAPED & DONE (14 from the original target set, pushed to main; CSVs in `data/<slug>/`):

| school_id | school | platform | rows |
|---|---|---|---|
| 3009619 | Southern Connecticut State | Web View Rows (static) | 2023 |
| 3007266 | UNC Greeley | SmartCatalogIQ (multi-level) | 3333 |
| 3035086 | Nicholls State | Web View Rows (subject pages) | 1561 |
| 3091104 | Rhodes College | Web View Rows (index+detail) | 1420 |
| 3050281 | Metropolitan CC-Kansas City | eLumen SPA (API) | 939 |
| 3037159 | Williams College | class-schedule SPA (FlareSolverr) | 1378 |
| 2995726 | Palomar College | PDF (web unreachable) | 932 |
| 3037211 | UMass Boston | Web View Rows (index+detail) | 1569 |
| 2990776 | Mesa CC | Coursedog SPA (JSON API) | 6149 |
| 2990782 | Paradise Valley CC | Coursedog SPA (JSON API) | 6149 |
| 2990779 | Scottsdale CC | Coursedog SPA (JSON API) | 6149 |
| 2995968 | American River | Web View Rows (program tables, derived) | 1579 |
| 2996053 | Folsom Lake | Web View Rows (program tables, derived) | 525 |
| 2996026 | Sacramento City | Web View Rows (program tables, derived) | 1049 |

Notes: Mesa/PV/Scottsdale are ONE Maricopa district Coursedog catalog (common course
numbering -> identical course bank across the three; CSVs differ only by school_id /
source_url). Los Rios three are DERIVED from per-program requirement tables (no standalone
listing exists; incomplete, no descriptions). UMass Boston needs a browser UA (default 403).
See SCRAPE_NOTES.md for per-platform details.

## 8b. Expansion: exclusion list DROPPED (manager direction)
Manager asked to scrape previously-excluded platforms too (work down the in-scope Web rows from
the top). 86 in-scope Web rows total; ~73 were unscraped. Biggest scrapable groups: CourseLeaf
(24, was "AZ Sitemap"), Coursedog (8, technique proven), acalog/Catod_Navoid (10). Built a shared
`courseleaf_spider.py` (handles all 3 CourseLeaf layouts — see SCRAPE_NOTES). 7 CourseLeaf done so
far then PAUSED at manager request (cap of 7): UIUC (3023894, 9452), LMU (3006182, 4665), CSU San
Bernardino (2996062, 4049), CSU Dominguez (2996065, 3035), CSU Bakersfield (2996060, 2461), Columbus
State (3017973, 2349), Northern Iowa (3020616, 1919). NEXT when resumed: more CourseLeaf, then the
Coursedog batch (generic spider; tenants like fsu_peoplesoft, umn_umntc_peoplesoft — capture
catalogId via Playwright like Maricopa), then acalog. Class Search / Self-Service / blank = dynamic
portals, case-by-case. (Note: CSU Chico 2996064 + RIT 3067286 below were excluded as CourseLeaf
when CourseLeaf was out of scope; they are now scrapable with courseleaf_spider if wanted.)

EXCLUDED earlier as CourseLeaf (now scrapable via courseleaf_spider if desired):
CSU Chico (2996064), RIT (3067286).

UNDELIVERABLE here (CurriQunet network block — need a different network/IP where
curriqunet.com resolves): Chaffey (2995976), Riverside (2996025). [Scottsdale was here but
was RECOVERED via the Maricopa Coursedog — only its old curriculum.maricopa.edu URL was
blocked.]

## 9. Per-school implementation notes (selectors / APIs / gotchas)
- **Southern CT**: `div.course-box[id]` → `h2` "CODE NNN - Title", `p.course-credits`,
  `p.last-term-offered` ("Last Term Offered: Spring 2027"). Year from `nav#breadcrumbs a`.
  Term filter (inline in spider): keep only terms within academic_year, keep "not yet
  offered", drop historical. UG + grad pages.
- **UNCO** (SmartCatalogIQ): index `…/course-descriptions/` → subject links = path with one
  segment after `course-descriptions/`. Subject page: `div.courselist h2.course-name` →
  `span` = code, anchor text = title; credits via
  `following-sibling::div[contains(@class,'sc-credithours')][1]//div[@class='credits']`.
  Normalize credits whitespace. UG + graduate catalogs.
- **Nicholls**: 91 subject pages under `…/courses_of_instruction/<subject>/`. Courses are
  `<p>` with `<strong>CODE. Title</strong>` (sometimes two `<strong>` tags) then `C-L-L`
  triple; credits = first number of the triple. Parse via paragraph text up to the triple,
  fallback to combined `<strong>` text. **Rate-limits (429)** → run gentle.
- **Rhodes**: index `div.views-field-field-course-number` has NESTED `<a>` (parser splits
  them) → code = 1st `a::text`, title = 2nd. Credits on detail page
  `div.course__credits span`. NO on-page year → academic_year blank + note. **Antibot
  rate-limits detail pages** (slow; 1,442 requests).
- **MCCKC** (eLumen API): `content_url(route) =
  api-prod.elumenapp.com/catalog/sites/publish/content/<route-with-/-as-,>?tenant=mcckc.elumenapp.com`.
  Crawl: `2026-2027/courses` → `2026-2027/department/<slug>` → `a.navitem`
  (`span.navitem-x-text` = "CODE - Title", href `2026-2027/course/<key>`) → course detail
  has "X.X Credits" + year. Reverse-engineered via Playwright network capture.
- **Williams**: SPA class schedule. Spider POSTs to FlareSolverr to render
  `catalog.williams.edu/list/`. Courses are `a.Accordion` text
  "DEPT NUM - SECTION (SEM) TYPE Title"; dedupe sections → courses; credits NOT in listing
  (blank); year "2026-27" normalized to "2026-2027". Cloudflare-gated (needs FlareSolverr).
- **Palomar** (PDF): `pdf_extractors/palomar_pdf.py`. COURSES section ~pp.203-358, 2-column.
  Column-crop each page; header regex `^(DEPT)\s(NUM)\s+(title)\s+\((units)\)$`. Year from
  PDF text. Web catalog (CurriQunet) is network-unreachable.

## 10. Gotchas learned
- `curriqunet.com` → connection refused to ALL tools (curl=000, FlareSolverr, headless &
  headful Playwright). `curriculum.maricopa.edu` → times out. These are network/IP blocks.
- `mccd.edu` = **Merced** College, NOT Maricopa — wrong PDF for Scottsdale.
- Python 3.9 f-strings cannot contain backslashes (build regex strings outside the f-string).
- FlareSolverr returns JSON endpoints as parsed objects, HTML as a string — handle both.
- `data/` is gitignored; CSVs are force-added (`git add -f`) and tracked via Git LFS.
- ROBOTSTXT_OBEY robots.txt 500 errors are harmless; the crawl proceeds.

## 11. Adding a new school (workflow)
1. From `Catalog-Data`, get school_id, slug (col E), col K URL, col M Sub Type.
2. Probe the URL (curl). If 403/202/empty → render via FlareSolverr and check the real
   platform (exclude if CourseLeaf/Coursedog/etc.).
3. Pick a technique from §7. Inspect the DOM/API/PDF to find code/title/credits/year.
4. Write `spiders/<school>_spider.py` (set `name`, `school_id`, `slug`, `allowed_domains`).
   Keep any term logic inside the spider. Do NOT format codes in the spider — the pipeline
   adds the `|` and splits dept/number.
5. Smoke test, then full run. Validate: empty fields, year, credits, row count.
6. Update `SCRAPE_NOTES.md`. Commit spider + `git add -f` the CSV; push.

## 12. Git / commit
- Branch `main` (user pushes directly here per their instruction).
- `git add -f data/<slug>/<slug>.csv` (data/ is gitignored, LFS-tracked).
- Commit message ends with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## 13. Related memory files
`project-course-catalog-scrapy` (progress), `feedback-catalog-csv-conventions`
(|-prefix / split / per-spider term rules).
