"""Audit trail: every privileged action lands here."""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from .auth import Principal
from .models import AuditLog


def log(session: Session, principal: Optional[Principal], action: str, entity: str = "",
        entity_id: str = "", detail: Optional[Dict[str, Any]] = None,
        org_id: Optional[str] = None) -> AuditLog:
    row = AuditLog(
        organization_id=org_id or (principal.organization_id if principal else None),
        principal_type=principal.kind if principal else "system",
        principal_id=principal.id if principal else "system",
        action=action, entity=entity, entity_id=entity_id, detail=detail or {},
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
