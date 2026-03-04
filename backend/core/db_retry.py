import time
import functools
from sqlalchemy.exc import OperationalError


def retry_on_deadlock(max_retries=3, delay=0.2):
    """
    Retries a DB operation if a deadlock occurs.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)

                except OperationalError as e:
                    if "deadlock" in str(e).lower():
                        if attempt < max_retries - 1:
                            time.sleep(delay * (attempt + 1))
                            continue
                    raise

        return wrapper

    return decorator