"""Authentication & authorization. Permissions are enforced here, in backend
code, never delegated to model instructions.

- Humans: Supabase JWT (laurel-haven session) -> must hold the `owner` role.
- Machines: `X-Engine-Key` scoped API keys stored as sha256 hashes.
"""
import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import httpx
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import config
from .db import get_session
from .models import ApiKey


# Fine-grained permission classes. Approval-sensitive classes are separately
# gated by permissions.requires_approval().
ALL_PERMISSIONS = [
    "chat",
    "agent.read",
    "agent.manage",
    "task.create",
    "task.read",
    "skill.read",
    "skill.write",
    "skill.publish",
    "skill.rollback",
    "schedule.manage",
    "cost.read",
    "approval.decide",
]


@dataclass
class Principal:
    kind: str  # "owner" | "machine"
    id: str
    organization_id: str
    permissions: List[str] = field(default_factory=list)
    display: str = ""

    def can(self, perm: str) -> bool:
        if self.kind == "owner":
            return perm in ALL_PERMISSIONS  # owner has every class
        return perm in self.permissions


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- Supabase --
def verify_supabase_token(token: str) -> Dict[str, Any]:
    """Validate a Supabase access token and confirm the owner role.
    Kept as a module-level function so tests can patch it."""
    if not (config.SUPABASE_URL and config.SUPABASE_PUBLISHABLE_KEY):
        raise HTTPException(503, "Supabase auth is not configured on the engine")
    headers = {"apikey": config.SUPABASE_PUBLISHABLE_KEY, "Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=10) as client:
        r = client.get(f"{config.SUPABASE_URL}/auth/v1/user", headers=headers)
        if r.status_code != 200:
            raise HTTPException(401, "Invalid Supabase token")
        user = r.json()
        role_r = client.get(
            f"{config.SUPABASE_URL}/rest/v1/user_roles",
            params={"user_id": f"eq.{user['id']}", "role": "eq.owner", "select": "role"},
            headers={**headers, "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
                     "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}"},
        ) if config.SUPABASE_SERVICE_ROLE_KEY else None
        roles = role_r.json() if role_r is not None and role_r.status_code == 200 else []
    if not roles:
        raise HTTPException(403, "Muffy is owner-only")
    return user


# ------------------------------------------------------------ dependencies --
def get_org_id(session: Session) -> str:
    from .models import Organization

    org = session.query(Organization).filter_by(slug=config.DEFAULT_ORG).one_or_none()
    if org is None:
        org = Organization(slug=config.DEFAULT_ORG, name="Laurel / FORM + LOGIC")
        session.add(org)
        session.commit()
        session.refresh(org)
    return org.id


def get_principal(request: Request, session: Session = Depends(get_session)) -> Principal:
    engine_key = request.headers.get("x-engine-key")
    if engine_key:
        row = (
            session.query(ApiKey)
            .filter_by(key_hash=hash_key(engine_key), revoked_at=None)
            .one_or_none()
        )
        if not row:
            raise HTTPException(401, "Invalid engine key")
        return Principal(kind="machine", id=f"key:{row.name}", organization_id=row.organization_id,
                         permissions=list(row.scopes or []), display=row.name)

    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if token:
        user = verify_supabase_token(token)
        return Principal(kind="owner", id=user["id"], organization_id=get_org_id(session),
                         permissions=list(ALL_PERMISSIONS),
                         display=user.get("email") or user["id"])
    raise HTTPException(401, "Authentication required")


def require(perm: str) -> Callable[[Principal], Principal]:
    def checker(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.can(perm):
            raise HTTPException(403, f"Missing permission: {perm}")
        return principal

    return checker
