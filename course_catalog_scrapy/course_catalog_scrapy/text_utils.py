import re


def html_to_text(
    html_content,
    ignore_links=True,
    ignore_images=True,
    ignore_tables=False,
    ignore_emphasis=True,
    body_width=2000,
    plain_text_only=False,
    **kwargs,
):
    import html2text

    text_maker = html2text.HTML2Text()
    text_maker.ignore_links = ignore_links
    text_maker.ignore_images = ignore_images
    text_maker.ignore_tables = ignore_tables
    text_maker.ignore_emphasis = ignore_emphasis
    text_maker.body_width = body_width

    if plain_text_only:
        text_maker.bypass_tables = False
        text_maker.ignore_emphasis = True
        text_maker.ignore_links = True
        text_maker.ignore_images = True
        text_maker.ignore_tables = True
        text_maker.default_image_alt = ""
        text_maker.skip_internal_links = True
        text_maker.inline_links = False
        text_maker.protect_links = False
        text_maker.mark_code = False

    cleaned_text = text_maker.handle(html_content).strip()

    if plain_text_only:
        cleaned_text = re.sub(r"^#{1,6}\s*\*\s*", "", cleaned_text, flags=re.MULTILINE)
        cleaned_text = re.sub(r"^#{1,6}\s*", "", cleaned_text, flags=re.MULTILINE)
        cleaned_text = re.sub(r"^\s*\*\s*", "", cleaned_text, flags=re.MULTILINE)
        cleaned_text = re.sub(r"\*{1,2}([^\*]+)\*{1,2}", r"\1", cleaned_text)
        cleaned_text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned_text)
        cleaned_text = re.sub(r"\n\s*\n", "\n", cleaned_text)
        cleaned_text = re.sub(r"[ \t]+", " ", cleaned_text)

    return cleaned_text


convert_html_to_text = html_to_text


def extract_course_title_from_long_line(title, algorithm="sentenceCase"):
    if not title or not isinstance(title, str):
        return ""

    words = title.split()
    if not words:
        return ""

    clean_title = []

    if algorithm == "sentenceCase":
        allow_conjenction = ["and", "the", "but", "nor", "yet", "for"]

        for i in range(1, len(words)):
            current_word = words[i]
            previous_word = words[i - 1]
            clean_title.append(previous_word)

            if not current_word[0].isupper():
                if len(current_word) < 3 or current_word in allow_conjenction:
                    continue
                break

            if i + 1 < len(words):
                if words[i + 1] in allow_conjenction:
                    continue
                if words[i + 1][0].islower():
                    break

    return " ".join(clean_title)


def clean_course_title(title):
    if not title:
        return ""

    title = re.sub(r"^[\s]*#{1,6}[\s]*\*+[\s]*", "", title)
    title = re.sub(r"^[\s]*\*+[\s]*", "", title)

    credit_pattern = r"\s*\d[\d\.\-]*[\w ]*(?:[Hh]r|[Cc]r|[Hh][Oo][Uu][Rr]|[Cc][Rr][Ee][Dd][Ii][Tt]|[Uu][Nn][Ii][Tt])s?[^\n]*$"
    title = re.sub(credit_pattern, "", title)

    title = re.sub(
        r"\s*\(\s*\d[\d\.\-]*[\w ]*(?:[Hh]r|[Cc]r|[Hh][Oo][Uu][Rr]|[Cc][Rr][Ee][Dd][Ii][Tt]|[Uu][Nn][Ii][Tt])s?[^\)]*\)\s*$",
        "",
        title,
    )
    title = re.sub(
        r"\s*\(\s*\d+(?:\.\d+)?(?:\s*[-–—]\s*\d+(?:\.\d+)?)?\s*\)\s*$", "", title
    )

    title = re.sub(r"\s*\.\s*$", "", title)
    title = re.sub(r"[\-\—\–\:\;\,\!\?\*\#\@\&\%\$]+\s*$", "", title)
    title = re.sub(r"\s*\(\s*$", "", title)
    title = title.strip() if title else title

    return title
