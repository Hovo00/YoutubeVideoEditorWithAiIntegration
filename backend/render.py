"""FFmpeg/FFprobe wrappers — the only place in the app that actually
touches the video file.
"""

from __future__ import annotations

import json
import subprocess


class FFmpegNotFoundError(RuntimeError):
    pass


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
            "-preset", "medium",
            "-crf", "18",
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
            "-preset", "medium",
            "-crf", "18",
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
