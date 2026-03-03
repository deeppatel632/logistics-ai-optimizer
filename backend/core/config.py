from pydantic_settings import BaseSettings
from functools import lru_cache




class Settings(BaseSettings):
    db_user: str
    db_password: str
    db_server: str
    db_port: int
    db_name: str
    db_driver: str

    redis_host: str = "localhost"
    redis_port: int = 6379

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()