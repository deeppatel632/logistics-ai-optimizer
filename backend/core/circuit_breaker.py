# backend/core/circuit_breaker.py

import pybreaker

db_breaker = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=30,
)
