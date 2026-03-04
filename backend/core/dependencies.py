from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database.connection import get_db
from fastapi import Request
from database.models import User
from backend.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    try:
        payload = decode_token(token)
        username = payload.get("sub")
        tenant_id = payload.get("tenant_id")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(
        User.username == username,
        User.tenant_id == tenant_id
    ).first()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


def require_role(required_role: str):
    def role_checker(user: User = Depends(get_current_user)):
        if user.role != required_role:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
    return role_checker


def get_current_tenant_id(request: Request):
    if not request.state.tenant_id:
        raise HTTPException(status_code=401, detail="Tenant context missing")
    return request.state.tenant_id