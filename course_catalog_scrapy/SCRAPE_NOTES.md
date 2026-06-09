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

## Notes for "year not on page" schools
Standard note: "2026-2027 not explicitly shown on the catalog page; scraped whatever
was available at the Catalog URL For AY2026-2027 (col K), which is flagged 2026-2027
Catalog Available = Yes (col I)."

- **Rhodes College (3091104)** — academic_year left blank: no 2026-2027 string appears
  on the courses index or the per-course detail pages. Scraped from col K
  (`https://catalog.rhodes.edu/courses`), col I = Yes. Term also not exposed.

## Excluded after FlareSolverr inspection (actually CourseLeaf)
These were labeled "Web View Rows" but the rendered page is CourseLeaf -> out of scope:
- CSU Chico (2996064) — courseleaf (was hidden behind Cloudflare)
- RIT (3067286) — courseleaf (served 2025-2026)

## Remaining target schools (not yet done)
Tractable (standard tech, needs page mapping):
- Williams (3037159) — WordPress catalog (wp-json API + dept pages); also has a PDF
- UMass Boston (3037211): term-based schedule pages, multi-level; deferred
- Los Rios (American River 2995968, Folsom Lake 2996053, Sacramento City 2996026):
  the "unofficial catalog preview" has NO course-description listing; courses appear
  only inside program-requirement tables (Code|Title|Units) -> duplicates across
  programs, incomplete coverage, no descriptions. Needs manager decision on whether
  a deduped program-table scrape is acceptable.

Hard — FlareSolverr alone insufficient (TLS-blocked / JS SPA needing interaction):
- CurriQunet SPA (Chaffey 2995976, Palomar 2995726, Riverside City 2996025) —
  HTTP 000 to all clients (TLS-level block) + SPA
- eLumen SPA (Metropolitan CC-Kansas City 3050281) — returns 753-byte app shell only
- Maricopa (Mesa CC 2990776, Paradise Valley 2990782 render 2025-2026 landing pages;
  Scottsdale 2990779 curriculum.maricopa.edu is a SPA that errored in FlareSolverr)
