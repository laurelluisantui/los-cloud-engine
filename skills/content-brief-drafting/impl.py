"""Review-only Content Agent skill; no model or external account access."""


def run(context, input):
    from engine.skills_lib import _parse_frontmatter

    meta, _ = _parse_frontmatter(context["skill_instructions"])
    if meta.get("format", "paragraph") not in ("paragraph", "bullets"):
        raise ValueError("unsupported content brief format")
    topic = input.get("topic") or "[TOPIC TO CONFIRM]"
    placeholders = ["VERIFIED CLAIM", "REVIEWED CTA"]
    if topic.startswith("["):
        placeholders.insert(0, "TOPIC TO CONFIRM")
    paragraph = (
            f"Content brief for {input['business_name']}: {topic}\n"
            f"Account reference: {input['website']}\n"
            "Angle: [VERIFIED CLAIM]\n"
            "Call to action: [REVIEWED CTA]\n"
            "Draft only. Nothing has been scheduled or published."
    )
    if meta.get("format") == "bullets":
        draft = "\n".join("- " + line for line in paragraph.splitlines())
    else:
        draft = paragraph
    return {
        "draft": draft,
        "placeholders": placeholders,
    }
