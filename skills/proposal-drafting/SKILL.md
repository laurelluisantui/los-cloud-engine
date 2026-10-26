---
name: proposal-drafting
version: 0.1.0
description: Draft a proposal for human review from verified research findings. Never invents prices or facts; unknowns are written as [bracketed placeholders]. Output is a draft only — nothing is sent.
---

# proposal-drafting

## Purpose
Combine evidence-based findings (from `prospect-research` / a site audit) into
a draft proposal Markdown for FORM + LOGIC services. The draft is for **human
review only**; this skill never sends anything.

## Input
`schema.json` → `input`: `business_name`, `website`, `findings[]`, optional
`services[]`.

## Output
`schema.json` → `output`: `proposal_markdown`, `placeholders[]`,
`based_on_findings` (count).

## Rules
- Every concrete claim in the proposal must trace to a supplied finding; the
  implementation counts citations and reports them.
- Pricing, dates, and client-specific facts that were not supplied are written
  as `[…]` placeholders and listed in `placeholders[]`.
- No exclusivity guarantees, no invented metrics.
