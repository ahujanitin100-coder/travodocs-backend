from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache

class Settings(BaseSettings):
    mongodb_url: str = Field(..., alias="MONGO_URL")
    db_name: str = Field(..., alias="DB_NAME")
    jwt_secret: str = Field(..., alias="JWT_SECRET")
    admin_email: str = Field(..., alias="ADMIN_EMAIL")
    admin_password: str = Field(..., alias="ADMIN_PASSWORD")
    frontend_url: str = Field(default="http://localhost:3000", alias="FRONTEND_URL")
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

@lru_cache
def get_settings() -> Settings:
    return Settings()