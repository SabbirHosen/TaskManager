import os
import redis
from urllib.parse import urlparse

class RedisClient:
    _instance = None  # Class variable to store the Redis instance

    def __new__(cls):
        """Ensure only one instance is created (Singleton)."""
        if cls._instance is None:
            cls._instance = super(RedisClient, cls).__new__(cls)

            # Load Redis configuration
            redis_url = os.getenv("REDIS_URL")
            if redis_url:
                url = urlparse(redis_url)
                redis_host = url.hostname
                redis_port = url.port
                redis_password = url.password
            else:
                redis_host = os.getenv("REDIS_HOST", "localhost")
                redis_port = int(os.getenv("REDIS_PORT", 6379))
                redis_password = None  # No password if REDIS_URL is not set

            redis_db = int(os.getenv("REDIS_DB", 0))

            # Initialize Redis connection
            try:
                cls._instance.redis = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    password=redis_password,
                    db=redis_db,
                    charset="utf-8",
                    decode_responses=True
                )
                if cls._instance.redis.ping():
                    print("✅ Connected to Redis successfully.")
            except redis.ConnectionError as e:
                print(f"❌ Failed to connect to Redis: {e}")
                cls._instance.redis = None  # Ensure instance exists even on failure

        return cls._instance

    def get_redis(self):
        """Return the Redis instance."""
        return self.redis

# Create a single instance to be imported elsewhere
redis_client = RedisClient().get_redis()
