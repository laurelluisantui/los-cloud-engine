"""Skill artifacts themselves: SKILL.md frontmatter, schemas, and impl output
conformance for all three shipped skills."""
import json

import pytest

from engine.providers import DevProvider
from engine.skills_lib import (SkillError, active_version, load_skill_dir,
                               run_skill, validate)
from tests.conftest import SAMPLE_HTML, fake_fetch

SKILLS = ["prospect-research", "prospect-website-audit", "proposal-drafting"]


@pytest.mark.parametrize("slug", SKILLS)
def test_skill_files_parse(slug):
    sd = load_skill_dir(slug)
    assert sd.version and sd.name and sd.body.startswith("---")
    assert sd.schema_input.get("type") == "object"
    assert sd.schema_output.get("type") == "object"


def test_research_input_validation(client, owner_headers, seeded):
    from engine.auth import get_org_id
    from engine.db import SessionLocal
    session = SessionLocal()
    with pytest.raises(SkillError):
        run_skill(session, get_org_id(session), "prospect-research",
                  {"business_name": "x"},  # missing website
                  {"provider": DevProvider()})
    session.close()


def _ctx():
    return {"provider": DevProvider(), "fetch": fake_fetch(), "organization_id": "org"}


def test_website_audit_output_conforms(client, owner_headers, seeded):
    from engine.auth import get_org_id
    from engine.db import SessionLocal
    session = SessionLocal()
    out, _ = run_skill(session, get_org_id(session), "prospect-website-audit",
                       {"website": "https://bluebonnetdental.example"}, _ctx())
    session.close()
    names = {c["name"]: c["result"] for c in out["checks"]}
    assert names["https"] == "pass"
    assert names["title"] == "pass"
    assert names["meta_description"] == "pass"
    assert names["contact_phone"] == "pass"
    assert "passed" in out["summary"]


def test_proposal_uses_findings_and_placeholders(client, owner_headers, seeded):
    from engine.auth import get_org_id
    from engine.db import SessionLocal
    session = SessionLocal()
    research, _ = run_skill(session, get_org_id(session), "prospect-research",
                            {"business_name": "Bluebonnet Dental",
                             "website": "https://bluebonnetdental.example"}, _ctx())
    out, _ = run_skill(session, get_org_id(session), "proposal-drafting",
                       {"business_name": "Bluebonnet Dental",
                        "website": "https://bluebonnetdental.example",
                        "findings": research["findings"]}, _ctx())
    session.close()
    assert "DRAFT" in out["proposal_markdown"]
    assert out["based_on_findings"] >= 1
    assert any("PRICE" in p for p in out["placeholders"])
    for ph in out["placeholders"]:
        assert len(ph) >= 2


def test_schema_validator():
    schema = {"type": "object", "required": ["a"],
              "properties": {"a": {"type": "string"},
                             "b": {"type": "array", "items": {"type": "integer"}}}}
    assert validate({"a": "x", "b": [1, 2]}, schema) == []
    errors = validate({"b": [1, "no"]}, schema)
    assert any("a" in e and "required" in e for e in errors)
    assert any("b[1]" in e for e in errors)
