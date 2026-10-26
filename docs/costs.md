# Cost estimate — dev phase (approval required before provisioning)

| Item | Est. monthly | Notes |
|---|---|---|
| Supabase project `los-cloud-engine` | $0 | free tier covers dev; Pro is $25 only if dev outgrows it |
| Render web service (starter) | $7 | or equivalent on any container host |
| Render background worker (starter) | $7 | can consolidate/co-locate to cut cost |
| OpenAI API usage | ~$5–30 | usage-based at dev volume; set an account spend cap |
| GitHub private repo + Actions | $0 | within included minutes |
| Custom subdomain (optional) | ~$1 | optional |
| **Total dev phase** | **≈ $15–50/mo** | |

Not included / deferred (needs separate approval before any production scale-up):
- Production-grade Postgres (Pro), higher-traffic hosting, log retention,
  monitoring add-ons, custom domain email.
- Nothing in this estimate includes laurel-haven/Lovable costs (unchanged).

The engine tracks real per-run model usage in `usage_costs` and exposes it at
`GET /v1/costs`, so actual spend is visible from day one.
