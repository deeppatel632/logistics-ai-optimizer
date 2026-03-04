# tests/test_inventory.py
#
# Pure-unit tests for security helpers and tenant context.
# No database, Redis, or network dependencies — safe for CI.

import pytest

from backend.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from backend.core.tenant_context import get_current_tenant, set_current_tenant


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_hash_returns_non_empty_string(self):
        hashed = hash_password("my_secret")
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_hash_differs_from_plain_text(self):
        plain = "my_secret"
        assert hash_password(plain) != plain

    def test_verify_correct_password(self):
        plain = "correct_horse_battery_staple"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("the_right_one")
        assert verify_password("the_wrong_one", hashed) is False

    def test_two_hashes_of_same_password_differ(self):
        """bcrypt uses a per-hash salt — equal inputs must not equal outputs."""
        pw = "same_password"
        assert hash_password(pw) != hash_password(pw)


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------

class TestJWT:
    def test_encode_decode_round_trip(self):
        payload = {"sub": "user_42", "tenant_id": 7}
        token = create_access_token(payload)
        decoded = decode_token(token)
        assert decoded["sub"] == "user_42"
        assert decoded["tenant_id"] == 7

    def test_token_is_string(self):
        token = create_access_token({"sub": "u1"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_exp_claim_is_present(self):
        token = create_access_token({"sub": "u2"})
        decoded = decode_token(token)
        assert "exp" in decoded

    def test_different_payloads_produce_different_tokens(self):
        t1 = create_access_token({"sub": "user_1"})
        t2 = create_access_token({"sub": "user_2"})
        assert t1 != t2


# ---------------------------------------------------------------------------
# Tenant context (ContextVar)
# ---------------------------------------------------------------------------

class TestTenantContext:
    def test_default_is_none(self):
        set_current_tenant(None)
        assert get_current_tenant() is None

    def test_set_and_get(self):
        set_current_tenant(99)
        assert get_current_tenant() == 99

    def test_overwrite_value(self):
        set_current_tenant(1)
        set_current_tenant(2)
        assert get_current_tenant() == 2

    def test_reset_to_none(self):
        set_current_tenant(5)
        set_current_tenant(None)
        assert get_current_tenant() is None
