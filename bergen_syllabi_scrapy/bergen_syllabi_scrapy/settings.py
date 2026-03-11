BOT_NAME = "bergen_syllabi_scrapy"

SPIDER_MODULES = ["bergen_syllabi_scrapy.spiders"]
NEWSPIDER_MODULE = "bergen_syllabi_scrapy.spiders"

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

ITEM_PIPELINES = {
    "bergen_syllabi_scrapy.pipelines.CsvExportPipeline": 1,
}

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

FEED_EXPORT_ENCODING = "utf-8"

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
