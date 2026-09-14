# Content folder scenario (Make 4918320)

Creates a content item's Google Drive scaffold when its Notion status becomes `Planning` or
`Filming`, and writes a link back to the row's `Link to Files`.

**Frozen as-is on 2026-09-14** (Albert): whatever was live at that moment is what we keep. The
blueprint is snapshotted verbatim at
`platform-settings/blueprints/content-folder-scenario-4918320.json`; ids and behaviours are data
in `platform-settings/content-sources.json` (`make_scenario`).

**It is edited in the Make UI, not from here.** On 2026-09-13 API pushes and UI edits repeatedly
overwrote each other. Re-snapshot the blueprint file after any UI change; don't push at it
without asking.

## What it does

```
1  Webhook (2819947)
2  Datastore: record exists?     key TC-<n>      [filter: Status is Planning or Filming]
3  Datastore: get a record       key = Parent item page id, else "__no_parent__"
4  Drive: create TC-<n>_<name>   under ifempty(3.contentID; <content root>)
5-8   Drive: 01_RAW / 02_EDIT / 03_FINAL / 04_PUBLISHED
9  Datastore: add record         key TC-<n>, contentID = the row's Content Name
10 Drive: share 03_FINAL         reader / anyone
11 Notion: Link to Files = 10.shareLink, and Post Date
12 Iterator -> 13  the nine 01_RAW children
```

**Folders are flat.** Every content folder is created at the Drive root; Notion's
`Parent item` / `Sub-item` tree is not mirrored.

## Behaviours to expect

Consequences of the current design, recorded so they don't get rediscovered as surprises.
Not a to-do list.

**Re-firing a row builds another tree.** Module 3's filter reads `{{2.exists}}`, but the
module's output field is `exist` — singular. The condition never resolves, so the already-built
guard never blocks. Observed live: restoring ten rows to `Planning` on 2026-09-14 produced ten
new folder trees and ten new `Link to Files` values.

**The row's link opens `03_FINAL`, not the content folder.** Module 11 writes
`{{10.shareLink}}`, and module 10 shares `03_FINAL`. The Drive app also returns `shareLink` in
the non-standard `https://drive.google.com/folder/d/<id>` form rather than the canonical
`/drive/folders/<id>`. If this is ever revisited, `{{4.webViewLink}}` is the content folder's
own link and comes back in the correct form.

**The datastore stores titles.** Module 9 puts the row's `Content Name` into `contentID`, whose
only consumer — module 4's `folderId` — needs a Drive folder id. Harmless while nesting is off,
because nothing reads it back successfully.

**Nesting cannot work in this shape**, for the record: module 3 looks a parent up by **page id**
(what Notion's relation returns) while module 9 files records under **`TC-<n>`**. The two key
spaces never meet, so module 4 always falls through to the root. A parent-aware version — a
router plus two self-calling HTTP modules that re-queued the webhook until the parent existed —
was built and proven to fire (both calls returned `200 Accepted`); it is in git history around
commit `0026a89` and is not in the live scenario.

## What survived from the OneDrive predecessor's problems

4803695 was 28 unrolled `createAFolder` modules in a ~366 KB blueprint that `scenarios_update`
silently refuses to write (`platform-settings/lightspeed.json:132`). Two of its three defects
are fixed here and should stay fixed:

| | 4803695 | 4918320 |
|---|---|---|
| Sharing role | `writer` — anyone with the link could **edit or delete** | `reader` |
| Shared folder | above `01_RAW` — raw footage inside clients' homes | `03_FINAL` only |
| Notion link | `04_PUBLISHED`, composed URL | `03_FINAL`, `shareLink` |

The scaffold is also one array plus an iterator rather than structure spread across the canvas,
so adding a folder is one string in `content-sources.json`.

## Make gotchas learned the hard way

Worth keeping whatever the scenario looks like later:

- **`filter.conditions` is an OR of ANDs** — the outer array is OR, the inner is AND. Written
  inverted, `[[Planning, Filming]]` means "Planning **and** Filming" and can never be true. The
  signature is a run consuming exactly **1 operation**.
- **`datastore:ExistRecord` outputs `exist`, not `exists`.**
- **`app-module_get` hides advanced fields** unless `includeAdvancedFields: true`. They are
  `required` with defaults, filled in silently by the UI and absent via the API — a module built
  through the API without them fails at runtime with `BundleValidationError`, not at save time.
- **`organizationId` is not the team id.** Passing the team id returns "Insufficient rights,
  admin permission organization view is needed", which reads like a permissions wall and isn't.
