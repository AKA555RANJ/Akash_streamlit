BOT_NAME = "course_catalog_scrapy"
SPIDER_MODULES = ["course_catalog_scrapy.spiders"]
NEWSPIDER_MODULE = "course_catalog_scrapy.spiders"
ROBOTSTXT_OBEY = True
CONCURRENT_REQUESTS = 2
DOWNLOAD_DELAY = 1.0
RANDOMIZE_DOWNLOAD_DELAY = True
COOKIES_ENABLED = True
HTTPCACHE_ENABLED = False
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
SPIDER_MIDDLEWARES = {
    "course_catalog_scrapy.middlewares.AttachRawHtmlMiddleware": 100,
}
ITEM_PIPELINES = {
    "course_catalog_scrapy.pipelines.HTMLCompactStoragePipeline": 100,
    "course_catalog_scrapy.pipelines.CleanCourseTitlePipeline": 200,
    "course_catalog_scrapy.pipelines.CsvExportPipeline": 300,
}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
