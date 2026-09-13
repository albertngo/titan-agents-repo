# Content folder scenario (Make 4918320)

Creates a content item's Google Drive scaffold when its Notion status becomes
`Planning` or `Filming`, then writes the folder's browse link back to the row's
`Link to Files`.

Ids, connections and the scaffold arrays are **data** in
`platform-settings/content-sources.json` (`make_scenario` + `folder_convention`).
Nothing here repeats them — a pointer has nothing in it to fall behind.

## Why it was rebuilt

The predecessor (**4803695**, OneDrive) was undebuggable because it was *unrolled*:
28 `createAFolder` modules, one per folder per format branch, in a ~366 KB blueprint.
Every structural change meant editing 28 places, and the blueprint is large enough
that `scenarios_update` on it **fails silently — writes nothing, returns success**
(`platform-settings/lightspeed.json:132`). So it is retired in the UI, never edited
through the API.

Three things it got wrong, all fixed here:

| | 4803695 | 4918320 |
|---|---|---|
| Sharing role | `writer` — anyone with the link could **edit or delete** | `reader` |
| Shared folder | above `01_RAW` — raw footage inside clients' homes | `03_FINAL` only |
| Notion link | composed `https://drive.google.com/folder/d/<id>`, which is not a Drive URL form, and pointed at the `04_PUBLISHED` **subfolder** | the content folder's own link |

## Shape — 13 modules

```
1  Webhook (hook 2819947)
2  Datastore: Does a record exist?      filter: Status is Planning or Filming
3  Datastore: Get a record  (parent)    filter: 2.exists = false      [Resume on error]
4  Drive: Create folder   TC-<n>_<name>  under 3.contentID, else the content root
5-8  Drive: Create folder   01_RAW / 02_EDIT / 03_FINAL / 04_PUBLISHED   under 4.id
9  Datastore: Add record    key = Notion page id, contentID = 4.id
10 Drive: Share             03_FINAL, reader/anyone
11 Notion: Update item      Link to Files = 4's folder link
12 Iterator                 the nine 01_RAW children
13 Drive: Create folder     under 5.id
```

Two structural decisions worth keeping:

**Four explicit top-level creates, one iterator for the nine RAW children.** A pure
iterator collapses the bundle stream and makes `03_FINAL`'s id unreachable for the
share step without `map()` gymnastics over an aggregator. Four named modules keep
every id directly addressable and still take 28 modules down to 13.

**The iterator is last.** Nothing needs to run after it, so the collapsed stream
costs nothing.

**The scaffold is one array, not canvas structure.** Adding `05_CAPTIONS` is one
string in `content-sources.json`.

## What v1 deliberately does not do

**Create a missing parent.** It does the *lookup* — if the parent's folder exists,
the child nests correctly — but a child firing before its parent lands at the content
root. Re-firing it after the parent exists files it correctly; setting the parent's
status first avoids it. Auto-creation needs a router whose behaviour cannot be
validated without executing it, and a router silently misfiling folders is worse than
a predictable gap. Revisit once v1 has run clean.

## Two things to watch on the first real fire

Neither could be verified without executing, and reading the module schemas needs an
`organization view` right this token does not have.

1. **Module 3 on a parentless row** looks up the sentinel key `__no_parent__`, which
   will never exist. Whether Make's *Get a record* errors or returns an empty bundle
   on a miss is unconfirmed, so the module carries a `builtin:Resume` handler —
   either way module 4 falls through to `ifempty(3.contentID; <root>)`. If the
   execution log shows module 3 erroring-and-resuming rather than passing cleanly,
   that is expected, not a fault.
2. **`4.webViewLink`** is the presumed output field for the folder's URL. Module 11
   writes `ifempty(4.webViewLink; "https://drive.google.com/drive/folders/" + 4.id)`,
   so an unresolved field name degrades to the canonical composed URL rather than
   writing an empty link. Confirm the value that lands on the row opens the
   `TC-<n>_…` folder, **not a subfolder** — that was the predecessor's bug and row
   165 still holds its output.

## Status

**Built, never fired.** No recorded execution as of 2026-09-13; `isActive: false`.
Do not describe it as working until a real fire is observed end to end.

Before activating, the Notion automation must be repointed at the v2 webhook
(`make_scenario.webhook_url`). Activating 4803695 instead would drain the two calls
still queued on its own hook into the OneDrive tree.
