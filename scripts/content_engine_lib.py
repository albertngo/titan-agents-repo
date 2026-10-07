#!/usr/bin/env python3
"""Shared, pure helpers for the content engine scripts.

Used by scripts/topic_harvest.py, topic_rank.py, blog_plan.py, blog_render.py and
blog_sweep.py. Holds no credentials, reaches no platform, writes nothing: every function
here is a pure transform of the registry (platform-settings/content-engine.json) and the
files a command hands it.
"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "platform-settings" / "content-engine.json"
TZ = ZoneInfo("America/Toronto")

WORD = re.compile(r"[a-z0-9]+")


def load_registry(path=None):
    return json.loads(Path(path or REGISTRY_PATH).read_text())


def now_local():
    return datetime.now(TZ)


def today():
    return now_local().strftime("%Y-%m-%d")


def clusters(reg):
    """Cluster slug -> entry, skipping the registry's own `_comment` keys."""
    return {k: v for k, v in reg["clusters"].items() if not k.startswith("_")}


def label_to_slug(reg):
    return {v["label"]: k for k, v in clusters(reg).items()}


def canonical_key(text):
    """Lower-case, alphanumeric tokens joined by single spaces. The dedupe key."""
    return " ".join(WORD.findall((text or "").lower()))


def tokens(text):
    return set(WORD.findall((text or "").lower()))


def jaccard(a, b):
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _padded(query):
    return " " + canonical_key(query) + " "


def _hit(padded_query, needle):
    """Whole-word containment. A needle with spaces (' vs ') is matched as a phrase."""
    n = canonical_key(needle)
    if not n:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", padded_query) is not None


def map_cluster(reg, query):
    """First matching rule wins; None when nothing matches (held cluster_unresolved)."""
    pq = _padded(query)
    for rule in reg["cluster_rules"]["rules"]:
        for needle in rule["any"]:
            if _hit(pq, needle):
                return rule["cluster"]
    return None


def is_local(reg, query):
    pq = _padded(query)
    return any(_hit(pq, tok) for tok in reg["local_tokens"])


def map_intent(reg, query):
    """Returns (intent label, score). First rule wins; registry default otherwise."""
    pq = _padded(query)
    for rule in reg["intent_rules"]["rules"]:
        for needle in rule["any"]:
            if _hit(pq, needle):
                return rule["intent"], float(rule["score"])
    d = reg["intent_rules"]["default"]
    return d["intent"], float(d["score"])


def action_id(target_system, op, target_key, field_names, content=b""):
    """blg-<sha1[:12]> over the parts the contract names. Stable across re-runs."""
    h = hashlib.sha1()
    h.update(target_system.encode())
    h.update(b"|" + op.encode())
    h.update(b"|" + str(target_key).encode())
    h.update(b"|" + ",".join(sorted(field_names)).encode())
    if content:
        h.update(b"|" + hashlib.sha1(content).hexdigest().encode())
    return "blg-" + h.hexdigest()[:12]


def sha1_file(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def slugify(text, max_len=70):
    s = canonical_key(text).replace(" ", "-")
    s = re.sub(r"-+", "-", s).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s


def slug_problem(reg, slug):
    """None when the slug is acceptable, else a held reason."""
    w = reg["website"]
    if not re.match(w["slug_regex"], slug or "") or len(slug) > w["slug_max"]:
        return "slug_invalid"
    if slug in w.get("reserved_slugs", []):
        return "slug_reserved"
    return None


def word_count(text):
    return len(WORD.findall(text or ""))


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
