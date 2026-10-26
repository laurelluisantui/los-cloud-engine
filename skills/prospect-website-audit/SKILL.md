---
name: prospect-website-audit
version: 0.1.0
description: Audit a prospect's public website for basic presence/quality signals (HTTPS, title, meta description, mobile viewport, contact paths). Deterministic checks with quoted evidence.
---

# prospect-website-audit

## Purpose
Fetch the prospect's public homepage and run deterministic quality checks.
Every check reports a `pass`/`fail`/`unknown` plus the exact evidence string
observed. No logins, no form submissions.

## Input
`schema.json` → `input`: `website` required.

## Output
`schema.json` → `output`: `checks[]` with `name`, `result`, `evidence`; plus
`summary`.

## Rules
- Checks are deterministic string/markup tests — they never guess.
- Evidence strings are verbatim from the fetched document (or empty).
- Private hosts are refused by the runtime fetch.
