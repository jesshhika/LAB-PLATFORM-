from redis import Redis
from rq import Queue

from api.app.core.config import get_settings

redis_connection = Redis.from_url(get_settings().redis_url)
default_queue = Queue("default", connection=redis_connection)
