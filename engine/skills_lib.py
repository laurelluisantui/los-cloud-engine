"""Git-backed Skills Library. Skills are versioned artifacts (SKILL.md + JSON
schemas + a pure-python impl) living under skills/<slug>/. Publishing writes
the files, commits to Git (best-effort), and records a SkillVersion row with a
content hash, so rollbacks restore exact prior bytes.
"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from . import config
from .models import Skill, SkillVersion

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


class SkillError(Exception):
    pass


@dataclass
class SkillDef:
    slug: str
    name: str
    version: str
    description: str
    body: str  # full SKILL.md
    schema_input: Dict[str, Any] = field(default_factory=dict)
    schema_output: Dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""


def _parse_frontmatter(md: str) -> Tuple[Dict[str, str], str]:
    m = FRONTMATTER.match(md)
    if not m:
        raise SkillError("SKILL.md missing YAML frontmatter")
    meta: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    for req in ("name", "version"):
        if req not in meta:
            raise SkillError(f"SKILL.md frontmatter missing '{req}'")
    if not SEMVER.match(meta["version"]):
        raise SkillError(f"version '{meta['version']}' is not semver")
    return meta, m.group(0)


def hash_bytes(*blobs: bytes) -> str:
    h = hashlib.sha256()
    for b in blobs:
        h.update(b)
    return h.hexdigest()


def load_skill_dir(slug: str, base: Optional[str] = None) -> SkillDef:
    root = os.path.join(base or config.SKILLS_DIR, slug)
    md_path = os.path.join(root, "SKILL.md")
    sc_path = os.path.join(root, "schema.json")
    if not os.path.isfile(md_path):
        raise SkillError(f"no SKILL.md at {md_path}")
    with open(md_path, "rb") as f:
        md_bytes = f.read()
    md = md_bytes.decode("utf-8")
    meta, _ = _parse_frontmatter(md)
    schemas = {"input": {}, "output": {}}
    sc_bytes = b""
    if os.path.isfile(sc_path):
        with open(sc_path, "rb") as f:
            sc_bytes = f.read()
        raw = json.loads(sc_bytes.decode("utf-8"))
        schemas = {"input": raw.get("input", {}), "output": raw.get("output", {})}
    return SkillDef(
        slug=slug,
        name=meta["name"],
        version=meta["version"],
        description=meta.get("description", ""),
        body=md,
        schema_input=schemas["input"],
        schema_output=schemas["output"],
        content_hash=hash_bytes(md_bytes, sc_bytes),
    )


# ------------------------------------------------------------ git helpers --
def _git(args: List[str]) -> str:
    try:
        out = subprocess.run(["git", "-C", config.REPO_ROOT] + args,
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip()
    except Exception:
        return ""


def commit_skill(slug: str, message: str) -> Optional[str]:
    if not os.path.isdir(os.path.join(config.REPO_ROOT, ".git")):
        return None
    _git(["add", os.path.join("skills", slug)])
    _git(["commit", "-m", message, "--", os.path.join("skills", slug)])
    return _git(["rev-parse", "HEAD"]) or None


def git_history(slug: str) -> List[str]:
    out = _git(["log", "--oneline", "--", os.path.join("skills", slug)])
    return [l for l in out.splitlines() if l]


# ------------------------------------------------------------- validation --
def validate(data: Any, schema: Dict[str, Any], path: str = "input") -> List[str]:
    """Minimal JSON-schema subset: type, required, properties, enum, items."""
    errors: List[str] = []
    if not schema:
        return errors
    t = schema.get("type")
    pytypes = {"object": dict, "array": list, "string": str, "number": (int, float),
               "integer": int, "boolean": bool}
    if t in pytypes and not isinstance(data, pytypes[t]):
        if t == "integer" and isinstance(data, bool):
            pass
        else:
            errors.append(f"{path}: expected {t}")
            return errors
    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}")
    if t == "object":
        for req in schema.get("required", []):
            if req not in data:
                errors.append(f"{path}.{req}: required")
        for k, sub in (schema.get("properties") or {}).items():
            if k in data:
                errors += validate(data[k], sub, f"{path}.{k}")
    if t == "array" and "items" in schema:
        for i, item in enumerate(data):
            errors += validate(item, schema["items"], f"{path}[{i}]")
    return errors


# --------------------------------------------------------------- registry --
def get_or_create_skill(session: Session, org_id: str, sd: SkillDef,
                        description: str = "") -> Skill:
    sk = session.query(Skill).filter_by(organization_id=org_id, slug=sd.slug).one_or_none()
    if sk is None:
        sk = Skill(organization_id=org_id, slug=sd.slug, name=sd.name,
                   description=description or sd.description)
        session.add(sk)
        session.commit()
        session.refresh(sk)
    return sk


def publish(session: Session, org_id: str, sd: SkillDef, created_by: str,
            approval_id: Optional[str] = None, write_files: bool = True) -> SkillVersion:
    """Publish sd as the active version of its skill. Caller MUST have passed
    the approval gate for skill.publish before calling this."""
    sk = get_or_create_skill(session, org_id, sd)
    dup = (session.query(SkillVersion)
           .filter_by(skill_id=sk.id, version=sd.version).one_or_none())
    if dup and dup.content_hash != sd.content_hash:
        raise SkillError(f"version {sd.version} already exists with different content")

    if write_files:
        root = os.path.join(config.SKILLS_DIR, sd.slug)
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(sd.body)
        with open(os.path.join(root, "schema.json"), "w", encoding="utf-8") as f:
            json.dump({"input": sd.schema_input, "output": sd.schema_output}, f, indent=2)

    sv = dup or SkillVersion(skill_id=sk.id, version=sd.version)
    sv.content_hash = sd.content_hash
    sv.body = sd.body
    sv.schema_input = sd.schema_input
    sv.schema_output = sd.schema_output
    sv.status = "published"
    sv.created_by = created_by
    sv.approval_id = approval_id
    session.add(sv)
    sk.active_version = sd.version
    session.commit()
    session.refresh(sv)
    if write_files:
        commit_skill(sd.slug, f"skill({sd.slug}): publish v{sd.version}")
    return sv


def rollback(session: Session, org_id: str, slug: str, to_version: str) -> SkillVersion:
    sk = session.query(Skill).filter_by(organization_id=org_id, slug=slug).one_or_none()
    if sk is None:
        raise SkillError("skill not found")
    target = (session.query(SkillVersion)
              .filter_by(skill_id=sk.id, version=to_version).one_or_none())
    if target is None:
        raise SkillError(f"unknown version {to_version}")
    root = os.path.join(config.SKILLS_DIR, slug)
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(target.body)
    with open(os.path.join(root, "schema.json"), "w", encoding="utf-8") as f:
        json.dump({"input": target.schema_input, "output": target.schema_output}, f, indent=2)
    sk.active_version = to_version
    target.status = "published"
    session.commit()
    commit_skill(slug, f"skill({slug}): rollback to v{to_version}")
    return target


def active_version(session: Session, org_id: str, slug: str) -> Optional[SkillVersion]:
    sk = session.query(Skill).filter_by(organization_id=org_id, slug=slug).one_or_none()
    if sk is None or sk.active_version is None:
        return None
    return (session.query(SkillVersion)
            .filter_by(skill_id=sk.id, version=sk.active_version).one_or_none())


def versions(session: Session, org_id: str, slug: str) -> List[SkillVersion]:
    sk = session.query(Skill).filter_by(organization_id=org_id, slug=slug).one_or_none()
    if sk is None:
        return []
    return (session.query(SkillVersion).filter_by(skill_id=sk.id)
            .order_by(SkillVersion.created_at.desc()).all())


def sync_library(session: Session, org_id: str) -> List[SkillVersion]:
    """Import every skill found on disk into the registry (idempotent)."""
    out: List[SkillVersion] = []
    if not os.path.isdir(config.SKILLS_DIR):
        return out
    for slug in sorted(os.listdir(config.SKILLS_DIR)):
        if not os.path.isfile(os.path.join(config.SKILLS_DIR, slug, "SKILL.md")):
            continue
        sd = load_skill_dir(slug)
        sk = get_or_create_skill(session, org_id, sd)
        existing = (session.query(SkillVersion)
                    .filter_by(skill_id=sk.id, version=sd.version).one_or_none())
        if existing is None:
            out.append(publish(session, org_id, sd, created_by="sync", write_files=False))
        elif sk.active_version is None:
            sk.active_version = sd.version
            session.commit()
    return out


# -------------------------------------------------------------- execution --
def skill_impl(slug: str, base: Optional[str] = None) -> Callable[..., Dict[str, Any]]:
    impl_path = os.path.join(base or config.SKILLS_DIR, slug, "impl.py")
    if not os.path.isfile(impl_path):
        raise SkillError(f"skill '{slug}' has no impl.py")
    spec = importlib.util.spec_from_file_location(f"skill_{slug.replace('-', '_')}", impl_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "run"):
        raise SkillError(f"skill '{slug}' impl.py must define run(context, input)")
    return mod.run


def run_skill(session: Session, org_id: str, slug: str, input_data: Dict[str, Any],
              context: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Execute the active version of slug. Returns (output, version)."""
    sv = active_version(session, org_id, slug)
    if sv is None:
        raise SkillError(f"skill '{slug}' is not published for this organization")
    errors = validate(input_data, sv.schema_input)
    if errors:
        raise SkillError("invalid input: " + "; ".join(errors))
    fn = skill_impl(slug)
    output = fn(context, input_data)
    out_errors = validate(output, sv.schema_output, path="output")
    if out_errors:
        raise SkillError("skill output failed schema: " + "; ".join(out_errors))
    return output, sv.version
