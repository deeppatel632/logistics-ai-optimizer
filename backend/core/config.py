from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    # App
    app_env: str
    debug: bool
    api_host: str
    api_port: int

    # Database
    db_user: str
    db_password: str
    db_server: str
    db_port: int
    db_name: str
    db_driver: str
    primary_db_url: str
    replica_db_url: str

    db_pool_size: int
    db_max_overflow: int
    db_pool_timeout: int
    db_pool_recycle: int

    # Redis
    redis_host: str
    redis_port: int
    redis_db: int

    # Kafka
    # Default targets the service name defined in docker-compose.prod.yml.
    # Override via KAFKA_BOOTSTRAP_SERVERS env var for other environments.
    kafka_bootstrap_servers: str = "kafka:9092"

    # JWT
    jwt_secret: str
    jwt_algorithm: str
    jwt_expiration_minutes: int

    class Config:
        env_file = ".env"
        extra = "ignore"   # allow extra env vars we don't own (e.g. PATH)


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()