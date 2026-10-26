"""proposal-drafting: build a review-only proposal from supplied findings.

With a model provider, the draft is model-written but forced to cite finding
indexes; drafts citing nonexistent findings are rejected and fall back to the
deterministic template. Dev mode uses the deterministic template directly.
"""
import json
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


def _model_draft(provider, business_name, website, findings, services):
    numbered = "\n".join(f"[finding {i}] {f['claim']} (source: {f['evidence_url']})"
                         for i, f in enumerate(findings, 1))
    instructions = (
        "Draft a one-page business proposal in Markdown for FORM + LOGIC (web, "
        "automation, content services). Use ONLY the supplied findings for factual "
        "claims and cite them inline as [finding N]. Pricing, dates and unverified "
        "facts must appear as [BRACKETED PLACEHOLDERS]. Return JSON: "
        "{\"proposal_markdown\": str}. The proposal is a draft for human review; "
        "never imply anything has been sent or agreed."
    )
    result = provider.complete(
        instructions,
        f"Business: {business_name}\nWebsite: {website}\nServices: {', '.join(services)}\n\n"
        f"Findings:\n{numbered or '(none supplied)'}",
    )
    try:
        md = json.loads(result.text)["proposal_markdown"]
    except (json.JSONDecodeError, KeyError):
        return None, result
    return md, result


def run(context, input):
    provider = context.get("provider")
    business_name, website = input["business_name"], input["website"]
    findings = list(input["findings"])
    services = list(input.get("services") or BASE_SERVICES)

    md = None
    if getattr(provider, "name", "dev") != "dev" and provider is not None:
        md, result = _model_draft(provider, business_name, website, findings, services)
        from engine.providers import estimate_cost_usd
        context["usage"] = {
            "provider": result.provider, "model": result.model,
            "tokens_in": result.tokens_in, "tokens_out": result.tokens_out,
            "cost_usd": estimate_cost_usd(result.model, result.tokens_in, result.tokens_out),
        }
        # Reject model drafts that cite findings that don't exist.
        max_cited = max([int(m.group(1)) for m in _CITE.finditer(md)] or [0]) if md else 0
        if md is None or max_cited > len(findings):
            md = None
    if md is None:
        md = _template(business_name, website, findings, services)
    return {
        "proposal_markdown": md,
        "placeholders": _placeholders(md),
        "based_on_findings": _cited_count(md, len(findings)),
    }
