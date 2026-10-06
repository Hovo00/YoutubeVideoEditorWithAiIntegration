"""Parsing for VTT transcripts and the structured AI editing response
described in AI_EDITING_INSTRUCTIONS.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TIMESTAMP_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})")
REMOVED_LINE_TS_RE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})"
)
QUOTED_RE = re.compile(r'"([^"]*)"')
HEADING_RE = re.compile(r"^#{1,6}\s*(.+?)\s*$", re.MULTILINE)

CANONICAL_SECTIONS = ("REMOVED", "EDITED_TRANSCRIPT", "CHANGE_LOG", "QUESTIONS")


@dataclass
class Cue:
    start: float
    end: float
    text: str


@dataclass
class RemovedSegment:
    start: float
    end: float
    text: str = ""
    reason: str = ""


@dataclass
class ParsedResponse:
    removed: list[RemovedSegment] = field(default_factory=list)
    edited_transcript: list[Cue] = field(default_factory=list)
    change_log: str = ""
    questions: str = ""
    warnings: list[str] = field(default_factory=list)


def parse_timestamp(raw: str) -> float:
    match = TIMESTAMP_RE.search(raw)
    if not match:
        raise ValueError(f"Not a valid timestamp: {raw!r}")
    hours, minutes, seconds, millis = match.groups()
    millis = millis.ljust(3, "0")[:3]
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000.0


def clean_text(text: str) -> str:
    text = text.replace("\n", " ")
    return " ".join(text.split()).strip()


def parse_vtt(text: str) -> list[Cue]:
    """Parse raw WEBVTT cue blocks into a list of Cue objects.

    Lines that aren't a "start --> end" timestamp line (headers, cue
    numbers, NOTE blocks) are skipped rather than erroring, since
    auto-generated captions and pasted excerpts vary in what they include.
    """

    lines = text.splitlines()
    cues: list[Cue] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].strip()

        if "-->" in line:
            start_raw, _, end_raw = line.partition("-->")
            try:
                start = parse_timestamp(start_raw)
                end = parse_timestamp(end_raw)
            except ValueError:
                i += 1
                continue

            i += 1
            text_lines = []
            while i < n and lines[i].strip() != "":
                text_lines.append(lines[i])
                i += 1

            cue_text = clean_text(" ".join(text_lines))
            if cue_text:
                cues.append(Cue(start=start, end=end, text=cue_text))
        else:
            i += 1

    return cues


def _canonical_heading(raw_heading: str) -> str | None:
    key = raw_heading.strip().upper().replace(" ", "_")
    for name in CANONICAL_SECTIONS:
        if key == name or key.startswith(name):
            return name
    return None


def split_sections(text: str) -> dict[str, str]:
    matches = list(HEADING_RE.finditer(text))
    sections: dict[str, str] = {}

    for idx, match in enumerate(matches):
        canonical = _canonical_heading(match.group(1))
        if not canonical:
            continue
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sections[canonical] = text[start:end].strip()

    return sections


def parse_removed_section(section_text: str) -> tuple[list[RemovedSegment], list[str]]:
    segments: list[RemovedSegment] = []
    warnings: list[str] = []

    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        line = re.sub(r"^[-*•]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        if not line:
            continue

        ts_match = REMOVED_LINE_TS_RE.search(line)
        if not ts_match:
            warnings.append(f"Could not find a timestamp range in REMOVED line: {raw_line!r}")
            continue

        start = parse_timestamp(ts_match.group(1))
        end = parse_timestamp(ts_match.group(2))

        if end <= start:
            warnings.append(f"Skipped invalid range (end <= start): {raw_line!r}")
            continue

        remainder = line[ts_match.end():]
        quoted = QUOTED_RE.search(remainder)
        text = quoted.group(1) if quoted else ""
        reason_part = remainder[quoted.end():] if quoted else remainder
        reason = reason_part.strip(" |\t-")

        segments.append(RemovedSegment(start=start, end=end, text=text, reason=reason))

    return segments, warnings


def parse_ai_response(text: str) -> ParsedResponse:
    sections = split_sections(text)
    warnings: list[str] = []

    if not sections:
        warnings.append(
            "No '## REMOVED' / '## EDITED_TRANSCRIPT' headings found in the pasted text — "
            "make sure you pasted the AI's full structured reply, not just the edited transcript."
        )

    removed, removed_warnings = parse_removed_section(sections.get("REMOVED", ""))
    warnings.extend(removed_warnings)

    edited_raw = sections.get("EDITED_TRANSCRIPT", "")
    edited_cues = parse_vtt(edited_raw) if edited_raw else []

    if "REMOVED" in sections and not removed:
        warnings.append("Found a REMOVED section but could not parse any cut ranges from it.")

    return ParsedResponse(
        removed=removed,
        edited_transcript=edited_cues,
        change_log=sections.get("CHANGE_LOG", ""),
        questions=sections.get("QUESTIONS", ""),
        warnings=warnings,
    )
