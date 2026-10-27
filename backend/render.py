"""FFmpeg/FFprobe wrappers — the only place in the app that actually
touches the video file.
"""

from __future__ import annotations

import json
import subprocess


class FFmpegNotFoundError(RuntimeError):
    pass


# Software x264 is CPU-bound on this machine (no usable hardware encoder);
# "veryfast" trades a small amount of quality for a large speed gain over
# "medium". Tune these if you want to trade speed for quality.
X264_PRESET = "veryfast"
X264_CRF = "20"


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
        command = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-to", str(end),
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", X264_PRESET,
            "-crf", X264_CRF,
            *audio_codec_args,
            "-movflags", "+faststart",
            output_path,
        ]
    else:
        filter_parts = []
        video_inputs = ""
        audio_inputs = ""

        for index, (start, end) in enumerate(keep_segments):
            filter_parts.append(
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{index}]"
            )
            video_inputs += f"[v{index}]"

            if audio:
                filter_parts.append(
                    f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]"
                )
                audio_inputs += f"[a{index}]"

        if audio:
            concat_inputs = "".join(
                f"[v{i}][a{i}]" for i in range(len(keep_segments))
            )
            concat_tail = f"concat=n={len(keep_segments)}:v=1:a=1[outv][outa]"
        else:
            concat_inputs = video_inputs
            concat_tail = f"concat=n={len(keep_segments)}:v=1:a=0[outv]"

        filter_complex = ";".join(filter_parts) + ";" + concat_inputs + concat_tail

        command = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
        ]
        if audio:
            command += ["-map", "[outa]"]
        command += [
            "-c:v", "libx264",
            "-preset", X264_PRESET,
            "-crf", X264_CRF,
            *audio_codec_args,
            "-movflags", "+faststart",
            output_path,
        ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError(
            "ffmpeg was not found on PATH. Install FFmpeg and make sure it is on PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg failed: {exc.stderr}") from exc


_MIX_SAMPLE_RATE = 44100


def render_video_with_audio(
    input_path: str,
    output_path: str,
    keep_segments: list[tuple[float, float]],
    keep_original_audio: bool,
    voice_overlays: list[tuple[float, str]],
    music_path: str | None = None,
    music_db: float = -5.0,
) -> None:
    """Same video cutting as render_video, but with a custom audio mix:
    the original audio track (optional), a looped background music bed
    (optional, attenuated by music_db), and per-chunk voice-over clips
    overlaid at their mapped position in the OUTPUT timeline (see
    editor.map_to_output_timeline). The output audio always spans the full
    video duration — built on a silent bed so it isn't truncated to
    whichever optional source happens to be shortest.
    """

    if not keep_segments:
        raise ValueError("Nothing left to render — every segment was cut.")

    total_duration = sum(end - start for start, end in keep_segments)
    include_original_audio = keep_original_audio and has_audio_stream(input_path)

    inputs: list[str] = ["-i", input_path]
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

    # Video: trim + concat each kept segment (same as render_video).
    video_labels = ""
    for index, (start, end) in enumerate(keep_segments):
        filter_parts.append(
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{index}]"
        )
        video_labels += f"[v{index}]"
    filter_parts.append(f"{video_labels}concat=n={len(keep_segments)}:v=1:a=0[outv]")

    # Audio: always start from a full-length silent bed so the output track
    # reliably spans the whole video regardless of which optional sources
    # are enabled, then mix in whichever sources are present.
    aformat = f"aformat=sample_rates={_MIX_SAMPLE_RATE}:channel_layouts=stereo"
    mix_labels = ["[silence]"]
    filter_parts.append(
        f"anullsrc=channel_layout=stereo:sample_rate={_MIX_SAMPLE_RATE}:d={total_duration}[silence]"
    )

    if include_original_audio:
        audio_labels = ""
        for index, (start, end) in enumerate(keep_segments):
            filter_parts.append(
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]"
            )
            audio_labels += f"[a{index}]"
        filter_parts.append(
            f"{audio_labels}concat=n={len(keep_segments)}:v=0:a=1,{aformat}[origaudio]"
        )
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
        f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=longest:"
        f"dropout_transition=0:normalize=0[outa]"
    )

    filter_complex = ";".join(filter_parts)

    command = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", X264_PRESET,
        "-crf", X264_CRF,
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError(
            "ffmpeg was not found on PATH. Install FFmpeg and make sure it is on PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg failed: {exc.stderr}") from exc
