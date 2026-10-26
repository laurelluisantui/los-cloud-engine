"""Approval gating. Destructive, financial, publishing, and external-communication
actions never execute directly: an Approval row is created and the action runs
only after an owner approves it."""
import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from .models import Approval, utcnow

# Action classes that always require an explicit owner approval before running.
APPROVAL_REQUIRED = {
    "skill.publish",
    "skill.rollback",
    "data.destructive",
    "financial",
    "publishing",
    "external_comms",
    "deploy",
    "permission.escalation",
}


def requires_approval(action: str) -> bool:
    return action in APPROVAL_REQUIRED


def create_approval(session: Session, org_id: str, action: str, payload: Dict[str, Any],
                    requested_by: str, task_id: str = None) -> Approval:
    ap = Approval(organization_id=org_id, action=action, payload=payload,
                  requested_by=requested_by, task_id=task_id)
    session.add(ap)
    session.commit()
    session.refresh(ap)
    return ap


def list_pending(session: Session, org_id: str) -> List[Approval]:
    return (
        session.query(Approval)
        .filter_by(organization_id=org_id, status="pending")
        .order_by(Approval.created_at.asc())
        .all()
    )


def decide(session: Session, org_id: str, approval_id: str, approve: bool,
           decided_by: str) -> Approval:
    ap = session.query(Approval).filter_by(id=approval_id, organization_id=org_id).one_or_none()
    if ap is None:
        raise KeyError("approval not found")
    if ap.status != "pending":
        raise ValueError(f"approval already {ap.status}")
    ap.status = "approved" if approve else "rejected"
    ap.decided_by = decided_by
    ap.decided_at = datetime.datetime.utcnow()
    session.commit()
    session.refresh(ap)
    return ap
