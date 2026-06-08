import re

_SEASON_RE = re.compile(r"(Fall|Spring|Summer|Winter)\s+(\d{4})(?:\s*-\s*(\d{2,4}))?", re.I)
_AY_RE = re.compile(r"(\d{4})\s*-\s*(\d{4})")


def term_in_academic_year(term, academic_year):
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
    if season == "fall":
        return term if year == start else ""
    if season == "winter" and m.group(3) is not None:
        return term if year == start else ""
    return term if year == end else ""


def term_decision(last_term, academic_year):
    if not last_term or not _SEASON_RE.search(last_term):
        return True, ""
    in_ay = term_in_academic_year(last_term, academic_year)
    return (True, in_ay) if in_ay else (False, "")
