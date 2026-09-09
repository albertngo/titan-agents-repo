#!/usr/bin/env python3
"""Backfill Lightspeed UUIDs into the Tosca Airtable upload file.
AT file: ingest/2026-09-09/tosca_airtable_upload_2026-09-09.csv (225 rows, LS ID blank)
LS export: 195 Tosca products already live in Lightspeed."""
import csv, re, openpyxl
from openpyxl.styles import PatternFill, Font

AT  = "/home/user/titan-agents-repo/ingest/2026-09-09/tosca_airtable_upload_2026-09-09.csv"
LSX = "/root/.claude/uploads/269a198f-9764-5d66-99c8-c4b232f92e0d/033fff57-tosca_uuid.xlsx"
OUT = None  # xlsx dropped 2026-09-09 (Albert: CSV only) -- see write block below

def al(s): return re.sub(r'[^a-z0-9]', '', str(s or '').lower())
def lev(a, b):
    if a == b: return 0
    if len(a) < len(b): a, b = b, a
    if not b: return len(a)
    prev = list(range(len(b)+1))
    for i, ca in enumerate(a):
        cur = [i+1]
        for j, cb in enumerate(b):
            cur.append(min(prev[j+1]+1, cur[j]+1, prev[j]+(ca != cb)))
        prev = cur
    return prev[-1]
def near(a, b, mn=5): return a == b or (len(a) >= mn and len(b) >= mn and abs(len(a)-len(b)) <= 1 and lev(a, b) <= 1)
def f(x):
    try: return float(str(x).strip())
    except (TypeError, ValueError): return None

# grade / noise tokens that are never a colour
NOISE = {'all','abgrade','abcdgrade','ab','abc','abcd','ef','round','l','r','doubleside',
         '3mmwear','selectbetter','','c','eachfoot','persf'}
COLLNOISE = {'moulding','europeanoak','spc','tg','','engineeredwood'}

def strip_coll(t):
    t = al(t)
    for suf in ('collection','series'):
        while t.endswith(suf): t = t[:-len(suf)]
    return t

# ---------------------------------------------------------------- load LS
wb = openpyxl.load_workbook(LSX, data_only=True)
rr = list(wb['Product Export'].iter_rows(values_only=True))
hdr = rr[0]
ls = []
for r in rr[1:]:
    d = dict(zip(hdr, r))
    name = str(d.get('name') or '').strip()
    if not d.get('id'): continue
    u = name.upper()
    fam = ('ENG' if u.startswith('TOSENG') else 'HWD' if u.startswith('TOSHAR')
           else 'VIN' if u.startswith('TOSVIN') else 'LAM' if u.startswith('TOSLAM') else None)
    is_mould = 'MOULDING' in u
    # colour candidates
    cols = set()
    for m in re.finditer(r'\(([^)]*)\)', name):
        t = al(m.group(1))
        if t and t not in NOISE and 'sfbox' not in t and not re.match(r'^[\d.]+$', t): cols.add(t)
    m = re.match(r'^TOS\w+\s*-\s*([^-|(]+?)\s*\(', name)          # legacy "TOSENG - Latte (Deluxe Collection)"
    if m: cols.add(al(m.group(1)))
    for seg in name.split('|')[1:]:                                # legacy "| Whipping Cream |"
        t = al(seg)
        if t and t not in NOISE and re.match(r'^[A-Za-z ]+$', seg.strip()) and 3 <= len(t) <= 22: cols.add(t)
    # collection candidates = all " - " segments
    colls = {strip_coll(s) for s in re.split(r'\s+-\s+', name.split('|')[0])}
    colls |= {strip_coll(m.group(1)) for m in re.finditer(r'\(([^)]*)\)', name)}
    colls -= COLLNOISE | {strip_coll('TOSENG'), 'toseng', 'toshar', 'tosvin', 'toslam'}
    # numeric/product code
    codes = set()
    for m in re.finditer(r'#([A-Za-z0-9]+)', name): codes.add(str(m.group(1)).upper())
    if d.get('sku'): codes.add(str(d['sku']).strip().upper())
    # specs. Three printed shapes:
    #   modern  '- 6.5" x 3/4" x RL'      width then 3/4 thickness
    #   solid   '- 4-1/4" x 3/4" x RL'    mixed fraction
    #   legacy  '3/4 " x 6" x RL'         thickness then width
    #   vinyl   '- 7.25" x 7mm x 60"'     width then mm thickness then length
    def frac(t):
        t = t.strip()
        m = re.fullmatch(r'(\d+)-(\d+)/(\d+)', t)
        if m: return int(m.group(1)) + int(m.group(2))/int(m.group(3))
        m = re.fullmatch(r'(\d+)/(\d+)', t)
        if m: return int(m.group(1))/int(m.group(2))
        return float(t)
    NUM = r'(\d+(?:-\d+/\d+|/\d+|\.\d+)?)'
    width = None
    for pat in (NUM + r'\s*"\s*x\s*\d+(?:\.\d+)?\s*mm',   # vinyl/laminate: width before Xmm
                NUM + r'\s*"\s*x\s*3/4',                      # modern/solid: width before 3/4"
                r'3/4\s*"\s*x\s*' + NUM + r'\s*"'):           # legacy: width after 3/4"
        m = re.search(pat, name)
        if m:
            try: width = frac(m.group(1))
            except (ValueError, ZeroDivisionError): width = None
            if width is not None: break
    tm = re.search(r'x\s*(\d+(?:\.\d+)?)\s*mm\s*x', name)
    thick = float(tm.group(1)) if tm else (19.05 if re.search(r'3/4\s*"', name) else None)
    bm = re.search(r'(\d+(?:\.\d+)?)\s*sf\s*/\s*b', name, re.I) or re.search(r'\((\d+(?:\.\d+)?)\s*sf/box\)', name, re.I)
    ls.append(dict(uuid=str(d['id']).strip(), sku=str(d.get('sku') or '').strip(), name=name,
                   fam=fam, mould=is_mould, cols=cols, colls=colls, codes=codes,
                   width=width, thick=thick, box=float(bm.group(1)) if bm else None,
                   cost=f(d.get('supply_price')), supplier=str(d.get('supplier_name') or '').strip()))

# ---------------------------------------------------------------- load AT
at = list(csv.DictReader(open(AT, encoding='utf-8')))
FAMMAP = {'HWD': 'HWD', 'ENG': 'ENG', 'LVP': 'VIN', 'LAM': 'LAM', 'ACC': 'ACC'}
MOULD_T = {'t-moulding': 'T-MOULD', 'reducer': 'REDUCER', 'nosing': 'NOSING'}
MOULD_M = {'spc': 'VINYL', 'laminate': 'LAMINATE'}

def at_colour(r):
    n = r['Product name']
    if '—' not in n: return ''
    tail = n.split('—')[-1].strip()
    tail = re.sub(r'\s*\([^)]*\)\s*$', '', tail).strip()      # drop trailing grade paren
    return al(tail)

cands = {}
for i, r in enumerate(at):
    fam = FAMMAP[r['SKU'][:3]]
    out = []
    if fam == 'ACC':
        p = [s.strip() for s in r['Product name'].split('|')]
        want_t, want_m = MOULD_T.get(p[1].lower()), MOULD_M.get(p[2].lower())
        for L in ls:
            if not L['mould']: continue
            u = L['name'].upper()
            if want_t and want_m and want_t in u and want_m in u:
                out.append(dict(uuid=L['uuid'], is_exact=True, passes=2, conflicts=0, ls=L,
                                why=f"moulding type+material bridge ({want_m} {want_t})"))
        cands[i] = out; continue

    aw, ath, abox, acost = f(r['Width (in)']), f(r['Thickness (mm)']), f(r['Box size (sf)']), f(r['Cost/unit'])
    acoll, acol, acode = strip_coll(r['Collection']), at_colour(r), str(r['Supplier SKU']).strip().upper()

    for L in ls:
        if L['fam'] != fam or L['mould']: continue
        exact = False; why = []
        if fam in ('VIN', 'LAM'):
            if acode and acode in L['codes']: exact = True; why.append(f"code {acode}")
        else:
            for c in L['cols']:
                if len(c) >= 3 and near(c, acol): exact = True; why.append(f"colour '{c}'"); break
        if not exact: continue
        P = C = 0; det = []
        # Collection is only comparable for the named-collection families. Vinyl/laminate
        # are identified by numeric code; LS calls them "#33 Color Code Series" and the new
        # list calls them "5.5mm SPC Click 6"" — different naming, not a conflict.
        collhit = None
        if fam == 'ENG' and acoll and L['colls']:
            collhit = any(near(x, acoll) or (len(acoll) >= 5 and (acoll in x or x in acoll))
                          for x in L['colls'] if x)
            if collhit: P += 1; det.append('collection')
            else: C += 1; det.append('COLLECTION CONFLICT')
        for lbl, a, b, tol in (('width', aw, L['width'], 0.3), ('thickness', ath, L['thick'], 0.15),
                               ('box', abox, L['box'], 0.6), ('cost', acost, L['cost'], 0.005)):
            if a is None or b is None: continue
            if abs(a-b) <= tol:
                P += 1; det.append(lbl)
            elif lbl == 'cost':
                det.append(f'cost CHANGED (LS ${b:.2f} -> list ${a:.2f})')   # expected on a new list
            else:
                C += 1; det.append(f'{lbl} CONFLICT (LS {b} vs list {a})')
        # Identity gates — a spec difference here means a DIFFERENT product, not a drifted
        # one, so the candidate is rejected rather than flagged. Width separates 6" from
        # 7.5" plank; thickness separates the 7mm vinyl line from the new 8mm one that
        # reuses the same colour codes.
        if aw is not None and L['width'] is not None and abs(aw - L['width']) > 0.3:
            continue
        if fam in ('VIN', 'LAM') and ath is not None and L['thick'] is not None \
           and abs(ath - L['thick']) > 0.15:
            continue
        out.append(dict(uuid=L['uuid'], is_exact=exact, passes=P, conflicts=C, ls=L,
                        why='; '.join(why + det)))
    out.sort(key=lambda c: (c['is_exact'], c['passes'], -c['conflicts']), reverse=True)
    cands[i] = out

# ------------------------------------------------- one-to-one resolution
res = {i: None for i in cands}
assigned = {}; ptr = {i: 0 for i in cands}
for i in cands:
    if not cands[i]: res[i] = dict(uuid=None, status='NOT_FOUND', note='No LS candidate — new product, not yet in Lightspeed')
def cur(i):
    cl = cands[i]
    while ptr[i] < len(cl) and cl[ptr[i]]['uuid'] in assigned: ptr[i] += 1
    return cl[ptr[i]] if ptr[i] < len(cl) else None
key = lambda c: (1 if c['is_exact'] else 0, c['passes'], -c['conflicts'])
changed = True
while changed:
    changed = False; claims = {}
    for i in cands:
        if res[i]: continue
        c = cur(i)
        if c is None:
            res[i] = dict(uuid=None, status='DUPLICATE', note='All matching LS UUIDs claimed by stronger rows'); changed = True; continue
        claims.setdefault(c['uuid'], []).append((i, c))
    for uuid, cl in claims.items():
        if uuid in assigned: continue
        if len(cl) == 1:
            i, c = cl[0]; assigned[uuid] = i
            res[i] = dict(uuid=uuid, status='OK', note=f"Matched LS sku {c['ls']['sku']} — {c['why']}"); changed = True
        else:
            cl.sort(key=lambda x: key(x[1]), reverse=True)
            if key(cl[0][1]) == key(cl[1][1]):
                for i, c in cl:
                    if key(c) == key(cl[0][1]):
                        res[i] = dict(uuid=None, status='AMBIGUOUS',
                                      note=f"Contends for LS {uuid} ({c['ls']['sku']}) with " +
                                           ', '.join(at[j]['SKU'] for j, _ in cl if j != i)); changed = True
                assigned[uuid] = None
            else:
                i, c = cl[0]; assigned[uuid] = i
                res[i] = dict(uuid=uuid, status='OK',
                              note=f"Matched LS sku {c['ls']['sku']} — {c['why']} [won contention vs " +
                                   ', '.join(at[j]['SKU'] for j, _ in cl[1:]) + "]"); changed = True
                for j, _ in cl[1:]:
                    if not res[j]: ptr[j] += 1; changed = True

written = [v['uuid'] for v in res.values() if v and v['uuid']]
assert len(written) == len(set(written)), "duplicate UUID assignment"

# ---------------------------------------------------------------- write
# CSV only (Albert, 2026-09-09), per the standing "every export is a .csv" rule.
# The `LS match status` / `LS match notes` helper columns carry what the highlighting did.
COLS = list(at[0].keys())
for i, r in enumerate(at):
    r['Lightspeed ID'] = res[i]['uuid'] or ''

CSVOUT = "/home/user/titan-agents-repo/ingest/2026-09-09/tosca_airtable_upload_2026-09-09.csv"
with open(CSVOUT, 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
    w.writerow(COLS + ['LS match status', 'LS match notes'])
    for i, r in enumerate(at):
        w.writerow(['' if r[c] is None else r[c] for c in COLS] + [res[i]['status'], res[i]['note']])

# ---------------------------------------------------------------- report
import collections
st = collections.Counter(v['status'] for v in res.values())
print("STATUS:", dict(st), " total:", len(at))
print("OK rows with a real CONFLICT:", sum(1 for v in res.values() if v['status']=='OK' and 'CONFLICT' in v['note']))
print("OK rows where cost changed  :", sum(1 for v in res.values() if v['status']=='OK' and 'CHANGED' in v['note']))
print()
for s in ('OK',):
    print(f"--- {s} sample by family ---")
    seen = set()
    for i, r in enumerate(at):
        if res[i]['status'] != s: continue
        k = r['SKU'][:3]
        if k in seen: continue
        seen.add(k); print(f"  {r['SKU']:<15} {r['Product name'][:44]:<44} -> {res[i]['uuid'][:8]} | {res[i]['note'][:70]}")
print()
print("--- OK rows WITH conflicts (review) ---")
for i, r in enumerate(at):
    if res[i]['status'] == 'OK' and 'CONFLICT' in res[i]['note']:
        print(f"  {r['SKU']:<15} {r['Product name'][:42]:<42} | {res[i]['note'][:110]}")
print()
for s in ('AMBIGUOUS', 'DUPLICATE'):
    rows = [(at[i]['SKU'], at[i]['Product name'], res[i]['note']) for i in res if res[i]['status'] == s]
    print(f"--- {s} ({len(rows)}) ---")
    for a, b, c in rows[:15]: print(f"  {a:<15} {b[:42]:<42} | {c[:90]}")
print()
nf = [(at[i]['SKU'], at[i]['Product name']) for i in res if res[i]['status'] == 'NOT_FOUND']
print(f"--- NOT_FOUND ({len(nf)}) by collection ---")
cc = collections.Counter(at[i]['Collection'] for i in res if res[i]['status'] == 'NOT_FOUND')
for k, v in cc.most_common(): print(f"  {v:>3}  {k}")
print()
used = set(written)
print("LS rows with NO Airtable counterpart (ignored by design):", sum(1 for L in ls if L['uuid'] not in used))
print("saved:", OUT)
