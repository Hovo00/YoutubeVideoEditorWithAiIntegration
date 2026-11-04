"""Splits the surviving (non-cut) transcript into voice-over chunks.

Preferred mode: one chunk per outline paragraph/sub-paragraph (see
AI_EDITING_INSTRUCTIONS.md Step 1 and parser.parse_outline, which guarantees
non-overlapping sections) — this matches the granularity the outline itself
already chose, instead of an arbitrary character count. Falls back to
~500-character chunks, cut only at cue boundaries, when no outline exists
yet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .editor import Cut, normalize_cuts
from .parser import Cue, OutlineSection

TARGET_CHUNK_CHARS = 500

# Auto-captions mark non-speech audio events with bracketed tags —
# "[музыка]" (music), "[аплодисменты]" (applause), "[laughter]", etc. These
# describe what's happening, they are never actual words anyone said, so a
# TTS voice-over must never read them aloud. Strips any `[...]` tag from
# voice-over text (the transcript data itself, used for cutting/display, is
# untouched — only the text that gets turned into speech is cleaned).
_BRACKETED_TAG_RE = re.compile(r"\[[^\]]*\]")

# ">>" marks a speaker change in auto-captions — transcription notation,
# not a spoken word, same category as the bracketed tags above.
_SPEAKER_MARK_RE = re.compile(r">>")

# Mode 2's review markers (AI_EDITING_INSTRUCTIONS.md, "Correcting Whisper
# errors"): `{corrected: Whisper heard "X"}` follows already-corrected text,
# so the note itself is dropped; `[unclear: X]` keeps Whisper's own words
# rather than leaving a hole mid-sentence. Handled before the generic `[...]`
# stripping above, which would otherwise delete the unclear words too.
_CORRECTED_NOTE_RE = re.compile(r"\{\s*corrected:[^}]*\}", re.IGNORECASE)
_UNCLEAR_RE = re.compile(r"\[\s*unclear:\s*([^\]]*)\]", re.IGNORECASE)


def _strip_non_speech_tags(text: str) -> str:
    text = _CORRECTED_NOTE_RE.sub(" ", text)
    text = _UNCLEAR_RE.sub(r" \1 ", text)
    text = _BRACKETED_TAG_RE.sub(" ", text)
    text = _SPEAKER_MARK_RE.sub(" ", text)
    text = " ".join(text.split())
    return re.sub(r" ([,.!?;:])", r"\1", text)

# When two outline sections heavily overlap (a short "aside" topic squeezed
# between two bigger ones), resolving the overlap can shrink the short one
# down to a sliver with only a fragment of a sentence in it. Rather than
# surface that as its own awkward chunk, fold it into a neighbor.
MIN_CHUNK_CHARS = 150

# Auto-caption cues routinely overlap their neighbors (see
# AI_EDITING_INSTRUCTIONS.md) — treat a cue as "removed"/"in this section"
# only on full containment, not partial overlap, so a neighboring cue that
# merely brushes an edge isn't included/dropped by mistake.
_EPS = 0.01


@dataclass
class TextChunk:
    text: str
    start: float
    end: float
    slot_duration: float
    title: str = ""


def _resolve_chunk_time_overlaps(chunks: list[TextChunk]) -> None:
    """A chunk's start/end come from the raw timestamps of whichever cues
    ended up in it — which can still overlap a neighbor's raw timestamps
    even though no cue or text is shared between them, since auto-caption
    cues routinely overlap their own neighbors. Purely a display/placement
    cleanup (slot_duration and the chunk's text are unaffected): splits an
    overlapping boundary at its midpoint, in place, so adjacent chunks
    never show — or anchor voice-over placement at — an overlapping time
    range."""

    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        curr = chunks[i]
        if curr.start < prev.end:
            midpoint = (prev.end + curr.start) / 2
            prev.end = midpoint
            curr.start = midpoint


def kept_cues(cues: list[Cue], cuts: list[Cut]) -> list[Cue]:
    def is_removed(cue: Cue) -> bool:
        return any(c.start <= cue.start + _EPS and cue.end <= c.end + _EPS for c in cuts)

    return [cue for cue in cues if not is_removed(cue)]


def chunk_kept_cues(cues: list[Cue], target_chars: int = TARGET_CHUNK_CHARS) -> list[TextChunk]:
    """Group consecutive kept cues into chunks of roughly `target_chars`
    characters each. A chunk's `slot_duration` is the real video time it has
    to fill in the final render — cue-overlap within the chunk and gaps from
    cuts elsewhere in the chunk are both accounted for by merging the
    chunk's own cue ranges the same way cuts are merged."""

    chunks: list[TextChunk] = []
    current: list[Cue] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if not current:
            return

        text = _strip_non_speech_tags(" ".join(cue.text for cue in current))

        if text:
            merged = normalize_cuts(
                [Cut(start=cue.start, end=cue.end) for cue in current],
                duration=max(cue.end for cue in current),
            )
            slot_duration = sum(m.end - m.start for m in merged)

            chunks.append(
                TextChunk(
                    text=text,
                    start=current[0].start,
                    end=current[-1].end,
                    slot_duration=slot_duration,
                )
            )
        current = []
        current_len = 0

    for cue in cues:
        current.append(cue)
        current_len += len(cue.text) + 1
        if current_len >= target_chars:
            flush()

    flush()
    _resolve_chunk_time_overlaps(chunks)
    return chunks


def _leaf_sections(sections: list[OutlineSection]) -> list[OutlineSection]:
    """A top-level paragraph that was split into sub-paragraphs shouldn't
    also be used whole — only the leaves of the outline (sub-paragraphs
    where they exist, otherwise the top-level paragraph itself) should
    become chunks, so every moment is covered exactly once."""

    leaves: list[OutlineSection] = []
    for index, section in enumerate(sections):
        if section.level == 2:
            has_children = index + 1 < len(sections) and sections[index + 1].level == 3
            if not has_children:
                leaves.append(section)
        else:
            leaves.append(section)
    return leaves


def _leaf_index_for_cue(cue: Cue, leaves: list[OutlineSection]) -> int:
    """Leaves are contiguous and non-overlapping (see parser._resolve_
    overlaps), so every cue start belongs to exactly one of them.

    This must match the exact convention AI_EDITING_INSTRUCTIONS.md tells
    Claude to use when it writes each section's own verbatim text: a cue
    belongs to whichever paragraph its own START falls into (a paragraph's
    start is inclusive, its end is exclusive). Claude is explicitly
    instructed to choose boundaries so this assignment lines up with real
    sentence breaks — using a different rule here (e.g. assigning by which
    section a cue overlaps *most*) would silently reassign cues Claude
    already placed correctly, pulling a cue's text into the wrong chunk
    even though the outline's own text has it right."""

    for i, section in enumerate(leaves):
        if cue.start < section.end:
            return i
    return len(leaves) - 1


def chunk_by_outline(kept: list[Cue], outline_sections: list[OutlineSection]) -> list[TextChunk]:
    """One chunk per leaf outline section. Every kept cue is assigned to
    exactly one chunk — whichever leaf it overlaps most — never required to
    fit fully inside the section's nominal time range, so a cue that
    straddles a (resolved) section boundary still gets its text included
    somewhere instead of silently falling through the gap between two
    neighbors.

    A chunk's spoken/displayed TEXT comes from the outline section's own
    `body` field, not from re-concatenating the raw cue text — AI_EDITING_
    INSTRUCTIONS.md permits Claude to correct Whisper mis-transcriptions in
    the outline body, so the body is the authoritative, possibly-corrected
    text. Cues are still used to compute `start`/`end`/`slot_duration`
    (real video timing is independent of whether the text was corrected).

    Groups shorter than MIN_CHUNK_CHARS are folded into a neighbor (forward
    where possible, otherwise backward for a trailing short group) so an
    overlap-shrunk section doesn't surface as an orphaned sentence
    fragment; its title/body are kept alongside the neighbor's so the merge
    is visible rather than silent."""

    leaves = _leaf_sections(outline_sections)
    if not leaves:
        return []

    buckets: list[list[Cue]] = [[] for _ in leaves]
    for cue in kept:
        buckets[_leaf_index_for_cue(cue, leaves)].append(cue)

    groups = [
        {"titles": [section.title], "bodies": [section.body], "cues": cues}
        for section, cues in zip(leaves, buckets)
        if cues
    ]

    merged_groups: list[dict] = []
    for index, group in enumerate(groups):
        text_len = len(_strip_non_speech_tags(" ".join(group["bodies"])))
        if text_len < MIN_CHUNK_CHARS and index + 1 < len(groups):
            groups[index + 1]["titles"] = group["titles"] + groups[index + 1]["titles"]
            groups[index + 1]["bodies"] = group["bodies"] + groups[index + 1]["bodies"]
            groups[index + 1]["cues"] = group["cues"] + groups[index + 1]["cues"]
        elif text_len < MIN_CHUNK_CHARS and merged_groups:
            merged_groups[-1]["titles"] += group["titles"]
            merged_groups[-1]["bodies"] += group["bodies"]
            merged_groups[-1]["cues"] += group["cues"]
        else:
            merged_groups.append(group)

    chunks: list[TextChunk] = []

    for group in merged_groups:
        cues = group["cues"]
        text = _strip_non_speech_tags(" ".join(group["bodies"]))
        if not text:
            continue

        merged = normalize_cuts(
            [Cut(start=cue.start, end=cue.end) for cue in cues],
            duration=max(cue.end for cue in cues),
        )
        slot_duration = sum(m.end - m.start for m in merged)

        chunks.append(
            TextChunk(
                text=text,
                start=cues[0].start,
                end=cues[-1].end,
                slot_duration=slot_duration,
                title=" / ".join(group["titles"]),
            )
        )

    _resolve_chunk_time_overlaps(chunks)
    return chunks
