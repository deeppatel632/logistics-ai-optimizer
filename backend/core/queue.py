from redis import Redis
from rq import Queue

from backend.core.config import settings


redis_conn = Redis(
    host=settings.redis_host,
    port=settings.redis_port,
)

shipment_queue = Queue("shipment_tasks", connection=redis_conn)