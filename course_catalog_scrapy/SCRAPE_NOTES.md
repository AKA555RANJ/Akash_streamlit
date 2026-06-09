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

## Notes for "year not on page" schools
(Populated as encountered. Standard note: "2026-2027 not explicitly shown on the
catalog page; scraped whatever was available at the Catalog URL For AY2026-2027
(col K), which is flagged 2026-2027 Catalog Available = Yes (col I).")
