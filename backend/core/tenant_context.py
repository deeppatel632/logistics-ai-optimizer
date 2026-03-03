from contextvars import ContextVar

_current_tenant: ContextVar[int | None] = ContextVar("current_tenant", default=None)


def set_current_tenant(tenant_id: int | None):
    _current_tenant.set(tenant_id)


def get_current_tenant() -> int | None:
    return _current_tenant.get()