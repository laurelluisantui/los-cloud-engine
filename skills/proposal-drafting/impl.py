"""proposal-drafting: build a review-only proposal from supplied findings.

The template is deterministic. Checking citation numbers in model-written
prose cannot prove other claims are true, so v0.1 does not use a model here.
"""
import re

_BRACKET = re.compile(r"\[([^\[\]<>]{2,80})\]")
_CITE = re.compile(r"\[finding (\d+)\]", re.I)

BASE_SERVICES = ["Website modernization", "Automation & systems", "Content engine"]


def _template(business_name, website, findings, services):
    lines = [
        f"# Draft Proposal — {business_name}",
        "",
        "_DRAFT for Laurel's review. Not sent to anyone._",
        "",
        "## What we verified",
    ]
    for i, f in enumerate(findings, 1):
        lines.append(f"- {f['claim']} (source: {f['evidence_url']}) [finding {i}]")
    if not findings:
        lines.append("- No verified findings supplied. [Research needed]")
    lines += ["", "## Proposed work (FORM + LOGIC)"]
    for s in services:
        lines.append(f"- {s} — scope and deliverables [SCOPE TBD], price [PRICE TBD]")
    lines += [
        "",
        "## Timeline",
        "Start date [START DATE TBD]; first milestone [MILESTONE TBD].",
        "",
        "## Next step",
        "A short call to confirm scope. Contact sent only after Laurel approves.",
    ]
    return "\n".join(lines)


def _placeholders(markdown):
    return sorted(set(m.group(1) for m in _BRACKET.finditer(markdown)))


def _cited_count(markdown, n_findings):
    return len({int(m.group(1)) for m in _CITE.finditer(markdown)
                if 1 <= int(m.group(1)) <= n_findings})


def run(context, input):
    business_name, website = input["business_name"], input["website"]
    findings = list(input["findings"])
    services = list(input.get("services") or BASE_SERVICES)
    md = _template(business_name, website, findings, services)
    return {
        "proposal_markdown": md,
        "placeholders": _placeholders(md),
        "based_on_findings": _cited_count(md, len(findings)),
    }
