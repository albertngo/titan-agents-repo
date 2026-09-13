# Content folder scenario (Make 4918320)

Creates a content item's Google Drive scaffold when its Notion status becomes `Planning` or
`Filming`, **nests it under its Notion parent**, and writes the folder's browse link back to
`Link to Files`.

Ids, connections, the scaffold arrays and every tunable are **data** in
`platform-settings/content-sources.json` (`make_scenario` + `folder_convention`). Nothing here
repeats them — a pointer has nothing in it to fall behind.

## Why it was rebuilt

The predecessor (**4803695**, OneDrive) was undebuggable because it was *unrolled*: 28
`createAFolder` modules, one per folder per format branch, in a ~366 KB blueprint. Every
structural change meant editing 28 places, and the blueprint is large enough that
`scenarios_update` on it **fails silently — writes nothing, returns success**
(`platform-settings/lightspeed.json:132`). So it is retired in the UI, never edited through the
API.

Three things it got wrong, all fixed here:

| | 4803695 | 4918320 |
|---|---|---|
| Sharing role | `writer` — anyone with the link could **edit or delete** | `reader` |
| Shared folder | above `01_RAW` — raw footage inside clients' homes | `03_FINAL` only |
| Notion link | composed `https://drive.google.com/folder/d/<id>`, not a Drive URL form, pointing at the `04_PUBLISHED` **subfolder** | the content folder's own `webViewLink` |

## Nesting, and why the shape is what it is

Notion rows form a tree through `Parent item` / `Sub-item`, and Drive mirrors it: a child's
content folder sits directly inside its parent's. If the parent has no folder yet, the parent's
is built first — however deep the chain. A real three-level chain exists today (TC-48 *1060
Britannia* → TC-51 *Warehouse Layout* → *Shortform: Satisfying All Parties + Myself*), so a
fixed two-level unroll was never sufficient.

**Make has no loop or recursion primitive**, and a blocking filter stops the *whole* downstream
branch — so "look up the parent, build it if missing, then carry on" cannot be written inline.
The scenario therefore drives its own recursion by **re-firing its own webhook**.

The obvious alternative — call your own webhook and *wait* for the folder id — was rejected. It
holds *depth + 2* executions open simultaneously, every one of them idle-waiting on a nested
call, and it cannot be serialised without deadlocking, because an execution would be waiting on
a nested one that can never start. Recursion wants concurrency; deduplication wants
serialisation; those two cannot both be had while anything blocks.

Firing and forgetting dissolves the conflict. Nothing waits, so `sequential: true` is safe — and
that is precisely what makes the sibling race impossible. The price is that a deep chain
resolves over several queued fires across a few seconds rather than in one nested call, which
nobody is watching for.

## Shape — 18 modules

```
1  Webhook (2819947)
2  Datastore: does a record exist?   filter: self-call OR Status is Planning/Filming
3  Notion: get a database item       filter: not already built AND attempt < max_attempts
4  Datastore: get the parent record  key = Parent item[1].id, else "__ROOT__"   [Resume on error]
5  Router
   ├─ parent NOT known → POST self {data:{id: parent}}
   │                   → POST self {data:{id: me}, attempt+1}     then stop
   └─ parent known     → create TC-<n>_<name> under the parent's folder
                       → AddRecord
                       → 01_RAW / 02_EDIT / 03_FINAL / 04_PUBLISHED
                       → share 03_FINAL (reader/anyone)
                       → Notion: Link to Files
                       → iterator → the nine 01_RAW children
```

Self-calls deliberately mimic the Notion payload (`{"data": {"id": …}}`), so `{{1.data.id}}` is
the only identity expression anywhere in the scenario.

Structural decisions worth keeping:

**The recursion's base case is data, not a branch.** A parentless row looks up the seeded
`__ROOT__` record, which answers with the Drive root folder id like any other parent lookup.
Without it, "has a parent" and "has no parent" are two router branches — and since a filter
stops everything downstream, each branch would need its own copy of the whole build chain. That
is the 28-module unrolling, reintroduced. It also keeps the root folder id out of the blueprint.

**Four explicit scaffold creates, one iterator for the nine RAW children.** A pure iterator
collapses the bundle stream and makes `03_FINAL`'s id unreachable for the share step without
`map()` gymnastics over an aggregator.

**The scaffold is one array, not canvas structure.** Adding `05_CAPTIONS` is one string in
`content-sources.json`.

## Two invariants a future editor will otherwise re-learn the hard way

**The Status gate is entry-only.** `Planning`/`Filming` filters calls arriving *from Notion*. A
self-call carries an `attempt` field and bypasses it, because a **parent must be buildable
regardless of its own Status** — otherwise a parent still in `Idea` never gets a folder and
every chain through it stalls. This looks like an artifact of where the filter sits. It is not.

**`sequential: true` is the race fix, and it is only safe because nothing blocks.** Two siblings
of the same unbuilt parent, flipped a second apart, would otherwise both find the parent missing
and both create it — two identically-named folders, one child in each, the datastore pointing at
whichever finished last. Nothing errors. Nobody notices until someone goes looking for footage.
Never pair this flag with a design that waits on a nested call.

## Defects found 2026-09-13, after the first fires

This is the section worth reading: a scenario with two green 21-operation runs was not, in fact,
working.

1. **Make's filter `conditions` is an OR of ANDs** — the outer array is OR, the inner is AND.
   Written inverted, `[[Planning, Filming]]` means "Planning **and** Filming", which can never be
   true. The scenario silently processed nothing; the signature is a run consuming exactly **1
   operation**. Fixed by hand in the UI before anyone noticed the cause.
2. **`datastore:ExistRecord` outputs `exist`, not `exists`.** A filter on `{{N.exists}}` never
   resolves, so the already-built guard never blocks and **every re-fire duplicates the entire
   folder tree**. Confirmed against the module schema and a run sample (`{"exist": false}`).
3. **A hand-edit** had `AddRecord` keying on `TC-<n>` while the parent lookup keyed on page id —
   the two can never match — and storing the row's *title* in `contentID` where a Drive folder id
   belongs. It never executed.
4. **`AddRecord` moved ahead of the scaffold.** If a scaffold create fails, the folder and the
   record both exist, so a re-fire is a no-op. Recording afterwards leaves a folder with no
   record, and the next fire builds a duplicate.

Two earlier unknowns are now closed rather than hedged: `createAFolder` does output
`webViewLink`, in the correct `/drive/folders/<id>` form; and `properties_value.ID` is the object
`{prefix, number}`. Note that `getADatabaseItem`'s property shape **differs** from the raw
webhook payload's — `properties_value.ID.number` against `properties.ID.unique_id.number`.

Never map the share module's `shareLink`: the Drive app still emits it in the malformed
`/folder/d/<id>` form that caused the predecessor's bug.

## Status

**Built and verified as a blueprint. Never fired under this design.** `isActive: false`.
Do not describe it as working until a real fire is observed.

The order that proves it:

1. A parentless row — folder at the content root, `Link to Files` opens the `TC-<n>_…` folder and
   **not a subfolder**.
2. **Re-fire the same row** — exactly one folder must exist afterwards. The direct test of
   defect 2.
3. A three-level chain, cold — three folders correctly nested, resolving over several queued
   fires.
4. Two siblings of an unbuilt parent, one second apart — exactly one parent folder.
5. A chain stops at `max_attempts` rather than looping.

Watch on the first *nested* fire: hook 2819947 has no data structure attached, so Make infers the
payload shape. If `attempt` is stripped, a self-call is blocked at module 2 — no folders created,
and the chain stalls visibly in the execution log rather than misfiling anything.
