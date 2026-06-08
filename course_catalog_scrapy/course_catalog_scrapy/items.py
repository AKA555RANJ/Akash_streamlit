import scrapy


class CourseItem(scrapy.Item):
    school_id = scrapy.Field()
    department_code = scrapy.Field()
    course_code = scrapy.Field()
    course_title = scrapy.Field()
    credits = scrapy.Field()
    graduate_type = scrapy.Field()
    term = scrapy.Field()
    academic_year = scrapy.Field()
    source_url = scrapy.Field()
