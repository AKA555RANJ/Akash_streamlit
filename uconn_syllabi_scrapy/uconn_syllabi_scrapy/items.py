import scrapy


class UConnSyllabusItem(scrapy.Item):
    # Output fields (exported to CSV/JSON)
    term_name               = scrapy.Field()  # e.g. "Fall 2025"
    class_name              = scrapy.Field()  # e.g. "CSE 3666"
    section                 = scrapy.Field()  # e.g. "001"
    instructor              = scrapy.Field()  # e.g. "Zhijie Shi"
    syllabus_web_url        = scrapy.Field()  # absolute URL (pipe → %7C)
    syllabus_local_filepath = scrapy.Field()  # e.g. "syllabi_downloads/1258_CSE_3666_1410.pdf"
    syllabus_local_filename = scrapy.Field()  # e.g. "1258_CSE_3666_1410.pdf"

    # Internal fields (used by FilesPipeline; not exported)
    term_code  = scrapy.Field()  # e.g. "1258" — for filtering and filename prefix
    file_urls  = scrapy.Field()  # [syllabus_web_url] or [] (no_download mode)
    files      = scrapy.Field()  # populated by FilesPipeline after download
