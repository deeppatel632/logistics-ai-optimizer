from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from backend.core.security import decode_token
from backend.core.tenant_context import set_current_tenant

class TenantMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        tenant_id = None
        auth_header = request.headers.get("Authorization")

        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                payload = decode_token(token)
                tenant_id = payload.get("tenant_id")
            except Exception:
                pass

        set_current_tenant(tenant_id)

        response = await call_next(request)

        # Clear after request
        set_current_tenant(None)

        return response