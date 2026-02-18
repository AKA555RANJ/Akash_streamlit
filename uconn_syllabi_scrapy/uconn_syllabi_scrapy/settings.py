BOT_NAME = "uconn_syllabi_scrapy"

SPIDER_MODULES = ["uconn_syllabi_scrapy.spiders"]
NEWSPIDER_MODULE = "uconn_syllabi_scrapy.spiders"

# Respect robots.txt
ROBOTSTXT_OBEY = True

# PHP backend — 2 concurrent requests is safe
CONCURRENT_REQUESTS = 2
DOWNLOAD_DELAY = 1.0
RANDOMIZE_DOWNLOAD_DELAY = True  # actual delay: 0.5s–1.5s

# Disable cookies (not needed; avoids stale session interference)
COOKIES_ENABLED = False

# Disable caching so we always fetch fresh data
HTTPCACHE_ENABLED = False

# Default request headers
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Files pipeline — downloads go into syllabi_downloads/
FILES_STORE = "syllabi_downloads"

ITEM_PIPELINES = {
    "uconn_syllabi_scrapy.pipelines.UConnFilesPipeline": 1,
    "uconn_syllabi_scrapy.pipelines.CsvExportPipeline":  2,
    "uconn_syllabi_scrapy.pipelines.JsonExportPipeline": 3,
}

# Twisted reactor (required for newer Scrapy versions on some platforms)
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

# Feed export encoding
FEED_EXPORT_ENCODING = "utf-8"

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
