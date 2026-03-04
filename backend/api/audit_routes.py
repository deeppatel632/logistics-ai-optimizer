from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.core.dependencies import require_role
from backend.schemas import AuditLogResponse
from backend.services.audit_service import get_audit_logs
from database.connection import get_db

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("/", response_model=List[AuditLogResponse])
def list_audit_logs(
    entity_type: Optional[str] = None,
    user_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user = Depends(require_role("admin")),
):
    return get_audit_logs(db, entity_type, user_id, limit, offset)