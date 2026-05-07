from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "api-gateway"

    AUTH_SERVICE_URL: str = "http://auth_service:8007"
    STOCK_SERVICE_URL: str = "http://stock_service:2004"
    ML_SERVICE_URL: str = "http://inference_service:8020"
    SCRAPING_SERVICE_URL: str = "http://scraping_service:8060"
    CSV_IMPORT_SERVICE_URL: str = "http://csv_import_service:8030"
    ALERTS_SERVICE_URL: str = "http://alerts_service:8006"

    FRONTEND_URL: str = "http://localhost:5173"

    DEFAULT_TIMEOUT_SECONDS: float = 120.0
    LONG_TIMEOUT_SECONDS: float = 600.0


settings = Settings()