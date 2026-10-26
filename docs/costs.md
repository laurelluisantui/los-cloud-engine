# Cost estimate — dev phase (approval required before provisioning)

Rechecked against [Render pricing](https://render.com/pricing) and
[OpenAI API pricing](https://developers.openai.com/api/docs/pricing) on
October 26, 2026. This is a budget estimate, not authorization to buy.

| Item | Est. monthly | Notes |
|---|---|---|
| Supabase project `los-cloud-engine` | $0 | free tier covers dev; Pro is $25 only if dev outgrows it |
| Render web service (starter) | $7 | always-on API; staging choice, not yet provisioned |
| Render background worker (starter) | $7 | persistent queue polling |
| OpenAI API usage | $5–30 proposed cap | usage-based; owner must approve cap before any key-backed calls |
| GitHub private repo + Actions | $0 | within included minutes |
| Custom subdomain (optional) | ~$1 | optional |
| **Total dev phase** | **≈ $19–44/mo** | before optional extras or plan changes |

Not included / deferred (needs separate approval before any production scale-up):
- Production-grade Postgres (Pro), higher-traffic hosting, log retention,
  monitoring add-ons, custom domain email.
- Nothing in this estimate includes laurel-haven/Lovable costs (unchanged).

The engine tracks token usage and **estimated** model cost in `usage_costs` and
exposes it at `GET /v1/costs`; provider billing remains authoritative.
The default is `gpt-5.4-mini` (published rate $0.75/1M input tokens and
$4.50/1M output tokens as of the linked price page). Confirm account access
and model compatibility in staging before the first live model call.
