from prometheus_client import Counter, Histogram

# Total HTTP requests
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status"]
)

# Request latency histogram
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"]
)

# Application errors
ERROR_COUNT = Counter(
    "application_errors_total",
    "Total number of application errors"
)