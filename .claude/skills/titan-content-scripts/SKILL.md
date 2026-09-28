---
name: titan-content-scripts
description: Turns a topic, a content series, or raw material (a job site, footage notes, a transcript, a Titan Project) into fully scripted shortform video ideas for Titan Flooring, and writes each one straight into the Titan Content Ideas database in Notion. Each entry gets three labelled hooks, a full spoken script with on-screen text and b-roll, a batch-ordered shot list, prep checklist, and per-platform captions (Instagram Reels, TikTok, Facebook, YouTube Shorts) tuned for reach and saves. Also writes or rewrites captions for an existing TC-## entry. Use this whenever Albert asks for content ideas, reel ideas, shorts, TikToks, video scripts, hooks, a shot list, "what should I film," "give me 10 ideas," "turn this job into content," "script this," asks for a caption for a TC number or a Titan video, or names a series (Facts & Myths, Titan Flooring Tests, Spot the Problem, This or That?, Material Showcase, Design Inspo, Behind the Scenes, Client Q&A, Success Stories), even without saying "script."
---

# Titan Content Scripts

Generate ready-to-shoot shortform content for Titan Flooring and file it in Notion. Albert is on camera; filming happens at the Mississauga showroom, the warehouse, or a client job site.

## Where it goes

- Database: **Titan Content Ideas**
- Data source: `collection://1ef596a4-505f-815d-a9c1-000b59bcedac`
- Create pages with `notion-create-pages`, parent = that data source (not a page ID).
- To search inside it, pass the data source URL as `data_source_url`; workspace-wide search is noisy.
- Reference bank for source lines: the "Floor Facts & Myths" section of page `1fa596a4505f8061a773d041b308b41f`. Cite it in each entry's **Pulled from** line when a line comes from there.

Write entries **straight into Notion without asking first.** Albert chose this.

## Step 1 — Work out the input mode

**Topic / series mode** — Albert gives a topic, a series, or nothing at all.
- If he gives nothing, pick topics yourself, spread across several series.
- Default batch: **10 entries** unless he names a number.

**Raw content mode** — Albert gives a job site, footage, a transcript, photos, or a Project.
- Extract and rank angles using the process in `references/hooks-and-angles.md`.
- Make as many entries as the material genuinely supports, up to 10. Don't pad with weak cuts; say how many it supported and why.
- If it matches a record in the Titan Projects data source (`collection://1b4596a4-505f-81ca-b1d5-000bb73ecbe1`), link it through the **Project** relation.
- Client quotes: use only what the client actually said. Never invent testimonials.

**Caption-only mode** — Albert asks for captions on an existing entry ("caption for TC 86").
- Find the entry in the database, fetch it, and write captions from its script, following `references/captions.md`.
- Replace that page's caption section in place (use the page-update tool) without touching anything else on the page.
- Also write every platform's caption into its **caption property** (Step 4). The properties are what actually posts, so they're never optional.

If it's both (e.g. "10 ideas, and use the Hwang job for some"), blend the two.

## Step 2 — Check before writing

1. Fetch the data source to confirm current property options (Series, Content Type, Status can change).
2. Search the database for each planned topic. Skip or re-angle anything already covered.
3. Fetch the Facts & Myths reference page when working in Facts & Myths, This or That?, or Design Inspo.

## Step 3 — Write each entry

Read all three reference files before writing the first entry:
- `references/entry-template.md` — page structure. Follow it exactly: section order, table columns, emoji headers, delivery legend.
- `references/hooks-and-angles.md` — the hook pattern library. Label every hook with its pattern and add a ★ recommended pick.
- `references/captions.md` — per-platform caption rules, formulas, and the quality check. Run the check on every caption before writing to Notion.

Rules carried over from past batches:
- **Hook A is always the AEO hook**: a plain question someone would type into search or ask an AI ("Does laminate still look cheap?"). Hooks B and C use two different patterns from the hook library.
- **Never say "link in bio"**, spoken or in captions, so the content works on YouTube too.
- **DM CTAs use only**: "DM askMaria (keyword FLOOR)". No other keywords.
- **CTA goals** come from: Save, Showroom visit, Free Quote, Follow, DM askMaria (keyword FLOOR). Vary them across a batch.
- **Specs are approximations.** Humidity ranges, expansion gaps, wear layers, AC ratings, IIC/STC, and cure times are worded as "about," "roughly," or "look for," with a "check the manufacturer" or "check your condo rules" nudge. Never state them as absolutes.
- **Test results are placeholders.** For Titan Flooring Tests, put `XX` wherever a measured result goes (decibels, seconds, scratch count). Never invent results.
- **Seasonal timing.** If a topic is seasonal (winter gaps, humidity, spring renos), add a scheduling note in the Big Idea box, e.g. "Post Oct/Nov when furnaces come on."
- **Voice**: friendly expert. Short, spoken sentences. Canadian spelling (colour, centre).
- **Hashtags**: 3–5 per platform (0–2 on Facebook), with at least one local tag, rotated across the batch so no two entries share an identical set.

## Step 4 — Set properties

| Property | Value |
|---|---|
| Content Name | Short title, series-led (e.g. "Myth Laminate Looks Cheap and Fake", "This or That Light Floors vs Dark Floors") |
| icon | One fitting emoji |
| Content Format | Shortform |
| Content Type | Educational, Authority, Storytelling, Visual, or Proven Winner — pick the best fit |
| Series | The matching series option(s) |
| Status | Planning |
| Weight | Light by default; Medium if it needs a job site, a second person, or a real test; Heavy only for multi-location shoots |
| Next: Post To | Instagram Reels |
| Project | Linked only in raw content mode, when a match exists |
| Caption - Instagram · Caption - TikTok · Caption - Facebook | Always filled: that platform's caption plus its hashtags, exactly as it should post. No label line. |
| Caption - YouTube · YouTube Title | Always filled: the Shorts description (plus hashtags) and the title |
| First Comment | Always filled: the pinned first comment (it's used on IG and TikTok) |
| Caption - Google Business | Only when Albert asks for a GBP caption (same rule as the body). Empty means that platform's row is held, never given another platform's caption. |
| Post Date, Link to Files, media fields | Leave blank unless Albert gives them. |

### Why the captions go in properties as well as the body

The body's `📝 CAPTIONS` section is for reading. It keeps the `Formula | Hook | CTA` label lines so Albert can learn which formulas work. The **properties** are what posts. The **Send to Calendar** button copies the property that matches **Next: Post To** into the Content Calendar Log row, and `/content-schedule` sends that row's Caption to Metricool. A button formula can't read page body text, so a caption that exists only in the body never gets posted. Keep the two copies identical, minus the label lines.

## Step 5 — Report back

Reply in Albert's PARA format (Point, Action, Result, Ask), in prose, short:
- **Point**: how many entries were created and which series they cover.
- **Action**: the batching plan — group entries by location (showroom / warehouse / job site) so he can shoot several in one session. Shot lists are already ordered talking head → demos → b-roll/VO.
- **Result**: anything he must prep or confirm (placeholders to fill, materials to pull, seasonal posting notes).
- **Ask**: one question, e.g. whether to schedule post dates or build captions for a specific entry.

Link each created page by title. Don't paste the scripts back into chat.

If a Notion write fails, say which entries failed, keep the rest, and offer to retry.
