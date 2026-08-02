# Ingest Output Contract — v1

Every ingester writes exactly one file per run:

```
/ingest/YYYY-MM-DD/<source>.json
```

Re-runs on the same day overwrite the file (idempotent). Never append.

## Envelope

```json
{
  "contract_version": "1",
  "source": "ghl",
  "run_at": "2026-07-24T07:05:00-04:00",
  "status": "ok",
  "error": null,
  "items": [],
  "metrics": {},
  "needs_attention": []
}
```

| Field | Rules |
|---|---|
| `contract_version` | Bump only with a migration note in this file. Orchestrator must tolerate n and n-1. |
| `source` | Machine name matching the agent: `ghl`, `email`, `bookkeeper`, ... |
| `status` | `ok`, `partial`, or `error`. `partial` = some data retrieved, some calls failed. |
| `error` | Human-readable string when status != ok, else null. |
| `items` | Array of Item objects (below). Empty array is valid — it means "nothing today", not failure. |
| `metrics` | Flat key→number map for the brief's stats line (e.g. `{"new_leads": 3, "unread": 41}`). |
| `needs_attention` | Array of strings. Anything Albert must see today. Keep it short and specific. |

## Item

```json
{
  "id": "ghl-lead-8842",
  "type": "lead",
  "title": "New lead: kitchen + stairs, Oakville",
  "summary": "Inbound SMS quote request, ~1200 sqft LVP, wants install. Phone captured.",
  "timestamp": "2026-07-24T06:41:00-04:00",
  "priority": "high",
  "link": "https://app.gohighlevel.com/...",
  "amount_cents": null,
  "raw_ref": "conversation 8842",
  "sensitivity": null
}
```

| Field | Rules |
|---|---|
| `id` | Globally unique, prefixed with source. Stable across re-runs **within the same day's file** so the funnel can dedupe intra-day. **Not stable across days** — as an entity's status changes (e.g. a lead's drift type), its id changes with it. Cross-day dedupe must key on a stable entity identifier (e.g. a platform contact ID), never on `id`. |
| `type` | Controlled per source, documented in that agent's file. Examples: `lead`, `message`, `invoice`, `expense`, `meeting`. |
| `title` | ≤ 80 chars. What it is. |
| `summary` | 1–3 sentences. What matters. No raw dumps. |
| `priority` | `high` (act today), `normal`, `low` (FYI). |
| `link` | Deep link to the source platform when available, else null. |
| `amount_cents` | Integer cents CAD when money is involved, else null. |
| `sensitivity` | Optional. `"team"` or `"private"`, else null (source default applies). Set by the ingest agent when an item needs routing different from its source's default — e.g. an item relaying content from an admin-only surface (QBO, Outlook, Notion Project Financials) or a genuinely personal matter. Provenance decides, not content: what staff already sees in its source platform stays team (Albert, 2026-08-02). May only escalate `team → private`, never the reverse. Consumed by `contracts/notion-task-schema.md` (Notion team/private routing) and by `vault-writer-agent` (vault `visibility` tagging: `team → staff`, `private → admin` — the mapping and the admin-fact list live in the Visibility section of the vault's `CONVENTIONS.md`). |
| `raw_ref` | Pointer back to the source record for audit. Never paste full raw content here. |

## `extensions` — optional, source-owned detail

An ingester MAY add one top-level `extensions` key for structured detail that
doesn't fit the shared item format:

```json
{
  "contract_version": "1",
  "source": "ghl",
  "items": [],
  "extensions": {
    "ghl": {
      "template_version": "2",
      "reporting": {},
      "conversations": []
    }
  }
}
```

| Rule | |
|---|---|
| Optional | Absent `extensions` is valid. Consumers must tolerate its absence. |
| Namespaced | Keyed by source name (`extensions.ghl`). An ingester writes ONLY its own key. |
| Source-owned | The owning agent defines the shape and documents it in its agent file. No cross-source schema. |
| Independently versioned | `template_version` inside the namespace versions that structure; it does NOT affect `contract_version`. |
| Additive only | New use case = new named array/object. Never repurpose an existing field. |
| Not a bypass | Everything in the brief must still be derivable from `items` / `metrics` / `needs_attention`. `extensions` is depth, never the only copy. |
| Exempt from the 50-item cap | The cap applies to `items`. Extensions still obey "no raw dumps". |

**Consumers** (orchestrator, vault-writer-agent) read `items`, `metrics`, and
`needs_attention` as the stable interface. They may read `extensions.<source>` for
richer output but must degrade gracefully when a section is missing — never fail a
brief because an extension changed shape.

Because `extensions` is additive and optional, adding it does not bump
`contract_version`.

## What ingesters must NOT do

- Write anywhere except their own `/ingest/YYYY-MM-DD/<source>.json`.
- Take actions on the source platform (send, delete, label) — ingest is read-only.
- Exceed ~50 items/day. Aggregate low-value items into one summary item instead.

## Adding a new source

1. Copy an existing agent file in `.claude/agents/`, rename, rewrite the platform section.
2. Add its `type` vocabulary to the agent file.
3. Add one row to the table in `CLAUDE.md`.
Done — the orchestrator picks up any `*.json` in the day folder automatically.
