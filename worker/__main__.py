from rq import Worker

from api.app.core.queue import default_queue, redis_connection

if __name__ == "__main__":
    Worker([default_queue], connection=redis_connection).work()
