"""Seed the engine: organization, skill registry sync, agent registry entries.
Idempotent — safe to run on every deploy. Does not mint keys or touch secrets."""
from . import config
from .auth import ALL_PERMISSIONS, Principal, get_org_id
from .db import SessionLocal, engine as db_engine
from .models import Agent, Base
from .skills_lib import sync_library
from .tools import register_agent


def seed() -> None:
    Base.metadata.create_all(db_engine)
    session = SessionLocal()
    try:
        org_id = get_org_id(session)
        system = Principal(kind="system", id="seed", organization_id=org_id,
                           permissions=list(ALL_PERMISSIONS))
        synced = sync_library(session, org_id)
        for slug, name, kind, desc, skills, perms in [
            ("muffy", "Muffy (Supervisor)", "orchestrator",
             "Owner-only executive orchestrator. Delegates to specialist agents, "
             "manages skills/schedules, never fabricates status.", [],
             ["orchestrate"]),
            ("sales-research", "FORM + LOGIC Sales Research Agent", "specialist",
             "Respects evidence: researches public information, audits the "
             "prospect's website and drafts proposals for human review. "
             "No outreach, no external writes.",
             ["prospect-research", "prospect-website-audit", "proposal-drafting"],
             ["research.public"]),
        ]:
            existing = (session.query(Agent)
                        .filter_by(organization_id=org_id, slug=slug).one_or_none())
            if existing is None:
                register_agent(session, system, slug, name, kind, desc, skills, perms)
        print(f"seeded org={org_id} skills_synced={len(synced)}")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
