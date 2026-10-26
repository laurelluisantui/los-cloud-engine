"""Disposable PostgreSQL CI integration test; never run against production.

Uses a newly created empty DB and an application role without BYPASSRLS.
Fails if tenant context is absent, wrong, or not reapplied after commit.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from engine.auth import get_org_id, hash_key
from engine.db import SessionLocal, scope_session
from engine.models import Agent, ApiKey, Conversation, Message, Organization, Task
from engine.seed import seed


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    seed()
    s = SessionLocal()
    try:
        role = s.execute(text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )).one()
        check(role == (False, False), "app role must not bypass RLS")
        flags = s.execute(text(
            "SELECT relrowsecurity, relforcerowsecurity "
            "FROM pg_class WHERE relname = 'tasks'"
        )).one()
        check(flags == (True, True), "tasks RLS must be enabled and forced")
        check(s.query(Agent).all() == [], "unscoped agent read leaked rows")
        org_a = get_org_id(s)
        org_b_row = Organization(slug="rls-other-org", name="RLS other")
        s.add(org_b_row)
        s.commit()
        org_b = org_b_row.id
        s.rollback()

        scope_session(s, org_a, "owner-a")
        agent = s.query(Agent).filter_by(slug="sales-research").one()
        agent_id = agent.id
        task = Task(organization_id=org_a, agent_id=agent_id,
                    skill_slug="prospect-research", status="queued", input={})
        conv = Conversation(organization_id=org_a, owner_user_id="owner-a")
        key = ApiKey(organization_id=org_a, name="ci-key",
                     key_hash=hash_key("losk_ci_only"), scopes=["task.read"])
        s.add_all([task, conv, key])
        s.commit()
        task_id, conv_id, key_hash = task.id, conv.id, key.key_hash
        s.add(Message(conversation_id=conv_id, role="user", content="private"))
        s.commit()
        check(s.query(Task).filter_by(id=task_id).one_or_none() is not None,
              "own tenant read failed after commit")
        check(s.query(Message).count() == 1, "owner memory read failed")
        s.rollback()

        scope_session(s, org_b, "owner-b")
        check(s.query(Agent).count() == 0, "other tenant's agents leaked")
        check(s.query(Task).filter_by(id=task_id).one_or_none() is None,
              "other tenant's task leaked")
        check(s.query(Conversation).filter_by(id=conv_id).one_or_none() is None,
              "other tenant's memory leaked")
        check(s.query(ApiKey).filter_by(key_hash=key_hash).one_or_none() is None,
              "other tenant's API key leaked")
        s.rollback()

        scope_session(s, org_a, "owner-b")
        check(s.query(Conversation).filter_by(id=conv_id).one_or_none() is None,
              "same tenant, different owner read private memory")
        check(s.query(Message).count() == 0, "private messages leaked")
        s.rollback()

        # A scoped connection cannot write a row for another organization.
        scope_session(s, org_b, "owner-b")
        s.add(Task(organization_id=org_a, agent_id=agent_id,
                   skill_slug="prospect-research", status="queued", input={}))
        try:
            s.commit()
            raise AssertionError("cross-tenant insert unexpectedly succeeded")
        except DBAPIError:
            s.rollback()

        # Machine-key lookup is allowed only for the exact hash, before org
        # context exists. It grants no blanket access to tenant tables.
        s.info.pop("organization_id", None)
        s.info.pop("user_id", None)
        s.info["api_key_hash"] = key_hash
        check(s.query(ApiKey).filter_by(key_hash=key_hash).one_or_none() is not None,
              "exact API key lookup failed")
        check(s.query(Task).all() == [], "key bootstrap leaked tenant tasks")
        s.rollback()
        print("PostgreSQL RLS verified: missing/wrong context denied, owner memory isolated.")
    finally:
        s.close()


if __name__ == "__main__":
    main()
