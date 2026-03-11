import scrapy


class SccSyllabusItem(scrapy.Item):
    school_id               = scrapy.Field()
    term_code               = scrapy.Field()
    term                    = scrapy.Field()
    department_code         = scrapy.Field()
    department_name         = scrapy.Field()
    course_code             = scrapy.Field()
    course_titel            = scrapy.Field()
    section_code            = scrapy.Field()
    instructor              = scrapy.Field()
    syllabus_filename       = scrapy.Field()
    syllabus_file_format    = scrapy.Field()
    syllabus_filepath_local = scrapy.Field()
    syllabus_filesize       = scrapy.Field()
    syllabus_file_source_url = scrapy.Field()
    source_url              = scrapy.Field()
    crawled_on              = scrapy.Field()
    downloaded_on           = scrapy.Field()
    _syllabus_html          = scrapy.Field()
