from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_env: str
    debug: bool

    api_host: str
    api_port: int

    db_server: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_driver: str

    db_pool_size: int
    db_max_overflow: int
    db_pool_timeout: int
    db_pool_recycle: int

    redis_host: str
    redis_port: int
    redis_db: int

    jwt_secret: str
    jwt_algorithm: str
    jwt_expiration_minutes: int

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings():
    return Settings()