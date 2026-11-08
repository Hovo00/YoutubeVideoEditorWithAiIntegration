"""New parts added on top of the kept transcript (intro, outro, news...).

The app writes the kept text to workspace/script.md as numbered sections;
Claude (AI_EDITING_INSTRUCTIONS.md, Mode 4) answers with workspace/
additions.md, which contains ONLY new blocks, each anchored before/after one
numbered section. The original text is never sent back, so it can't be
changed by accident — it always comes from the transcript/outline as before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .chunker import TextChunk, _strip_non_speech_tags


@dataclass
class Addition:
    title: str
    text: str
    # Original-timeline time the new part is inserted at (see
    # editor.build_timeline) — a time, not a section number, so it stays
    # put if the cuts are changed afterwards.
    anchor: float
    position: str  # "before" / "after"
    section: int  # 1-based section number it was anchored to


def _format_time(seconds: float) -> str:
    hours, rest = divmod(max(0.0, seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:04.1f}"


def build_script(chunks: list[TextChunk], language: str) -> str:
    """workspace/script.md — what Claude reads in Mode 4. Section numbers
    are what additions.md anchors to."""
    kept = sum(c.slot_duration for c in chunks)
    lines = [
        "# Current script (written by the app — read only, do not edit)",
        "",
        f"Language: {language or 'unknown'} · Sections: {len(chunks)} · "
        f"Kept video length: {_format_time(kept)}",
        "",
    ]
    for number, chunk in enumerate(chunks, start=1):
        title = chunk.title or f"Part {number}"
        lines += [
            f"## [{number}] {title} ({_format_time(chunk.start)} - {_format_time(chunk.end)})",
            chunk.text,
            "",
        ]
    return "\n".join(lines)


_NEW_HEADING_RE = re.compile(
    r"^##\s*NEW\s+(before|after)\s+\[?(\d+)\]?\s*(?:\|\s*(.*?))?\s*$", re.IGNORECASE
)
_ANY_HEADING_RE = re.compile(r"^#{1,2}\s")


def parse_additions(
    text: str, chunks: list[TextChunk], duration: float
) -> tuple[list[Addition], list[str]]:
    """Reads additions.md against the same chunk list script.md was built
    from. Returns the additions in file order plus warnings for blocks that
    had to be skipped."""
    additions: list[Addition] = []
    warnings: list[str] = []

    current: dict | None = None
    body: list[str] = []

    def flush() -> None:
        if current is None:
            return
        block_text = "\n".join(body).strip()
        number = current["number"]
        label = f"NEW {current['position']} {number}"
        if not 1 <= number <= len(chunks):
            warnings.append(f"Skipped '{label}': there is no section {number} (script has {len(chunks)}).")
        elif not block_text:
            warnings.append(f"Skipped '{label}': it has no text.")
        else:
            chunk = chunks[number - 1]
            if current["position"] == "before":
                # Before the first section means the very start of the video,
                # not the first spoken word (which can be a moment in).
                anchor = 0.0 if number == 1 else chunk.start
            else:
                anchor = duration if number == len(chunks) else chunk.end
            additions.append(
                Addition(
                    title=current["title"] or ("Intro" if anchor == 0.0 else "New part"),
                    text=block_text,
                    anchor=anchor,
                    position=current["position"],
                    section=number,
                )
            )

    for line in text.splitlines():
        match = _NEW_HEADING_RE.match(line)
        if match:
            flush()
            current = {
                "position": match.group(1).lower(),
                "number": int(match.group(2)),
                "title": (match.group(3) or "").strip(),
            }
            body = []
        elif _ANY_HEADING_RE.match(line):
            # SOURCES / NOTES / QUESTIONS etc. end a block and aren't spoken.
            flush()
            current = None
            body = []
        elif current is not None:
            body.append(line)
    flush()

    if not additions and not warnings:
        warnings.append("additions.md has no '## NEW before/after N | Title' blocks.")
    return additions, warnings


def merge_additions(chunks: list[TextChunk], additions: list[dict]) -> list[TextChunk]:
    """Slots the added parts in among the original chunks by anchor time —
    an addition goes before any original chunk starting at or after its
    anchor; additions sharing an anchor keep their file order."""
    added = [
        TextChunk(
            text=_strip_non_speech_tags(a["text"]),
            start=a["anchor"],
            end=a["anchor"],
            slot_duration=0.0,
            title=a["title"],
            kind="added",
            addition_index=index,
        )
        for index, a in enumerate(additions)
    ]
    keyed = [((c.start, 1), c) for c in chunks] + [((c.start, 0), c) for c in added]
    keyed.sort(key=lambda pair: pair[0])
    return [chunk for _, chunk in keyed]
