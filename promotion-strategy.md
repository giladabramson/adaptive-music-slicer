# Adaptive Music Slicer — Promotion & Competitor Strategy

A conversation about how to position, price, and promote the adaptive music slicer / AI composer with stems.

---

## Q1: What is the best way to promote my product of the music slicer? Who are my competitors?

Based on the README, the product isn't really a stem splitter — it's an **adaptive music engine for interactive media** (loops + `config.json` with emotion tags consumed by a runtime player). That changes who the competitors are.

### Real competitors

**Direct (adaptive/interactive music for games & apps):**
- **FMOD** and **Wwise** — industry-standard game audio middleware. Huge moat, but heavy and require a composer to author the music.
- **Elias Studio** — adaptive music engine, niche but established.
- **Reactional Music** — newer platform doing exactly the "music that reacts to game state" pitch.
- **Beatoven.ai**, **Mubert**, **Soundraw**, **AIVA** — AI-generated background music for video/games. Most are *not* stem-aware or adaptive at runtime; that's the wedge.

**Adjacent (will get compared to these even though they don't do the same thing):**
- **Moises.ai**, **LALAL.AI** — consumer stem separators. The product actually *uses* Demucs internally, so don't position against them.

### Differentiation (in one sentence)

"Generate or import a track, get loop-ready stems with emotion tags that a game can crossfade between — no composer, no Wwise project, one CLI call." Nobody else combines text-to-music → stem separation → bar-quantised looping → runtime-ready config in one pipeline.

### Where to promote it

1. **r/gamedev, r/IndieDev, r/GameAudio** — show a 30-sec video of a game scene changing tension and stems swapping in. This is the killer demo.
2. **HN Show HN** — the "Lyria + Demucs + librosa pipeline" angle is the technical hook.
3. **Unity Asset Store / Unreal Marketplace** — ship a thin runtime player + the CLI as the authoring tool. This is where game devs actually pay.
4. **itch.io devlog + Twitter/X #gamedev** — short before/after clips.
5. **GameDev.tv, GDC Vault talks, audio podcasts** (The Game Audio Podcast, Beards Cats and Indie Game Audio) — pitch as a guest.

---

## Q2: The product is an AI music composer that splits the music

That reframes it. It's an **AI composer with stems as a feature**, not an adaptive-music middleware play. The stems are what differentiate from every other AI composer (most output a flat mixdown).

### Real competitors (AI music composers)

**Generalist AI composers — direct competition:**
- **Suno** and **Udio** — current market leaders, consumer-facing, song-length output, *flat mix only*. Massive funding, massive users.
- **AIVA** — composer for film/game scoring, MIDI export (closest to stems).
- **Soundraw**, **Mubert**, **Beatoven.ai**, **Loudly** — royalty-free background music for video creators.
- **Boomy** — consumer "make a song in seconds," monetises via streaming royalties.
- **Stable Audio** (Stability AI), **Google MusicFX / Lyria**, **Meta MusicGen** — model providers, not really products.

**Wedge in one line:** "Every other AI composer hands you a stereo mixdown you can't edit. We hand you the drums, bass, melody, and vocals as separate loop-ready files — so you can remix, layer in a DAW, or drop into a game/video that needs the parts to move independently."

Suno users complain constantly about not getting stems (Suno added a limited stems feature recently but it's paywalled and quality varies).

### Who actually pays for this

| Buyer | Why they need stems specifically |
|---|---|
| **Producers / beatmakers** | Want to remix, swap an AI-generated bassline into a real track |
| **Video / YouTube creators** | Duck the music under dialogue by lowering one stem, not the whole track |
| **Podcasters** | Same — stems = better mix control |
| **Game / app devs** | Layer drums in during action, drop them out during dialogue |
| **DJs / live performers** | Stems are the entire point of modern DJ software (Serato, Rekordbox) |

The first two are the biggest market and the easiest to reach.

### Where to promote

1. **A 60-second side-by-side video**: "Suno gives you this [flat mix]. We give you this [4 stems, then a quick remix]." Post to TikTok, X, Reels, YouTube Shorts. This single piece of content is worth more than everything else combined.
2. **r/WeAreTheMusicMakers, r/edmproduction, r/trapproduction, r/SunoAI, r/udio** — the Suno/Udio subs are full of people asking "how do I get stems out of this." Show up with the answer.
3. **Splice / Tracklib forums and Discords** — sample-pack culture overlaps perfectly with "AI loop kits."
4. **Beatmaker YouTubers** (Internet Money, Busy Works Beats, ManiBeats) — send free access, ask for an honest review.
5. **Product Hunt + Show HN** — the technical pipeline (Lyria/MusicGen → Demucs → quantised loops) is a good HN hook; the "AI composer that gives you stems" angle is the PH hook.
6. **Splice / Loopcloud / BeatStars** as distribution — sell the AI-generated stems as loop packs. Revenue from day one.

### Two things to decide before promoting

1. **Web app or CLI?** Right now it's a Python CLI on GitHub — that limits to developers. Suno-style users will not `pip install demucs`. A simple web frontend (even just Gradio on HF Spaces) would 100x the addressable market.
2. **Free / open-source / paid?** The repo is public. Going OSS-with-hosted-tier (like Audacity → Audacity Cloud), pure SaaS, or paid desktop app? This determines whether posting to r/opensource or running Google Ads.

---

## Q3: There are real costs to produce the music, both the model and the GPU-web to run it

That kills the "free web app, race Suno to the bottom" idea. Suno/Udio are VC-burning to give generations away; can't out-burn them, so need a model where every song sold is margin-positive.

### What this implies

**1. Not a consumer-mass-market play. A premium / B2B play.**
The cost floor (Lyria call + GPU for Demucs) is probably $0.05–$0.50/song depending on length and stack. That's fine — but only if selling to someone for whom one song is worth $1–$50, not someone who wants 200 free generations to find one they like. That rules out the TikTok-teen-Suno-user crowd and points squarely at:

- **YouTube/podcast creators** — pay $5–15/track today for royalty-free music on Epidemic Sound, Artlist, Soundstripe. Stems justify the upper end.
- **Indie game devs** — pay $30–200 for a music asset pack on Unity Asset Store. Stems + emotion tags are *exactly* what they want.
- **Ad agencies / corporate video** — pay $50–500/track. Highest margin, slowest sales cycle.
- **API customers** — apps that embed music generation (fitness, meditation, video editors) and pass the cost through.

**2. Stems become the entire pricing wedge, not a feature.**

| Tier | Output | Target |
|---|---|---|
| Free / cheap | Flat mix preview, watermarked, low-res | Lead-gen only |
| Standard | Full mix, no stems | Suno-comparable, low margin |
| **Pro** | **Full mix + 4 stems + config.json** | **Real product. $5–15/track or $20–40/mo capped** |
| Enterprise / API | Pay-per-call, volume discount | Game studios, video tools |

The stems step (Demucs) is the *extra cost absorbed only when someone pays for the upsell* — keeps the funnel cheap and margin healthy.

**3. Cost optimisation matters more than feature work right now.**

- **Replicate / Modal / RunPod** for Demucs and MusicGen — pay-per-second, cold-start fast, no idle GPU bill. Replicate hosts both Demucs and MusicGen turnkey.
- **Lyria** is API-priced — track per-song cost obsessively and consider whether to fall back to MusicGen for the cheap tier.
- **Batch + async**, not realtime. "Your track will be ready in 2 minutes, we'll email you" lets you pack GPU usage and use spot instances. Users tolerate this for paid creative tools (Midjourney trained them to wait).
- **Cache the expensive step you can cache.** Can't cache Lyria output (generative), but you *can* pre-generate a library of 10k stem-ready tracks across moods/BPMs and sell *retrieval* + *light remix* as a near-zero-marginal-cost product. That's actually how Soundraw and Mubert keep their margins — they're 80% library, 20% generation.

**4. The hybrid model is probably the winner.**

Library of pre-generated stem packs (high margin, instant delivery) + on-demand generation as the premium upsell (low margin, slower, but high perceived value). Same backend, two products, very different unit economics.

### What I'd do this week

1. Calculate actual fully-loaded cost per song on each backend (Lyria vs MusicGen, CPU vs GPU Demucs). Without that number can't price.
2. Pick **one** vertical (start with indie game devs — smallest TAM but highest willingness-to-pay for stems + emotion tags, which is literally the README).
3. Pre-generate 50 stem packs and list them on **Unity Asset Store** and **itch.io**. Zero marginal cost per sale, validates demand, learn what mood/BPM/genre combinations sell before scaling generation.

---

## Q4: How did they build 80% library?

Important correction first: the "80% library" doesn't mean 80% pre-generated finished tracks sitting on a CDN. It means most of what users hear is **recombined from a modest pool of human-composed stems**, not generated per-request. That changes the answer a lot — and it maps directly to what the pipeline already outputs.

### How Mubert, Soundraw, and Endel actually did it

**Mubert** started with ~a few thousand short loops composed by human producers on a revenue-share deal. The "AI" was a rules engine that picked loops by key/BPM/mood and stitched them. They marketed "billions of tracks" — which was true combinatorially (1000 loops × variations × arrangements) but misleading about source material. Neural generation came later and is still a minority of output.

**Soundraw** pays human composers to upload modular stems (drums, bass, melody, FX) organised by genre/mood/BPM. Their generator picks compatible stems and assembles a track with intro/build/drop structure. Composers get a flat fee or share; Soundraw owns perpetual license.

**Endel** licensed a small set of generative sound packs from a few collaborating artists (Grimes, Plastikman, etc.) and recombines them per user's biometric input. Tiny source library, huge perceived variety.

**Epidemic Sound / Artlist** (not AI but same lesson): built 40k+ track catalogs by paying composers ~$200–2000 per accepted track for perpetual ownership. No royalties downstream.

The pattern: **own the stems forever, recombine forever, marginal cost ≈ zero.**

### What this means specifically

The pipeline already outputs **bar-quantised, BPM-tagged, emotion-tagged stems with a config.json**. That's the exact format a recombination engine needs. Most AI composers can't do this — they output flat mixdowns.

Three concrete paths to bootstrap a library, cheapest first:

1. **AI-generate + heavy curate.** Run Lyria overnight on 500 prompts across genres/moods/BPMs. Keep the 20% that's actually good (~100 stem packs). Cost: ~$50 + listening time. Fastest, lowest quality ceiling.
2. **Pay 5–10 composers per-stem.** Post on r/WeAreTheMusicMakers or Fiverr: "$50 per accepted 8-bar loop, 4 stems, you keep credit, I keep license." Higher musical quality than current AI for ~$200/pack. This is the Soundraw/Epidemic playbook in miniature.
3. **License an existing stem library** (Splice, Loopcloud, Looperman commercial tier) and build the recombination/adaptive layer on top. Skips the catalog-building entirely; compete on the player, not the content.

The honest pick for a solo founder: **start with #1 to validate the product**, switch to **#2 once you know which genres sell**, never bother with on-demand generation as the primary product. On-demand is the demo and the upsell, not the engine.

---

## Q5: How will option one go?

Concrete walkthrough as a weekend project with numbers.

### Option 1, end-to-end

**Step 1 — Plan the prompt grid (30 min, $0)**
Pick the axes that matter to buyers:
- 8 genres (lo-fi, synthwave, cinematic, ambient, trap, funk, reggae, orchestral)
- 5 moods (chill, tense, triumphant, sad, energetic)
- 3 BPM bands (80, 110, 140)

That's 120 prompt slots. Generate 4 variations each = **480 attempts**. Build the prompt strings in a CSV: `genre, mood, bpm, prompt_text`.

**Step 2 — Batch-generate (overnight, ~$50)**
Loop the existing pipeline over the CSV. Lyria preview is rate-limited so this runs hours, not minutes — kick it off Friday night. Cost is roughly $0.10/call × 480 = **~$50** (verify with actual pricing). Demucs runs locally on CPU for free, just slower; or on Modal at ~$0.01/track if needed faster.

Output: 480 folders, each with `drums.wav / bass.wav / other.wav / vocals.wav / config.json`.

**Step 3 — Auto-filter to kill obvious garbage (2 hr to write, runs in minutes)**
Write a ~150-line Python script that rejects packs failing any of:

- librosa-detected BPM differs from requested BPM by >3
- Any non-vocal stem has RMS below threshold (separation failed)
- Vocals stem RMS *above* threshold (Lyria/MusicGen are instrumental — loud vocals = leakage = bad separation)
- Loop seam discontinuity > N samples at zero-crossing
- Overall loudness wildly off (-30 LUFS or +0 LUFS)

This typically kills 50–60% with zero listening. Goes from 480 → ~200 candidates.

**Step 4 — Human curate (2 hr listening)**
Open each surviving pack, hit play on the full mix, listen for 15 seconds. Three buckets: *keep / kill / maybe*. Be ruthless — competing with human-composed asset packs, so "fine" gets killed. Target: **40–80 keepers** from 200. This is the painful step that can't be skipped; AI music quality is bimodal, and only ears separate the modes reliably.

**Step 5 — Package each keeper (~5 min each, so ~5 hr total for 60 packs)**
For each pack:
- Title: `Synthwave Energetic 128 BPM` is fine; clever names don't sell better
- 15-sec preview MP3 (full mix) — auto-generate from the stems
- Tags: genre, mood, BPM, key (librosa can estimate key), "stems included", "loop"
- One demo video per *genre*, not per pack — record the screen playing a stem, muting drums, layering them back. **This is the one thing buyers actually convert on.** Make 8 videos, reuse across the 60 listings.
- License PDF (royalty-free, perpetual, no resale — there are templates)

**Step 6 — List on two marketplaces (1 day)**
- **Unity Asset Store** — slow approval (1–4 weeks), but game devs are the stems audience. $15–30/pack.
- **Itch.io** — instant listing, flexible pricing, indie game devs browse it. Charge $10 or pay-what-you-want with a $5 floor.
- Skip Pond5/AudioJungle for v1 — their audiences want finished tracks, not stems.

Don't dump all 60 at once — list 10, see what moves, double down on what works.

### What "done" looks like

End of the weekend: $50 spent, ~60 packs listed, two marketplace storefronts, eight demo videos. Then it's passive — sales happen or they don't, and you learn what to generate more of.

### What the failure mode looks like

List 60 packs and sell 3 in a month. That's not a tragedy — it's the validation signal. It means either:
1. AI quality isn't there yet for paying buyers → switch to option #2 (hire composers).
2. The audience doesn't browse Asset Store / Itch for music → switch promotion channel.
3. Stems aren't enough of a wedge → rethink the positioning entirely.

Either way: $50 and a weekend spent, not $5k and three months.

---

## Open next steps

- Write the auto-filter script (step 3) against the existing pipeline — highest leverage piece, saves listening to ~300 bad clips.
- Instrument cost-per-song in the pipeline so pricing decisions have a real number behind them.
- Decide single primary buyer vertical (likely indie game devs) before doing any of the above.
