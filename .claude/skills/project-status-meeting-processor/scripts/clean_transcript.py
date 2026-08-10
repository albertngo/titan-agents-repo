#!/usr/bin/env python3
"""
clean_transcript.py — Strip filler from Microsoft Teams meeting transcripts.

Part of the `project-status-meeting-processor` skill (Titan Flooring).

Consumes the markdown produced by `extract-text transcript.docx` and emits a
cleaned transcript with speaker labels and timestamps preserved for citation.

Cleaning rule (per SKILL.md Step 1):
    Drop a turn if it is shorter than MIN_WORDS *and* consists only of filler
    tokens. Both conditions must hold — a short but substantive turn ("Roy
    quoted 2400") survives, and a long rambling filler turn survives too, since
    dropping it risks losing content.

Also drops empty turns and merges consecutive turns from the same speaker,
which Teams fragments heavily.

Usage:
    python clean_transcript.py IN.md OUT.md
    python clean_transcript.py IN.md OUT.md --format notion
    python clean_transcript.py IN.md OUT.md --min-words 5 --keep-merge-off

Formats:
    raw     (default) "**Speaker**  m:ss" header, body on following line
    notion  "**Speaker** · *m:ss*" header, body collapsed to one line
            (matches SKILL.md Step 7.6.1 for the Notion transcript sub-page)
"""

import argparse
import re
import sys

MIN_WORDS = 4

# Tokens that carry no meeting content on their own.
FILLER = {
    "yeah", "yep", "yup", "yes", "no", "nope", "ok", "okay", "mhm", "mm",
    "mmhmm", "hmm", "huh", "uh", "um", "uhh", "umm", "ah", "oh", "eh",
    "right", "sure", "exactly", "correct", "true", "gotcha", "got", "it",
    "alright", "cool", "nice", "good", "great", "perfect", "awesome",
    "the", "a", "and", "so", "but", "well", "like", "just", "i", "you",
    "we", "he", "she", "they", "that", "this", "is", "was", "to", "of",
    "thanks", "thank", "please", "sorry", "bye", "hello", "hi", "hey",
    "wait", "sound", "sounds", "know", "mean", "think", "guess",
}

# **Speaker Name   **5:22   /   **Speaker Name**0:03:14   /   Speaker Name  5:22
HEADER_RE = re.compile(
    r"^\s*(?:\*\*)?\s*(?P<speaker>[^*\d\n][^*\n]*?)\s*(?:\*\*)?\s*"
    r"(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\s*(?:\*\*)?\s*$"
)

WORD_RE = re.compile(r"[A-Za-z0-9']+")


def normalize_ts(ts: str) -> str:
    """0:05:22 -> 5:22 ; 5:22 stays 5:22."""
    parts = ts.split(":")
    if len(parts) == 3 and parts[0] in ("0", "00"):
        return f"{int(parts[1])}:{parts[2]}"
    return ts


def parse_turns(text: str):
    """Yield (speaker, timestamp, body) tuples in document order."""
    turns, speaker, ts, body = [], None, None, []
    for line in text.splitlines():
        m = HEADER_RE.match(line)
        if m:
            if speaker is not None:
                turns.append((speaker, ts, " ".join(body).strip()))
            speaker = m.group("speaker").strip()
            ts = normalize_ts(m.group("ts"))
            body = []
        elif speaker is not None:
            if line.strip():
                body.append(line.strip())
    if speaker is not None:
        turns.append((speaker, ts, " ".join(body).strip()))
    return turns


def is_filler(body: str, min_words: int) -> bool:
    words = WORD_RE.findall(body.lower())
    if not words:
        return True
    if len(words) >= min_words:
        return False
    return all(w in FILLER for w in words)


def merge_consecutive(turns):
    """Collapse back-to-back turns from the same speaker, keeping first ts."""
    merged = []
    for speaker, ts, body in turns:
        if merged and merged[-1][0] == speaker:
            prev_speaker, prev_ts, prev_body = merged[-1]
            joined = f"{prev_body} {body}".strip()
            merged[-1] = (prev_speaker, prev_ts, joined)
        else:
            merged.append((speaker, ts, body))
    return merged


def render(turns, fmt: str) -> str:
    out = []
    for speaker, ts, body in turns:
        if fmt == "notion":
            out.append(f"**{speaker}** · *{ts}*")
            out.append(" ".join(body.split()))
        else:
            out.append(f"**{speaker}**  {ts}")
            out.append(body)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description="Strip filler from Teams transcripts.")
    ap.add_argument("infile")
    ap.add_argument("outfile")
    ap.add_argument("--format", choices=["raw", "notion"], default="raw")
    ap.add_argument("--min-words", type=int, default=MIN_WORDS)
    ap.add_argument("--keep-merge-off", action="store_true",
                    help="Do not merge consecutive same-speaker turns.")
    args = ap.parse_args()

    with open(args.infile, encoding="utf-8", errors="replace") as f:
        raw = f.read()

    turns = parse_turns(raw)
    if not turns:
        sys.exit("No speaker turns found — check that the input is an "
                 "extract-text export of a Teams .docx transcript.")

    kept = [t for t in turns if not is_filler(t[2], args.min_words)]
    if not args.keep_merge_off:
        kept = merge_consecutive(kept)

    with open(args.outfile, "w", encoding="utf-8") as f:
        f.write(render(kept, args.format))

    dropped = len(turns) - len([t for t in turns if not is_filler(t[2], args.min_words)])
    pct = (dropped / len(turns) * 100) if turns else 0
    print(f"Turns in:      {len(turns)}", file=sys.stderr)
    print(f"Filler dropped: {dropped} ({pct:.0f}%)", file=sys.stderr)
    print(f"Turns out:     {len(kept)}", file=sys.stderr)
    print(f"Wrote:         {args.outfile}", file=sys.stderr)


if __name__ == "__main__":
    main()
