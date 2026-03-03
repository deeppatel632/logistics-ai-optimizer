from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database.connection import get_db
from backend.services.audit_service import get_audit_logs
from backend.schemas import AuditLogResponse
from backend.core.dependencies import require_role

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("/", response_model=list[AuditLogResponse])
def list_audit_logs(
    entity_type: str | None = None,
    user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user = Depends(require_role("admin")),
):
    return get_audit_logs(db, entity_type, user_id, limit, offset)