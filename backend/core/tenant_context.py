from contextvars import ContextVar
from typing import Optional

_current_tenant: ContextVar[Optional[int]] = ContextVar("current_tenant", default=None)


def set_current_tenant(tenant_id: Optional[int]) -> None:
    _current_tenant.set(tenant_id)


def get_current_tenant() -> Optional[int]:
    return _current_tenant.get()