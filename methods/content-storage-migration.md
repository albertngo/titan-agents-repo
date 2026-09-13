# Content storage migration — OneDrive → Google Drive

One-time move of the content library, decided 2026-09-12 (Albert). Two halves that
must happen in order: **the bytes**, then **the Notion links**. A moved folder whose
Notion row still points at OneDrive is a broken row, so the second half is part of the
migration, not a follow-up — but it cannot start until the first is verified, or it
points rows at folders that do not exist yet.

Registry: `platform-settings/content-sources.json` (`migration` block).

## Why not Make

Make bills **data transfer** monthly — Free 100 MB, Core 1 GB, **Pro/Teams 10 GB**.
The job is **200.6 GB**, and `TFC-149_Tim Gilbert` **alone (51 GB) exceeds the entire
monthly allowance on every tier**. Make cannot do this slowly; it cannot do it at all.

The Drive scenario cloned on 2026-09-12 is still correct and still needed — it builds
the scaffold and the share link for **new** rows. Different job, same folders.

## Measured before planning

| | |
|---|---|
| Top-level content folders | 32 |
| Total | 200.6 GB |
| The 11 folders over 1 GB | 199.1 GB — **99.3%** |
| Everything else combined | 1.44 GB |
| Worst-case Drive path | 152 chars (limit 400) — **not a risk** |
| Drive daily upload cap | 750 GB/day — 200 GB fits in one day |

The weight is raw footage in `01_RAW`, which the posting pipeline never reads. It
migrates anyway: Albert's Drive is a 2 TB plan, and one source of truth beats a split
archive. The residual risk is **throughput, not cost**.

---

## Part 1 — the bytes (Albert's Mac, rclone)

Not from a cloud session: 200 GB through an ephemeral container is absurd, and no
session holds OAuth for both clouds in a form rclone can use.

### 1. Configure remotes, once

```bash
rclone config    # 'onedrive' -> OneDrive Business / SharePoint
                 # 'gdrive'   -> Google Drive (albertngo95@gmail.com)
```

### 2. Generate the plan

List the OneDrive content root, then:

```bash
python3 scripts/content_migration_map.py --listing onedrive.json --out-dir ingest/<date>/
```

Produces `migration-map.csv` (`order, notion_id, old_name, new_name, bytes`) and
`migrate.sh`. **Read the CSV before running anything.** It is the whole rename,
reviewable in one screen, and the `TFC-` → `TC-` change happens here in flight.

The mapper **refuses** to plan if two folders claim one Notion id — rclone copies into
a named destination, so two sources would merge into one folder silently.

### 3. Dry run

```bash
DRY=1 ./migrate.sh
```

### 4. Run it

```bash
./migrate.sh          # log: ~/titan-migration.log
```

Smallest first, deliberately: the 21 sub-gigabyte folders finish in minutes and prove
remotes, naming and permissions before the 51 GB folder commits hours to a
misconfiguration. Each folder is `rclone check --size-only --one-way`'d immediately
after its copy, so a problem surfaces at folder 3 rather than at the end.

**Interrupted? Run it again.** `rclone copy` skips files already present by name and
size, so a re-run resumes. The script exits non-zero if any folder failed.

### Safety properties, and why each is there

- **`copy`, never `sync`.** `sync` deletes at the destination to match the source; on
  a half-migrated estate that is data loss. A test asserts `sync` never appears in the
  generated script.
- **Nothing is deleted from OneDrive.** Not by this script, not at the end of this
  phase. OneDrive keeps working as the archive until Albert has looked at Drive and
  said otherwise. Reversible-by-inaction is the only safe shape at this volume.
- **`--drive-stop-on-upload-limit`** stops cleanly on the daily cap rather than
  churning through retries.

---

## Part 2 — the Notion links (a Claude session, after Part 1 verifies)

Per row, keyed on the **Notion id** — never the prefix, which is exactly what changed:

1. `search_files` in Drive for `TC-<id>_…` under `drive.root_folder_id`.
   **Never resolve by title alone**: three folders in this account match "Titan
   Flooring", one of them shared in by an outside agency.
2. Take its `viewUrl`.
3. Write **only** `Link to Files`. Per `write_properties` in the registry, this
   pipeline may not touch `Status`, `Caption`, `Post Date` or `Next: Post To` — those
   are the plan, and an agent editing them has started deciding what to post.
4. Log each row moved / skipped / failed, and **write the report before reporting
   success** — the same rule the actions agents follow.

**A row whose Drive folder is missing is skipped and reported, never guessed at.** A
row silently left on a dead OneDrive link is worse than one flagged unmigrated.

### Sharing stays narrow

`Link to Files` points at the content folder and **stays private** — it is for Albert
and the team, who are signed in. Only the `03_FINAL` asset handed to Metricool needs
anyone-with-link, per `share_scope: media_dir_only`.

Sharing the root would be simpler, since Drive permissions inherit — and would expose
every `01_RAW` folder, i.e. raw unedited footage inside clients' homes, to anyone with
the link. Finished assets are already bound for public feeds; raw footage never
consented to that. **The migration changes no permissions at all.**

---

## Done means

- `rclone check` clean on all 32 folders.
- Every Notion row's `Link to Files` resolves to a live Drive folder, or is reported
  as unmigrated with a reason.
- `ingest/<date>/actions-log.json` carries one entry per row touched.
- OneDrive still intact. Deleting it is a separate, later, human decision.
