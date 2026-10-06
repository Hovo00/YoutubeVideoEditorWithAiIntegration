"""Parsing for VTT transcripts and the structured AI editing response
described in AI_EDITING_INSTRUCTIONS.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TIMESTAMP_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})")
TIMESTAMP_PAIR_RE = r"\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}"

# A single REMOVED entry: a timestamp range, an optional quoted cue text, and
# a reason — all lazily captured up to wherever the *next* timestamp range
# starts (or end of text). This works whether the AI put one entry per line
# or ran them all together as one paragraph (both happen in practice).
REMOVED_ENTRY_RE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})"
    r"\s*\|?\s*"
    r'(?:"([^"]*)")?'
    r"\s*\|?\s*"
    r"(.*?)"
    r"(?=" + TIMESTAMP_PAIR_RE + r"|\Z)",
    re.DOTALL,
)

# Cue-setting tokens that can trail a VTT timestamp line (not actual cue text).
CUE_SETTINGS_RE = re.compile(
    r"^(?:(?:align|position|size|line|vertical|region):\S+\s*)+$", re.IGNORECASE
)

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
    """Parse VTT-style cue blocks into a list of Cue objects.

    Handles two layouts, since different AIs (and real YouTube VTT files)
    vary here:

    1. Standard WebVTT — timestamp line alone, cue text on the following
       line(s), cues separated by a blank line.
    2. "Timestamp + text on one line" — some AI replies write
       "HH:MM:SS.mmm --> HH:MM:SS.mmm some cue text" with no line break
       and no blank-line separator between cues.

    Lines that aren't a "start --> end" timestamp line (headers, cue
    numbers, NOTE blocks) are skipped rather than erroring.
    """

    lines = text.splitlines()
    cues: list[Cue] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].strip()

        if "-->" in line:
            start_raw, _, rest = line.partition("-->")
            end_match = TIMESTAMP_RE.search(rest)

            if not end_match:
                i += 1
                continue

            try:
                start = parse_timestamp(start_raw)
            except ValueError:
                i += 1
                continue

            end = parse_timestamp(end_match.group(0))
            remainder = rest[end_match.end():].strip()
            i += 1

            if remainder and not CUE_SETTINGS_RE.match(remainder):
                cue_text = clean_text(remainder)
            else:
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


def _match_heading(line: str) -> str | None:
    """Recognize a line as one of our section headings, whether it's
    markdown ("## REMOVED"), bold ("**REMOVED**"), or just a bare word on
    its own line ("REMOVED") — different AIs format these differently.
    """

    candidate = line.strip().strip("#*_>- \t").rstrip(":").strip()

    if not candidate or len(candidate) > 40:
        return None

    key = candidate.upper().replace(" ", "_")

    for name in CANONICAL_SECTIONS:
        if key == name or key.startswith(name + "_"):
            return name

    return None


def split_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in text.splitlines():
        heading = _match_heading(line)
        if heading:
            current = heading
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)

    return {name: "\n".join(body).strip() for name, body in sections.items()}


def parse_removed_section(section_text: str) -> tuple[list[RemovedSegment], list[str]]:
    segments: list[RemovedSegment] = []
    warnings: list[str] = []

    for match in REMOVED_ENTRY_RE.finditer(section_text):
        start_raw, end_raw, text, reason_raw = match.groups()

        start = parse_timestamp(start_raw)
        end = parse_timestamp(end_raw)

        if end <= start:
            warnings.append(f"Skipped invalid range (end <= start): {start_raw} --> {end_raw}")
            continue

        reason = (reason_raw or "").strip(" |\t\r\n-")
        segments.append(RemovedSegment(start=start, end=end, text=text or "", reason=reason))

    return segments, warnings


def parse_ai_response(text: str) -> ParsedResponse:
    sections = split_sections(text)
    warnings: list[str] = []

    if not sections:
        warnings.append(
            "No REMOVED / EDITED_TRANSCRIPT section headings found in the pasted text — "
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
