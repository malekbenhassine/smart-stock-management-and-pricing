from pydantic import BaseSettings, EmailStr


class Settings(BaseSettings):
    APP_NAME: str = "auth-service"
    API_V1_PREFIX: str = "/api/v1"

    DB_HOST: str = "postgres"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_NAME: str = "auth_db"

    JWT_SECRET_KEY: str = "change-me-super-secret"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120

    ACTIVATION_TOKEN_EXPIRE_HOURS: int = 24
    FRONTEND_ACTIVATION_URL: str = "http://localhost:5173/activate-account"
    FRONTEND_RESET_PASSWORD_URL: str = "http://localhost:5173/reset-password"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = "your_email@gmail.com"
    SMTP_PASSWORD: str = "your_app_password"
    MAIL_FROM: EmailStr = "your_email@gmail.com"

    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


settings = Settings()