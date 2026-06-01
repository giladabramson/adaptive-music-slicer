# Open-core strategy

A note to future me (and anyone contributing) about what stays public in this
repo and what belongs in the eventual private hosted-service repo.

## The model — open core (decided 2026-05-30)

This repo (`adaptive-music-slicer`) is the **open-source engine**, MIT
licensed. A separate, private repo will eventually hold the **hosted-service
code**: authentication, queue management, per-customer dashboard, billing,
prompt library, anything that runs as a server for paying customers.

This is the playbook used by Plausible, PostHog, Resend, Supabase, Sentry,
Modal, and many others. The engine being open builds trust with the dev
audience and brings organic traffic. The hosted service is the thing that's
worth paying for — because nobody actually wants to provision GPUs, manage
Lyria keys, or operate Python.

## Why the boundary matters

Once a hosted version exists, every commit needs a single answer to "does
this go in the open repo or the closed one?" If we get this wrong we either
(a) leak the moat into the public repo or (b) close off something that should
have stayed open for credibility. The line below is the reference.

## What lives where

### Public (this repo, MIT)

- `adaptive_music_engine/` — the CLI engine: pipeline, separation, slicing,
  generation backends, analysis, metadata, errors
- `adaptive_player.py` — the desktop reference player (Tkinter + sounddevice)
- `landing/` — the marketing landing page source (HTML/CSS/JS, demo assets)
- `scripts/` — `compare_separators.py`, `play_comparison.py`, anything
  diagnostic
- Example songs / fixtures used in the landing demo
- Tests (when they exist)
- All engine-side documentation
- This file

### Private (future `adaptive-music-hosted` repo)

- API server (likely FastAPI or Modal endpoints) wrapping the engine
- Job queue + worker management + GPU pool orchestration
- Auth, accounts, sessions
- Billing (Stripe wrap), subscription management, usage metering
- Web dashboard / customer-facing UI (separate from this `landing/`)
- **Prompt library / presets / templates** — curation IS the moat for an
  AI-product. The engine can generate any music; what's hard is knowing
  which prompts produce shippable game audio per genre/mood. That belongs
  in the closed repo.
- Per-customer storage, history, audit logs, content moderation hooks
- Customer-facing analytics dashboards (separate from landing-page
  Vercel Analytics, which is fine to keep public)
- Marketing landing pages for the paid product (when they exist)

## Rule of thumb

> Anything an experienced game dev could rebuild in a weekend stays public.
> Anything that's operational glue, customer-facing convenience, or curated
> domain knowledge stays private.

## Things that must not leak into this repo

- API keys, OAuth tokens, service credentials (already in `~/.*` dirs and
  gitignored — keep it that way; never inline)
- Customer data (none yet — and when there is, it lives in the private repo
  and a real database, not files)
- Hosted-service source code (until the private repo exists, none should be
  written; when it exists, anything server-side goes there)
- Internal-only prompt templates / fine-tunings that we want to charge for

## When the hosted version starts

1. Create `adaptive-music-hosted` as a private repo, separate organisation or
   personal scope is fine.
2. Decide on the API contract between hosted-service and engine. Likely the
   hosted service imports `adaptive_music_engine` as a pip dependency, pinned
   to a tag of this repo.
3. Pin a version of this repo, tag a release (`v0.1.0` etc), so the hosted
   repo can depend on a stable engine.
4. Update [landing/index.html](landing/index.html) interest section to point
   at the real signup / waitlist URL once the hosted version exists.
5. Update this file with the actual private-repo name and any boundary
   adjustments learned by then.

## What this means for the landing page

The landing page (`landing/`) is in the public repo because:

- It sells *both* the open engine ("try it locally today") and the future
  hosted version ("get notified when it's hosted")
- Anything secret on the landing page (Formspree form ID, Vercel Analytics
  IDs) is either embedded in the deployed environment or a tokenised
  placeholder, never a real secret in source

The hosted product, when it has its own dashboard / signup flow, will get
its own separate marketing page in the private repo. The two co-exist.

## What changes today

Nothing technical. The landing page already has the right shape (open
engine + hosted-coming teaser). This file is the only artifact added.
