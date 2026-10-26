---
name: prospect-research
version: 0.1.0
description: Research a prospect's publicly available information and produce evidence-based findings. Every finding must quote a source excerpt from fetched public pages.
---

# prospect-research

## Purpose
Given a business name and website, gather publicly available information and
return findings where **every claim is backed by a verbatim source excerpt**
from a fetched public page. No inference without evidence, no outreach, no
account modifications.

## Input
See `schema.json` → `input`: `business_name`, `website` required.

## Output
See `schema.json` → `output`: `findings[]` with `claim`, `evidence_url`,
`source_excerpt`; plus `notes`.

## Rules
- Fetch only public http(s) pages on public hosts (the runtime blocks private
  networks and caps payload size).
- A finding is valid only if its `source_excerpt` appears verbatim in a fetched
  page. The implementation verifies this in code and drops unverifiable claims.
- Unknowns must be reported in `notes`, never guessed.
- No contact attempts, no form submissions, no logins.
