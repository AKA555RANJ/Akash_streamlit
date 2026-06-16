from course_catalog_scrapy.items import CourseItem


class AttachRawHtmlMiddleware:
    """Attach the raw page body to every CourseItem so HTMLCompactStoragePipeline can
    archive the exact source the row was scraped from. Done in one place instead of in
    every spider's yield."""

    def process_spider_output(self, response, result, spider):
        for item in result:
            if isinstance(item, CourseItem) and not item.get("raw_html"):
                item["raw_html"] = response.body
            yield item
