from prometheus_client import Counter, Gauge, Histogram

# Application errors
ERROR_COUNT = Counter(
    "application_errors_total",
    "Total number of application errors"
)
# Total HTTP requests
REQUEST_COUNT = Counter(
    "app_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "http_status"]
)

# Request latency
REQUEST_LATENCY = Histogram(
    "app_request_latency_seconds",
    "Request latency in seconds",
    ["endpoint"]
)

# Active DB connections (manual tracking)
DB_CONNECTIONS = Gauge(
    "app_db_connections",
    "Active database connections"
)

# Background job count
BACKGROUND_TASKS = Counter(
    "app_background_tasks_total",
    "Total background tasks executed"
)