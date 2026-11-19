"""Pauses inside a voice-over that is shorter than its video window.

Automatic TTS speaks each chunk in one go. When even the slowest speed
leaves a long silence at the end of the chunk's window, the chunk is voiced
in parts with pauses between them instead, so the voice spreads over the
window rather than finishing early. Whatever silence is still left at the
end after that is flagged for review as before.

Pause markers in the text (the user can type them; the app writes them back
after voicing so you can see where it paused and for how long):

    ...в его углу Джорджо Петросяна. ||3 И сразу посыпались вопросы...

    ||      pause here, the app decides how long
    ||3     pause exactly 3 seconds (||1.5 and ||1,5 work too)

Markers are never read aloud. A text with markers is split only at its
markers. Without markers, split points come from workspace/pauses.md,
written by the AI together with the outline (Mode 2 in
AI_EDITING_INSTRUCTIONS.md):

    ## 00:01:23.450 - 00:02:10.000 | Section title
    - after: "и сразу посыпались вопросы." | resume: 00:01:41.200
    - after: "это не просто какой-то кикбоксёр."

`after` quotes the end of a sentence where a pause sounds natural. The
optional `resume` is the time (original video) where speech starts again
after a stretch without speech: the next part waits for it, so the voice
stays in step with the picture. Hints are matched by their quote; the `##`
headings only help a human read the file. Without matching hints the text
is split at sentence ends.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parser import parse_timestamp

# Shortest and longest pause the app picks by itself. A `resume` point may
# wait longer (that silence is in the video too), and a number typed in a
# marker is used as it is.
MIN_PAUSE_SECONDS = 0.35
MAX_PAUSE_SECONDS = 2.5

# A part shorter than this many characters is joined to its neighbour
# rather than voiced alone (a lone "Да." sounds odd between pauses). Only
# for split points the app picks; markers are always kept.
MIN_PART_CHARS = 25

MARKER_RE = re.compile(r"\|\|(\d+(?:[.,]\d+)?)?")

_HINT_RE = re.compile(
    r"""^\s*[-*]\s*after:\s*["«“](?P<quote>.+?)["»”]\s*(?:\|\s*resume:\s*(?P<resume>[\d:.,]+))?\s*$""",
    re.IGNORECASE,
)
_SENTENCE_END_RE = re.compile(r"[.!?…]+[»\"”)]*(?=\s)")


@dataclass
class PauseHint:
    quote: str
    resume: float | None = None


@dataclass
class Part:
    text: str
    resume: float | None = None  # original-timeline time this part should start at
    pause: float | None = None  # fixed pause before this part (from a `||N` marker)
    # The pause before this part is a preferred one (an AI hint or a `||`
    # marker) rather than an ordinary sentence end: it's stretched first.
    preferred: bool = True


def has_markers(text: str) -> bool:
    return bool(MARKER_RE.search(text))


def strip_markers(text: str) -> str:
    """The text as it is spoken."""
    if not has_markers(text):
        return text
    return re.sub(r" ([,.!?;:])", r"\1", " ".join(MARKER_RE.sub(" ", text).split()))


def fixed_pause_total(text: str) -> float:
    return sum(float(m.group(1).replace(",", ".")) for m in MARKER_RE.finditer(text) if m.group(1))


def parse_pause_hints(text: str) -> list[PauseHint]:
    hints = []
    for line in text.splitlines():
        match = _HINT_RE.match(line)
        if not match:
            continue
        resume = None
        if match.group("resume"):
            try:
                resume = parse_timestamp(match.group("resume"))
            except ValueError:
                resume = None
        quote = " ".join(match.group("quote").split())
        if quote:
            hints.append(PauseHint(quote, resume))
    return hints


def _normalize(text: str) -> str:
    # Same length as the input, so positions carry over.
    return text.lower().replace("ё", "е")


def _hint_cuts(text: str, hints: list[PauseHint]) -> dict[int, float | None]:
    """Cut positions (index just after the quoted words) -> resume time."""
    haystack = _normalize(text)
    cuts: dict[int, float | None] = {}
    for hint in hints:
        position = haystack.find(_normalize(hint.quote))
        if position < 0:
            continue
        end = position + len(hint.quote)
        if end < len(text.rstrip()):
            cuts[end] = hint.resume
    return cuts


def _sentence_cuts(text: str) -> dict[int, float | None]:
    return {m.end(): None for m in _SENTENCE_END_RE.finditer(text) if m.end() < len(text.rstrip())}


def _split_at_markers(text: str) -> list[Part]:
    parts: list[Part] = []
    pause: float | None = None
    previous = 0
    for match in list(MARKER_RE.finditer(text)) + [None]:
        end = match.start() if match else len(text)
        piece = text[previous:end].strip()
        if piece:
            parts.append(Part(piece, None, pause if parts else None))
        if match:
            pause = float(match.group(1).replace(",", ".")) if match.group(1) else None
            previous = match.end()
    return parts


def split_into_parts(
    text: str, hints: list[PauseHint], chunk_start: float, chunk_end: float
) -> tuple[list[Part], str]:
    """The chunk's text cut at its pause points, and where those came from:
    "markers" (typed in the text), "hints" (pauses.md) or "sentences"."""
    if has_markers(text):
        return _split_at_markers(text), "markers"

    # Every sentence end is a possible pause; the AI's hints are preferred
    # ones (stretched first) and may carry a resume time.
    hint_cuts = _hint_cuts(text, hints)
    cuts: dict[int, tuple[float | None, bool]] = {pos: (None, False) for pos in _sentence_cuts(text)}
    cuts.update({pos: (resume, True) for pos, resume in hint_cuts.items()})
    source = "hints" if hint_cuts else "sentences"

    parts: list[Part] = []
    previous = 0
    resume, preferred = None, False
    for position in sorted(cuts) + [len(text)]:
        piece = text[previous:position].strip()
        if piece:
            valid = resume if resume is not None and chunk_start < resume < chunk_end else None
            # Without any hints, all sentence ends are equally good.
            parts.append(Part(piece, valid, None, preferred or not hint_cuts))
        previous = position
        resume, preferred = cuts.get(position, (None, False))

    # Join parts that are too short to stand alone. A part that starts at a
    # hint keeps its own start.
    joined: list[Part] = []
    for part in parts:
        if joined and not (part.preferred and hint_cuts) and (
            len(part.text) < MIN_PART_CHARS or len(joined[-1].text) < MIN_PART_CHARS
        ):
            last = joined[-1]
            joined[-1] = Part(f"{last.text} {part.text}", last.resume, last.pause, last.preferred)
        else:
            joined.append(part)
    return joined, source


def plan_starts(
    durations: list[float],
    fixed: list[float | None],
    offsets: list[float | None],
    target: float,
    preferred: list[bool] | None = None,
) -> list[float]:
    """Start time (seconds from the chunk's start) of each part.

    fixed[i]: a pause typed before part i (used as is). offsets[i]: where
    part i should start to match the video (a `resume` hint), or None. Other
    pauses are flexible: as long as needed to fill `target`, between
    MIN_PAUSE_SECONDS and MAX_PAUSE_SECONDS; preferred[i] pauses are
    stretched first, the others only if that's not enough. Whatever doesn't fit stays
    silent at the end (and gets flagged); parts that are too long together
    simply run past `target` with minimal pauses (also flagged)."""
    count = len(durations)

    def base_gap(i: int) -> float:
        return fixed[i] if fixed[i] is not None else MIN_PAUSE_SECONDS

    # What has to fit from part i on, with minimal flexible pauses.
    after = [0.0] * (count + 1)
    for i in range(count - 1, -1, -1):
        after[i] = durations[i] + (base_gap(i + 1) if i + 1 < count else 0.0) + after[i + 1]

    preferred = preferred or [True] * count
    flexible = [i for i in range(1, count) if fixed[i] is None and offsets[i] is None]
    first = {i for i in flexible if preferred[i]}
    second = {i for i in flexible if not preferred[i]}
    room = MAX_PAUSE_SECONDS - MIN_PAUSE_SECONDS

    def layout(extra_first: float, extra_second: float) -> tuple[list[float], float]:
        starts = [0.0] * count
        end = durations[0]
        for i in range(1, count):
            extra = extra_first if i in first else extra_second if i in second else 0.0
            start = end + base_gap(i) + extra
            if fixed[i] is None and offsets[i] is not None:
                # Wait for the speech in the video, but never so long that
                # the rest can't fit any more.
                start = max(start, min(offsets[i], target - after[i]))
            starts[i] = start
            end = start + durations[i]
        return starts, end

    def stretch(fit) -> float:
        """Largest extra in [0, room] for which fit(extra) still ends by target."""
        if fit(room)[1] <= target:
            return room
        low, high = 0.0, room
        for _ in range(30):
            middle = (low + high) / 2
            if fit(middle)[1] <= target:
                low = middle
            else:
                high = middle
        return low

    starts, end = layout(0.0, 0.0)
    if end >= target or not flexible:
        return starts
    extra_first = stretch(lambda e: layout(e, 0.0)) if first else 0.0
    extra_second = stretch(lambda e: layout(extra_first, e)) if second else 0.0
    return layout(extra_first, extra_second)[0]


def _format_seconds(seconds: float) -> str:
    return f"{round(seconds, 1):g}"


# Pauses shorter than this sound like an ordinary sentence break, so they
# aren't written into the text (the text would fill up with ||0.4 marks).
SHOWN_PAUSE_SECONDS = 0.5


def text_with_markers(parts: list[Part], starts: list[float], durations: list[float]) -> str:
    """The parts joined back, with `||N` markers showing the real pauses
    (a typed marker is always kept, with its actual length)."""
    pieces = [parts[0].text]
    for i in range(1, len(parts)):
        gap = starts[i] - (starts[i - 1] + durations[i - 1])
        if gap >= SHOWN_PAUSE_SECONDS or parts[i].pause is not None:
            pieces.append(f"||{_format_seconds(gap)}")
        pieces.append(parts[i].text)
    return " ".join(pieces)
