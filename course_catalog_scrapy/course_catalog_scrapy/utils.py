import re

# Matches "Fall 2026", "Spring 2027", "Winter 2026-27", "Winter 2026-2027".
_SEASON_RE = re.compile(
    r"(Fall|Spring|Summer|Winter)\s+(\d{4})(?:\s*-\s*(\d{2,4}))?", re.I
)
_AY_RE = re.compile(r"(\d{4})\s*-\s*(\d{4})")


def term_in_academic_year(term, academic_year):
    """Return `term` only if it falls within `academic_year` (e.g. "2026-2027"),
    else "". A Fall term belongs to its start year; Spring/Summer/Winter belong to
    the end year. Winter ranges ("Winter 2026-27") belong to the start year.
    Used to drop historical "last term offered" values from a single-year catalog.
    """
    if not term or not academic_year:
        return ""
    ay = _AY_RE.search(academic_year)
    if not ay:
        return ""
    start, end = int(ay.group(1)), int(ay.group(2))

    m = _SEASON_RE.search(term)
    if not m:
        return ""
    season = m.group(1).lower()
    year = int(m.group(2))
    is_range = m.group(3) is not None

    if season == "fall":
        return term if year == start else ""
    if season == "winter" and is_range:
        return term if year == start else ""
    # Spring / Summer / single-year Winter belong to the end year.
    return term if year == end else ""


def term_decision(last_term, academic_year):
    """Decide whether a course belongs in a single-year catalog, based on its
    "last term offered" value. Returns (keep_row, term_value):
    - a dated term within `academic_year`  -> (True, that term)
    - a dated term outside it (historical)  -> (False, "")  # drop the course
    - a non-dated status ("not yet offered"
      / blank, i.e. new/unscheduled course) -> (True, "")   # keep, no term
    """
    if not last_term:
        return True, ""
    if not _SEASON_RE.search(last_term):
        return True, ""
    in_ay = term_in_academic_year(last_term, academic_year)
    if in_ay:
        return True, in_ay
    return False, ""
