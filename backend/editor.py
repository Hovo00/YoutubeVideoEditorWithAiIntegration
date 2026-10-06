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
