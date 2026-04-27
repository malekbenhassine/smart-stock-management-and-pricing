import os


class Settings:
    STOCK_SERVICE_URL: str = os.getenv("STOCK_SERVICE_URL", "http://stock_service:2004")
    SCRAPING_INTERVAL_MINUTES: int = int(os.getenv("SCRAPING_INTERVAL_MINUTES", "60"))
    HEADLESS: bool = os.getenv("HEADLESS", "true").lower() == "true"
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "20"))
    MAX_PAGES_PER_CATALOG: int = int(os.getenv("MAX_PAGES_PER_CATALOG", "20"))
    USER_AGENT: str = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )


settings = Settings()