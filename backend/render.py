"""FFmpeg/FFprobe wrappers — the only place in the app that actually
touches the video file.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Callable

from .editor import Timeline, build_timeline


class FFmpegNotFoundError(RuntimeError):
    pass


# Software x264 fallback: "veryfast" trades a small amount of quality for a
# large speed gain over "medium". Tune these if you want to trade speed for quality.
X264_PRESET = "veryfast"
X264_CRF = "20"
X264_ARGS = ["-c:v", "libx264", "-preset", X264_PRESET, "-crf", X264_CRF]

# GPU (NVENC) encoding is used whenever it works. The FFmpeg on PATH may be
# too new for the installed NVIDIA driver (FFmpeg 9 needs driver 610+, which
# Pascal cards like the GTX 1060 never get), so FFMPEG_RENDER_PATH can point
# at an older FFmpeg build used only for rendering.
FFMPEG_RENDER = os.environ.get("FFMPEG_RENDER_PATH", "ffmpeg")
NVENC_ARGS = [
    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "24", "-b:v", "0",
    "-pix_fmt", "yuv420p",
]

_nvenc_available: bool | None = None


def nvenc_available() -> bool:
    """Probes once whether FFMPEG_RENDER can actually open the NVENC encoder
    (it fails on missing GPUs and on driver/FFmpeg version mismatches)."""
    global _nvenc_available
    if _nvenc_available is None:
        command = [
            FFMPEG_RENDER, "-hide_banner",
            "-f", "lavfi", "-i", "color=size=256x256:duration=0.1",
            "-c:v", "h264_nvenc", "-f", "null", "-",
        ]
        try:
            _nvenc_available = subprocess.run(command, capture_output=True).returncode == 0
        except FileNotFoundError:
            _nvenc_available = False
    return _nvenc_available


def _run_encode(build_command: Callable[[str, list[str]], list[str]]) -> None:
    """Runs build_command(ffmpeg_binary, video_codec_args) with NVENC when
    available, retrying with software x264 if the NVENC attempt fails."""
    attempts = [("ffmpeg", X264_ARGS)]
    if nvenc_available():
        attempts.insert(0, (FFMPEG_RENDER, NVENC_ARGS))

    for index, (binary, codec_args) in enumerate(attempts):
        try:
            subprocess.run(build_command(binary, codec_args), check=True, capture_output=True, text=True)
            return
        except FileNotFoundError as exc:
            raise FFmpegNotFoundError(
                "ffmpeg was not found on PATH. Install FFmpeg and make sure it is on PATH."
            ) from exc
        except subprocess.CalledProcessError as exc:
            if index == len(attempts) - 1:
                raise RuntimeError(f"ffmpeg failed: {exc.stderr}") from exc


def get_duration(video_path: str) -> float:
    command = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        video_path,
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError(
            "ffprobe was not found on PATH. Install FFmpeg and make sure it is on PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffprobe failed: {exc.stderr}") from exc

    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def has_audio_stream(video_path: str) -> bool:
    command = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        video_path,
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError(
            "ffprobe was not found on PATH. Install FFmpeg and make sure it is on PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffprobe failed: {exc.stderr}") from exc

    return bool(result.stdout.strip())


def render_video(
    input_path: str,
    output_path: str,
    keep_segments: list[tuple[float, float]],
) -> None:
    if not keep_segments:
        raise ValueError("Nothing left to render — every segment was cut.")

    audio = has_audio_stream(input_path)
    audio_codec_args = ["-c:a", "aac", "-b:a", "192k"] if audio else ["-an"]

    if len(keep_segments) == 1:
        start, end = keep_segments[0]

        def build_command(ffmpeg: str, codec_args: list[str]) -> list[str]:
            return [
                ffmpeg, "-y",
                "-ss", str(start),
                "-to", str(end),
                "-i", input_path,
                *codec_args,
                *audio_codec_args,
                "-movflags", "+faststart",
                output_path,
            ]
    else:
        filter_parts = [_video_cut_filter(keep_segments, "outv")]
        if audio:
            filter_parts.append(_audio_cut_filter(keep_segments, "outa"))
        filter_complex = ";".join(filter_parts)
        audio_map = ["-map", "[outa]"] if audio else []

        def build_command(ffmpeg: str, codec_args: list[str]) -> list[str]:
            return [
                ffmpeg, "-y",
                *_source_input_args(input_path, keep_segments),
                "-filter_complex", filter_complex,
                "-map", "[outv]",
                *audio_map,
                *codec_args,
                *audio_codec_args,
                "-movflags", "+faststart",
                output_path,
            ]

    _run_encode(build_command)


_MIX_SAMPLE_RATE = 44100


def _video_cut_filter(keep_segments: list[tuple[float, float]], out_label: str) -> str:
    """Keeps only the frames inside keep_segments, in one pass over [0:v].

    Not one trim branch per segment + concat: ffmpeg copies every decoded
    frame into every trim branch, and a later segment's branch holds its
    frames in memory until concat gets to it. A 6-minute 1080p video keeping
    0-165s plus a tail at 354s needed >12 GB and was OOM-killed. Here
    `select` drops the cut frames as they're decoded, and `setpts` shifts
    each kept frame back by the total length cut before it. That's exact for
    variable frame rates too, and memory stays flat."""
    keep = "+".join(f"gte(t,{start:.6f})*lt(t,{end:.6f})" for start, end in keep_segments)

    shifts = []
    previous_end = 0.0
    for start, end in keep_segments:
        gap = start - previous_end
        if gap > 0:
            shifts.append(f"gte(T,{start:.6f})*{gap:.6f}")
        previous_end = end
    shift = "+".join(shifts) or "0"

    return f"[0:v]select='{keep}',setpts='PTS-({shift})/TB'[{out_label}]"


def _audio_cut_filter(keep_segments: list[tuple[float, float]], out_label: str, extra: str = "") -> str:
    """Sample-exact atrim + concat of [0:a]. The per-segment branches buffer
    like the video ones would, but audio is small (minutes of decoded audio
    are tens of MB), and atrim cuts on exact samples, which select can't."""
    parts = [
        f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]"
        for index, (start, end) in enumerate(keep_segments)
    ]
    labels = "".join(f"[a{index}]" for index in range(len(keep_segments)))
    tail = f",{extra}" if extra else ""
    parts.append(f"{labels}concat=n={len(keep_segments)}:v=0:a=1{tail}[{out_label}]")
    return ";".join(parts)


def get_frame_rate(video_path: str) -> str:
    """The video stream's frame rate as ffprobe reports it, e.g. "30/1"."""
    command = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "csv=p=0",
        video_path,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError(
            "ffprobe was not found on PATH. Install FFmpeg and make sure it is on PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffprobe failed: {exc.stderr}") from exc
    return result.stdout.strip() or "30/1"


def get_video_size(video_path: str) -> tuple[int, int]:
    command = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0:s=x",
        video_path,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError(
            "ffprobe was not found on PATH. Install FFmpeg and make sure it is on PATH."
        ) from exc
    width, height = result.stdout.strip().split("x")[:2]
    return int(width), int(height)


def _broll_overlays(
    timeline: Timeline,
    inserts: list[tuple[float, float]],
    insert_clips: list[list[tuple[str, float, float]]],
    size: tuple[int, int],
    frame_rate: str,
    first_input_index: int,
    base_label: str,
    out_label: str,
) -> tuple[list[str], list[str]]:
    """Lays each insert's picked clips (video only) over the still frame the
    timeline holds there, back to back from the insert's start. A clip is
    trimmed where the insert ends; if the clips run out early, the last
    clip's final frame is held until the insert ends.

    Each clip is its own seeked input (`-ss`/`-t` before `-i`), so ffmpeg
    only decodes the picked seconds, and `setpts` moves it to its output
    time; `overlay` passes the main video through until a clip's first frame
    arrives. Returns (extra input args, filter parts)."""
    width, height = size
    input_args: list[str] = []
    parts: list[str] = []
    current = base_label
    input_index = first_input_index
    count = 0

    for insert_start, (_, insert_duration), clips in zip(timeline.insert_starts, inserts, insert_clips):
        insert_end = insert_start + insert_duration
        cursor = insert_start
        placed = []
        for path, start, end in clips:
            length = min(end - start, insert_end - cursor)
            if length < 0.05:
                break
            placed.append((path, start, length, cursor))
            cursor += length

        for position, (path, start, length, at) in enumerate(placed):
            is_last = position == len(placed) - 1
            show_until = insert_end if is_last else at + length
            input_args += ["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", path]
            clip_label = f"broll{count}"
            next_label = f"vb{count}"
            parts.append(
                f"[{input_index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={frame_rate},"
                f"setpts=PTS-STARTPTS+{at:.6f}/TB[{clip_label}]"
            )
            parts.append(
                f"[{current}][{clip_label}]overlay=eof_action=repeat:"
                f"enable='between(t,{at:.6f},{show_until:.6f})'[{next_label}]"
            )
            current = next_label
            input_index += 1
            count += 1

    parts.append(f"[{current}]null[{out_label}]")
    return input_args, parts


def _video_timeline_filter(timeline: Timeline, frame_rate: str, out_label: str) -> str:
    """Like _video_cut_filter, but kept pieces are placed at their timeline
    output positions, leaving gaps where inserts go. `fps` fills each gap by
    repeating the frame before it (the first frame for a gap at the start),
    and `tpad` holds the last frame through a trailing gap — a still-frame
    placeholder until inserts get footage of their own."""
    keep = "+".join(f"gte(t,{start:.6f})*lt(t,{end:.6f})" for start, end, _ in timeline.pieces)

    # Shift for each piece is (source start - output start); it changes in
    # steps at each piece's source start.
    first_start, _, first_out = timeline.pieces[0]
    terms = [f"{first_start - first_out:.6f}"]
    previous_shift = first_start - first_out
    for start, _, out_start in timeline.pieces[1:]:
        shift = start - out_start
        terms.append(f"gte(T,{start:.6f})*({shift - previous_shift:.6f})")
        previous_shift = shift

    last_start, last_end, last_out = timeline.pieces[-1]
    trailing = max(0.0, timeline.total - (last_out + last_end - last_start))
    return (
        f"[0:v]select='{keep}',setpts='PTS-({'+'.join(terms)})/TB',"
        f"fps={frame_rate}:start_time=0,"
        f"tpad=stop_mode=clone:stop_duration={trailing + 1:.3f},"
        f"trim=duration={timeline.total:.6f}[{out_label}]"
    )


def _audio_timeline_filter(timeline: Timeline, out_label: str, aformat: str) -> str:
    """Original audio for the kept pieces with silence in every insert gap."""
    parts = []
    labels = ""
    cursor = 0.0
    for index, (start, end, out_start) in enumerate(timeline.pieces):
        gap = out_start - cursor
        if gap > 0.001:
            parts.append(f"anullsrc=channel_layout=stereo:sample_rate={_MIX_SAMPLE_RATE}:d={gap:.6f}[g{index}]")
            labels += f"[g{index}]"
        parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,{aformat}[a{index}]")
        labels += f"[a{index}]"
        cursor = out_start + (end - start)
    if timeline.total - cursor > 0.001:
        parts.append(f"anullsrc=channel_layout=stereo:sample_rate={_MIX_SAMPLE_RATE}:d={timeline.total - cursor:.6f}[gend]")
        labels += "[gend]"
    count = labels.count("[")
    parts.append(f"{labels}concat=n={count}:v=0:a=1[{out_label}]")
    return ";".join(parts)


def _source_input_args(input_path: str, keep_segments: list[tuple[float, float]]) -> list[str]:
    """`-i input`, limited to end just after the last kept segment, so
    ffmpeg doesn't decode a cut-off tail of the video for nothing.
    Input-side `-t` (with no `-ss`) keeps timestamps unchanged, so the
    select/atrim filters still line up."""
    last_end = max(end for _, end in keep_segments)
    return ["-t", f"{last_end + 0.5:.3f}", "-i", input_path]


def render_video_with_audio(
    input_path: str,
    output_path: str,
    keep_segments: list[tuple[float, float]],
    keep_original_audio: bool,
    voice_overlays: list[tuple[float, str]],
    music_path: str | None = None,
    music_db: float = -5.0,
    inserts: list[tuple[float, float]] | None = None,
    insert_clips: list[list[tuple[str, float, float]]] | None = None,
) -> None:
    """Same video cutting as render_video, but with a custom audio mix:
    the original audio track (optional), a looped background music bed
    (optional, attenuated by music_db), and per-chunk voice-over clips
    overlaid at their mapped position in the OUTPUT timeline (see
    editor.map_to_output_timeline / editor.output_time). The output audio
    always spans the full video duration — built on a silent bed so it isn't
    truncated to whichever optional source happens to be shortest.

    `inserts` — (anchor, duration) pairs for added parts (see
    editor.build_timeline): the video holds a still frame for `duration`
    seconds at each anchor, and the original audio is silent there.

    `insert_clips` — per insert (parallel to `inserts`), the (video path,
    start, end) clips picked to show during it instead of the still frame
    (see _broll_overlays). Their audio is never used.
    """

    if not keep_segments:
        raise ValueError("Nothing left to render — every segment was cut.")

    timeline = build_timeline(keep_segments, inserts) if inserts else None
    total_duration = timeline.total if timeline else sum(end - start for start, end in keep_segments)
    include_original_audio = keep_original_audio and has_audio_stream(input_path)

    inputs: list[str] = _source_input_args(input_path, keep_segments)
    next_input_index = 1

    music_input_index = None
    if music_path:
        inputs += ["-stream_loop", "-1", "-i", music_path]
        music_input_index = next_input_index
        next_input_index += 1

    voice_input_indices = []
    for _, path in voice_overlays:
        inputs += ["-i", path]
        voice_input_indices.append(next_input_index)
        next_input_index += 1

    filter_parts = []

    if timeline:
        frame_rate = get_frame_rate(input_path)
        if insert_clips and any(insert_clips):
            filter_parts.append(_video_timeline_filter(timeline, frame_rate, "basev"))
            broll_inputs, broll_parts = _broll_overlays(
                timeline, inserts, insert_clips, get_video_size(input_path), frame_rate,
                next_input_index, "basev", "outv",
            )
            inputs += broll_inputs
            next_input_index += broll_inputs.count("-i")
            filter_parts += broll_parts
        else:
            filter_parts.append(_video_timeline_filter(timeline, frame_rate, "outv"))
    else:
        filter_parts.append(_video_cut_filter(keep_segments, "outv"))

    # Audio: always start from a full-length silent bed so the output track
    # reliably spans the whole video regardless of which optional sources
    # are enabled, then mix in whichever sources are present.
    aformat = f"aformat=sample_rates={_MIX_SAMPLE_RATE}:channel_layouts=stereo"
    mix_labels = ["[silence]"]
    filter_parts.append(
        f"anullsrc=channel_layout=stereo:sample_rate={_MIX_SAMPLE_RATE}:d={total_duration}[silence]"
    )

    if include_original_audio:
        if timeline:
            filter_parts.append(_audio_timeline_filter(timeline, "origaudio", aformat))
        else:
            filter_parts.append(_audio_cut_filter(keep_segments, "origaudio", aformat))
        mix_labels.append("[origaudio]")

    if music_input_index is not None:
        filter_parts.append(
            f"[{music_input_index}:a]atrim=start=0:end={total_duration},"
            f"asetpts=PTS-STARTPTS,volume={music_db}dB,{aformat}[music]"
        )
        mix_labels.append("[music]")

    for (start_in_output, _path), input_index in zip(voice_overlays, voice_input_indices):
        delay_ms = max(0, round(start_in_output * 1000))
        label = f"voice{input_index}"
        filter_parts.append(f"[{input_index}:a]{aformat},adelay={delay_ms}|{delay_ms}[{label}]")
        mix_labels.append(f"[{label}]")

    filter_parts.append(
        # duration=first: the silent bed is exactly as long as the video, so a
        # voice-over or music running past the end can't extend the audio.
        f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=first:"
        f"dropout_transition=0:normalize=0[outa]"
    )

    filter_complex = ";".join(filter_parts)

    def build_command(ffmpeg: str, codec_args: list[str]) -> list[str]:
        return [
            ffmpeg, "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "[outa]",
            *codec_args,
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            output_path,
        ]

    _run_encode(build_command)
