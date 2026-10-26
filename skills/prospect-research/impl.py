"""prospect-research implementation.

Evidence rule enforced in code: a finding only survives if its source_excerpt
is a verbatim substring of the page it cites. Dev mode (no model key) extracts
deterministic facts (title, meta description) from the real fetched HTML.
"""
import json
import re
from html import unescape

_TAG = re.compile(r"<[^>]+>")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META_DESC = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', re.I | re.S)


def _text(html, limit=20000):
    body = unescape(_TAG.sub(" ", html))
    return re.sub(r"\s+", " ", body).strip()[:limit]


def _excerpt(page_text, needle):
    idx = page_text.lower().find(needle.lower())
    if idx < 0:
        return None
    return page_text[max(0, idx - 60): idx + len(needle) + 60].strip()


def _record_usage(context, result):
    if result is None:
        return
    from engine.providers import estimate_cost_usd
    context["usage"] = {
        "provider": result.provider, "model": result.model,
        "tokens_in": result.tokens_in, "tokens_out": result.tokens_out,
        "cost_usd": estimate_cost_usd(result.model, result.tokens_in, result.tokens_out),
    }


def _dev_findings(page_text, html, url, business_name):
    findings, notes = [], []
    m = _TITLE.search(html)
    if m:
        title = _text(m.group(1))
        ex = _excerpt(page_text, title)
        if ex:
            findings.append({"claim": f"The site presents itself as: {title}",
                             "evidence_url": url, "source_excerpt": ex})
    else:
        notes.append("No <title> found on the homepage.")
    m = _META_DESC.search(html)
    self_desc = None
    if m:
        self_desc = _text(m.group(1))
        ex = _excerpt(page_text, self_desc)
        if ex:
            findings.append({"claim": f"Self-description meta tag says: {self_desc}",
                             "evidence_url": url, "source_excerpt": ex})
    if business_name.lower() in page_text.lower():
        ex = _excerpt(page_text, business_name)
        if ex:
            findings.append({"claim": f"Business name '{business_name}' appears on the homepage",
                             "evidence_url": url, "source_excerpt": ex})
    else:
        notes.append(f"Business name '{business_name}' not found verbatim on the homepage.")
    if not self_desc:
        notes.append("No meta description found; positioning unclear from the homepage.")
    return findings, notes


def _model_findings(provider, page_text, url, business_name):
    instructions = (
        "You extract evidence-based findings about a business from its public website text. "
        "Return JSON: {\"findings\": [{\"claim\": str, \"excerpt\": str}], \"notes\": [str]}. "
        "Every excerpt MUST be a verbatim substring of the provided text. Max 5 findings. "
        "Never invent facts; missing info goes in notes."
    )
    result = provider.complete(
        instructions,
        f"Business: {business_name}\nWebsite: {url}\n\nPage text:\n{page_text}",
    )
    try:
        data = json.loads(result.text)
    except json.JSONDecodeError:
        return [], ["Model did not return parseable JSON; no findings recorded."], result
    findings, notes = [], list(data.get("notes") or [])
    for f in (data.get("findings") or [])[:5]:
        claim, excerpt = str(f.get("claim", "")), str(f.get("excerpt", ""))
        if not claim or not excerpt:
            continue
        verified = _excerpt(page_text, excerpt)
        if verified:
            findings.append({"claim": claim, "evidence_url": url, "source_excerpt": verified})
        else:
            notes.append(f"Dropped unverifiable claim: {claim[:80]}")
    return findings, notes, result


def run(context, input):
    fetch = context["fetch"]
    provider = context.get("provider")
    url = input["website"]
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    urls = [url] + [u if u.startswith(("http://", "https://")) else "https://" + u
                    for u in input.get("extra_urls", [])[:3]]
    html = fetch(url)
    page_text = _text(html)
    if getattr(provider, "name", "dev") == "dev" or provider is None:
        findings, notes = _dev_findings(page_text, html, url, input["business_name"])
        notes.append("Dev provider: findings are deterministic extractions, not AI analysis.")
        result = None
    else:
        findings, notes, result = _model_findings(provider, page_text, url,
                                                  input["business_name"])
    _record_usage(context, result)
    for extra in urls[1:]:
        try:
            page_text += " " + _text(fetch(extra))
        except Exception as exc:  # noqa: BLE001 - note, don't fail the run
            notes.append(f"Could not fetch {extra}: {exc}")
    return {"findings": findings, "notes": notes}
