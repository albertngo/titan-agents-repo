#!/usr/bin/env python3
"""
clean_transcript.py — Strip filler from Titan Flooring Teams meeting transcripts.

Usage:
    python clean_transcript.py <input> <output.md>

Input formats (auto-detected):

1. WEBVTT — the live Graph API transcript (meeting-transcript:///events/...),
   the default source per SKILL.md Step 1. Standard WebVTT cues, Teams-style
   speaker tagging:

    WEBVTT

    00:00:01.000 --> 00:00:05.000
    <v Albert Ngo>Yeah, so on the Nasser project we...</v>

   A cue with no <v Name> tag is kept with speaker "Unknown" rather than
   dropped — better to surface an attribution gap than silently lose content.

2. Teams .docx export (markdown after extract-text), manual-upload fallback,
   with speaker turns formatted like:

    **Albert Ngo   **5:22
    Yeah, so on the Nasser project we...

Behavior (both formats):
- Groups content into speaker turns.
- Drops turns that are pure filler (short AND composed only of filler tokens).
- Collapses internal whitespace but preserves speaker labels and timestamps
  exactly (needed downstream for citation).
- Normalizes timestamps to mm:ss (or h:mm:ss past one hour) either way, so
  citations read the same regardless of source format.
- Prints a before/after stats summary to stderr.

Rules mirror the skill: a turn is dropped only if it has fewer than 4 words
AND every word is a filler token. Anything with substance survives, however
short ("$300 billed" survives; "Yeah, yeah okay" does not).
"""

import re
import sys
from pathlib import Path

# Header for a speaker turn in the .docx-export format, tolerant of variable
# spacing inside the bold markers and of timestamps like 5:22, 12:03, 1:02:45.
DOCX_TURN_HEADER = re.compile(
    r"^\*\*(?P<speaker>[^*]+?)\s*\*\*\s*(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\s*$"
)

# WebVTT cue timing line, e.g. "00:00:05.500 --> 00:00:08.000" (cue settings
# after the end time, if any, are ignored).
VTT_TIMING = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}"
)

# Teams voice tag: <v Speaker Name>text</v> — closing tag is sometimes
# missing/malformed in real exports, so don't require it.
VTT_VOICE_TAG = re.compile(r"<v\s+([^>]+)>(.*?)(?:</v>)?\s*$", re.DOTALL)

FILLER_TOKENS = {
    # affirmations / backchannel
    "yeah", "yea", "yep", "yes", "no", "nope", "ok", "okay", "kay", "k",
    "mhm", "mm", "mmm", "hmm", "hm", "uh", "um", "uhh", "umm", "huh",
    "right", "sure", "cool", "nice", "good", "great", "perfect", "exactly",
    "correct", "true", "gotcha", "alright", "aight",
    # connective fragments
    "so", "and", "but", "or", "the", "a", "an", "like", "well", "then",
    "just", "i", "me", "we", "you", "it", "its", "that", "this", "there",
    "oh", "ah", "eh", "hey", "hi", "hello", "bye", "thanks", "thank",
    # common truncated-turn artifacts
    "mean", "know", "see", "was", "is", "are", "do", "did", "not",
}

WORD_RE = re.compile(r"[a-zA-Z']+")


def is_filler_turn(text: str) -> bool:
    """Drop only if <4 words AND every alphabetic word is a filler token.

    Anything containing a digit, dollar amount, or a non-filler word is kept.
    """
    stripped = text.strip()
    if not stripped:
        return True
    # Numbers / amounts carry signal even in tiny turns.
    if re.search(r"[\d$]", stripped):
        return False
    words = WORD_RE.findall(stripped.lower())
    if not words:
        return True  # punctuation-only / artifact
    if len(words) >= 4:
        return False
    return all(w in FILLER_TOKENS for w in words)


def vtt_ts_to_mmss(ts: str) -> str:
    """'00:12:34.567' -> '12:34', or 'h:mm:ss' past one hour."""
    h, m, s_ms = ts.split(":")
    s = s_ms.split(".")[0]
    h, m = int(h), int(m)
    if h:
        return f"{h}:{m:02d}:{s}"
    return f"{m}:{s}"


def looks_like_vtt(lines) -> bool:
    for line in lines[:5]:
        if line.strip().upper().startswith("WEBVTT"):
            return True
    return False


def parse_docx_turns(lines):
    """Yield (speaker, timestamp, body_text) tuples from the docx-export format."""
    speaker, ts, body = None, None, []
    for line in lines:
        m = DOCX_TURN_HEADER.match(line.strip())
        if m:
            if speaker is not None:
                yield speaker, ts, " ".join(body).strip()
            speaker = m.group("speaker").strip()
            ts = m.group("ts")
            body = []
        else:
            if line.strip():
                body.append(line.strip())
    if speaker is not None:
        yield speaker, ts, " ".join(body).strip()


def parse_vtt_turns(lines):
    """Yield (speaker, timestamp, body_text) tuples from WebVTT cues.

    Consecutive cues from the same speaker with no gap in content are NOT
    merged — each cue is its own turn, timestamped at its own start. This
    keeps citation timestamps accurate; downstream readers see more, shorter
    turns than the docx format tends to produce, which is fine.
    """
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if not line or line.upper().startswith("WEBVTT") or line.isdigit():
            i += 1
            continue
        m = VTT_TIMING.match(line)
        if not m:
            i += 1
            continue
        ts = vtt_ts_to_mmss(m.group("start"))
        i += 1
        text_lines = []
        while i < n and lines[i].strip():
            text_lines.append(lines[i].strip())
            i += 1
        raw = " ".join(text_lines)
        vm = VTT_VOICE_TAG.match(raw)
        if vm:
            speaker = vm.group(1).strip()
            body = vm.group(2).strip()
        else:
            speaker = "Unknown"
            body = re.sub(r"</?v[^>]*>", "", raw).strip()
        yield speaker, ts, body


def main():
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    lines = src.read_text(encoding="utf-8", errors="replace").splitlines()

    fmt = "vtt" if looks_like_vtt(lines) else "docx"
    turns = parse_vtt_turns(lines) if fmt == "vtt" else parse_docx_turns(lines)

    kept, dropped = [], 0
    total = 0
    for speaker, ts, body in turns:
        total += 1
        # Collapse internal whitespace; preserve label + timestamp verbatim.
        body = re.sub(r"\s+", " ", body).strip()
        if is_filler_turn(body):
            dropped += 1
            continue
        kept.append(f"**{speaker}** · *{ts}*\n{body}\n")

    if total == 0:
        print(
            f"WARNING: no speaker turns matched the detected '{fmt}' format. "
            "Check the source content — falling back to pass-through with "
            "blank-line filler filtering.",
            file=sys.stderr,
        )
        out_lines = [l for l in lines if not is_filler_turn(l)]
        dst.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    else:
        dst.write_text("\n".join(kept), encoding="utf-8")

    in_kb = src.stat().st_size / 1024
    out_kb = dst.stat().st_size / 1024
    print(
        f"clean_transcript [{fmt}]: {total} turns in, {len(kept)} kept, "
        f"{dropped} dropped ({dropped / max(total, 1):.0%} filler). "
        f"{in_kb:.0f}KB -> {out_kb:.0f}KB",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
