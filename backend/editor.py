"""Deterministic cut normalization — turns potentially overlapping,
AI-proposed removal ranges into a clean, merged list of cuts, and converts
those cuts into the segments of the source video that should be kept.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Cut:
    start: float
    end: float
    text: str = ""
    reason: str = ""


def normalize_cuts(cuts: list[Cut], duration: float) -> list[Cut]:
    clipped: list[Cut] = []

    for cut in cuts:
        start = max(0.0, min(cut.start, duration))
        end = max(0.0, min(cut.end, duration))

        if end <= start:
            continue

        clipped.append(Cut(start=start, end=end, text=cut.text, reason=cut.reason))

    clipped.sort(key=lambda c: c.start)

    merged: list[Cut] = []

    for current in clipped:
        if not merged:
            merged.append(current)
            continue

        previous = merged[-1]

        if current.start <= previous.end:
            previous.end = max(previous.end, current.end)
            if current.reason and current.reason not in previous.reason:
                previous.reason = (
                    f"{previous.reason}; {current.reason}" if previous.reason else current.reason
                )
        else:
            merged.append(current)

    return merged


def calculate_keep_segments(cuts: list[Cut], duration: float) -> list[tuple[float, float]]:
    keep: list[tuple[float, float]] = []
    position = 0.0

    for cut in cuts:
        if cut.start > position:
            keep.append((position, cut.start))
        position = max(position, cut.end)

    if position < duration:
        keep.append((position, duration))

    return keep


def map_to_output_timeline(time: float, keep_segments: list[tuple[float, float]]) -> float:
    """Maps a point in the ORIGINAL (pre-cut) timeline to where it lands in
    the final rendered video, where kept segments are concatenated
    back-to-back with cut gaps closed.

    `time` is NOT guaranteed to fall inside a keep segment — a cue that
    starts inside a cut region but extends past the cut's end is correctly
    treated as "kept" elsewhere (it isn't fully contained in the cut, so its
    tail content would be lost if dropped), but its own start timestamp can
    land squarely inside the cut itself. There's no corresponding instant in
    the output for a point inside a cut, so such a point is mapped to
    wherever the output jumps to right after that cut — the start of the
    next kept segment — rather than falling through to a fallback that
    silently placed it at the very end of the video."""

    offset = 0.0
    for start, end in keep_segments:
        if time < start:
            return offset
        if time <= end:
            return offset + (time - start)
        offset += end - start

    # Past every kept segment entirely (e.g. a cue after a trailing cut with
    # nothing kept afterward) — only sane place left is the very end.
    return offset


# --- Inserted parts (new text added on top of the kept transcript) ---------
#
# An insert is (anchor, duration): `duration` seconds of new material placed
# at original-timeline time `anchor`, pushing everything from `anchor` on
# later in the output. Inserts must be sorted by anchor (stable for equal
# anchors — that's their playback order).

_ANCHOR_EPS = 0.001


@dataclass
class Timeline:
    # (source_start, source_end, output_start) for every kept piece, in order.
    pieces: list[tuple[float, float, float]]
    # Output start of each insert, parallel to the inserts list.
    insert_starts: list[float]
    total: float


def build_timeline(
    keep_segments: list[tuple[float, float]], inserts: list[tuple[float, float]]
) -> Timeline:
    """Splits kept segments at any insert anchor falling inside one, and
    works out where every kept piece and every insert lands in the output."""

    anchors = sorted({anchor for anchor, _ in inserts})
    pieces: list[tuple[float, float, float]] = []
    for start, end in keep_segments:
        inner = [a for a in anchors if start + _ANCHOR_EPS < a < end - _ANCHOR_EPS]
        bounds = [start, *inner, end]
        for piece_start, piece_end in zip(bounds, bounds[1:]):
            pieces.append((piece_start, piece_end, output_time(piece_start, keep_segments, inserts)))

    insert_starts = []
    inserted_so_far = 0.0
    for anchor, duration in inserts:
        insert_starts.append(map_to_output_timeline(anchor, keep_segments) + inserted_so_far)
        inserted_so_far += duration

    total = sum(end - start for start, end in keep_segments) + inserted_so_far
    return Timeline(pieces=pieces, insert_starts=insert_starts, total=total)


def output_time(
    time: float, keep_segments: list[tuple[float, float]], inserts: list[tuple[float, float]]
) -> float:
    """map_to_output_timeline, plus every insert placed at or before `time`
    (an insert anchored exactly at `time` plays before it)."""
    pushed = sum(duration for anchor, duration in inserts if anchor <= time + _ANCHOR_EPS)
    return map_to_output_timeline(time, keep_segments) + pushed
