"""prospect-website-audit: deterministic homepage checks with verbatim evidence."""
import re

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META_DESC = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', re.I | re.S)
_VIEWPORT = re.compile(r'<meta[^>]+name=["\']viewport["\']', re.I)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}")
_TAG = re.compile(r"<[^>]+>")


def run(context, input):
    fetch = context["fetch"]
    url = input["website"]
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    html = fetch(url)
    text = re.sub(r"\s+", " ", _TAG.sub(" ", html))

    def check(name, ok, evidence=""):
        return {"name": name, "result": "pass" if ok else "fail",
                "evidence": (evidence or "")[:300]}

    title = _TITLE.search(html)
    desc = _META_DESC.search(html)
    email = _EMAIL.search(text)
    phone = _PHONE.search(text)
    checks = [
        check("https", url.startswith("https://"), url.split("://", 1)[0] + "://"),
        {"name": "title", "result": "pass" if title else "fail",
         "evidence": title.group(1).strip()[:300] if title else ""},
        {"name": "meta_description", "result": "pass" if desc else "fail",
         "evidence": desc.group(1).strip()[:300] if desc else ""},
        check("mobile_viewport", bool(_VIEWPORT.search(html)),
              "viewport meta present" if _VIEWPORT.search(html) else ""),
        {"name": "contact_email", "result": "pass" if email else "unknown",
         "evidence": email.group(0) if email else ""},
        {"name": "contact_phone", "result": "pass" if phone else "unknown",
         "evidence": phone.group(0) if phone else ""},
        check("has_body_text", len(text.strip()) > 200,
              f"{len(text.strip())} characters of visible text"),
    ]
    passed = sum(1 for c in checks if c["result"] == "pass")
    failed = [c["name"] for c in checks if c["result"] == "fail"]
    summary = (f"{passed}/{len(checks)} checks passed."
               + (f" Failures: {', '.join(failed)}." if failed else ""))
    return {"checks": checks, "summary": summary}
