#!/usr/bin/env python3
"""Sentence-aligned clip planning and FFmpeg rendering; no network or wallet use."""
from __future__ import annotations
import argparse
from bisect import bisect_right
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import textwrap
from typing import Any

FORMATS = {"vertical": (360, 640), "square": (480, 480), "landscape": (640, 360)}

class ClipError(ValueError):
    """Invalid input or incomplete output, never silent partial success."""

def number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ClipError(f"{name} must be a finite number")
    return float(value)

@dataclass(frozen=True)
class Sentence:
    start: float
    end: float
    text: str

@dataclass(frozen=True)
class Window:
    first: int
    last: int
    start: float
    end: float
    score: float
    excerpt: str
    mode: str
    retention_peak: float | None

def validate(data: dict) -> tuple[list[Sentence], list[dict]]:
    if not isinstance(data, dict): raise ClipError("Manifest must be an object")
    if data.get("rights_confirmed") is not True:
        raise ClipError("Rights to process the source must be confirmed")
    duration = number(data.get("duration"), "duration")
    if not 0 < duration <= 3600:
        raise ClipError("Preview supports sources up to 60 minutes")
    n = data.get("clip_count")
    if type(n) is not int or not 1 <= n <= 12:
        raise ClipError("clip_count must be an integer from 1 to 12")
    formats = data.get("formats")
    if not isinstance(formats, list) or not formats or any(not isinstance(f, str) or f not in FORMATS for f in formats) or len(formats) != len(set(formats)):
        raise ClipError("Request unique supported formats: vertical, square, landscape")
    lo = number(data.get("min_seconds", 15), "min_seconds")
    hi = number(data.get("max_seconds", 60), "max_seconds")
    if not 0 < lo <= hi <= 90:
        raise ClipError("Require 0 < min_seconds <= max_seconds <= 90")
    if type(data.get("captions", True)) is not bool:
        raise ClipError("captions must be boolean")
    rows = data.get("sentences")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 2000:
        raise ClipError("Supply 1 to 2000 timestamped complete sentences")
    sentences = []
    previous_end = 0.0
    for row in rows:
        if not isinstance(row, dict): raise ClipError("Each sentence must be an object")
        start, end = number(row.get("start"), "start"), number(row.get("end"), "end")
        text = row.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            raise ClipError("Sentence text must contain 1 to 1000 characters")
        text = " ".join(text.split())
        if text[-1] not in ".!?。！？":
            raise ClipError("Only complete, punctuated sentences can be selected")
        if not 0 <= start < end <= duration or start < previous_end - 1e-6:
            raise ClipError("Sentence times must be sorted, non-overlapping and inside the video")
        previous_end = end
        sentences.append(Sentence(start, end, text))
    retention = data.get("retention", [])
    if not isinstance(retention, list) or len(retention) > 10000:
        raise ClipError("retention must be a bounded list")
    if retention and not isinstance(data.get("retention_source"), str):
        raise ClipError("Retention points require an explicit source label")
    if retention and not data["retention_source"].strip():
        raise ClipError("Retention source label must not be blank")
    previous_t = -1.0
    for point in retention:
        if not isinstance(point, dict): raise ClipError("Each retention point must be an object")
        t, value = number(point.get("time"), "retention time"), number(point.get("value"), "retention value")
        if not 0 <= t < duration or not 0 <= value <= 1 or t <= previous_t:
            raise ClipError("Retention points require increasing times and values from zero to one")
        previous_t = t
    return sentences, retention

def candidates(data: dict, sentences: list[Sentence], retention: list[dict]) -> list[Window]:
    low, high = float(data.get("min_seconds", 15)), float(data.get("max_seconds", 60))
    points_t = [p["time"] for p in retention]
    out = []
    keywords = ("because", "result", "fix", "question", "important", "example", "without")
    for i, first in enumerate(sentences):
        for j in range(i, len(sentences)):
            end = sentences[j].end
            length = end - first.start
            if length > high + 1e-6: break
            if length + 1e-6 < low: continue
            text = " ".join(s.text for s in sentences[i:j+1])
            density = min(len(text.split()) / max(length, 1), 4.0)
            rhetorical = sum(word in text.lower() for word in keywords)
            score = density + 0.3 * rhetorical
            peak = None
            if retention:
                a, b = bisect_right(points_t, first.start - 1e-9), bisect_right(points_t, end - 1e-9)
                if a == b: continue  # Do not claim retention support for an unsampled window.
                peak = max(p["value"] for p in retention[a:b])
                score += 10 * peak
            excerpt = max(sentences[i:j+1], key=lambda s: sum(w in s.text.lower() for w in keywords)).text
            out.append(Window(i, j, first.start, end, score, excerpt,
                              "retention" if retention else "transcript-content-heuristic", peak))
            if len(out) > 100000: raise ClipError("Candidate budget exceeded")
    return out

def choose(windows: list[Window], count: int) -> list[Window]:
    """Exact-count weighted interval scheduling; avoids greedy under-filling."""
    windows = sorted(windows, key=lambda w: (w.end, w.start, w.first))
    ends = [w.end for w in windows]
    prev = [bisect_right(ends, w.start + 1e-9, 0, i) for i, w in enumerate(windows)]
    m = len(windows)
    scores = [[-math.inf] * (m + 1) for _ in range(count + 1)]
    take = [[False] * (m + 1) for _ in range(count + 1)]
    scores[0] = [0.0] * (m + 1)
    for k in range(1, count + 1):
        for i in range(1, m + 1):
            skip = scores[k][i-1]
            yes = scores[k-1][prev[i-1]] + windows[i-1].score
            if yes > skip:
                scores[k][i], take[k][i] = yes, True
            else:
                scores[k][i] = skip
    if scores[count][m] == -math.inf:
        raise ClipError(f"Cannot produce {count} non-overlapping complete-sentence clips within the requested limits")
    picked = []
    k, i = count, m
    while k:
        if take[k][i]:
            picked.append(windows[i-1]); i = prev[i-1]; k -= 1
        else: i -= 1
    return sorted(picked, key=lambda w: w.start)

def plan(data: dict) -> dict:
    sentences, retention = validate(data)
    selected = choose(candidates(data, sentences, retention), data["clip_count"])
    clips = []
    for i, w in enumerate(selected, 1):
        reason = (f"Source-labeled retention peak {w.retention_peak:.3f}; contains: {w.excerpt}"
                  if retention else f"No retention supplied. Transparent transcript heuristic selected this complete idea: {w.excerpt}")
        clips.append({"id": f"clip-{i:02d}", "start": w.start, "end": w.end,
                      "selection_mode": w.mode, "reason": reason,
                      "retention_peak": w.retention_peak,
                      "sentences": [asdict(s) for s in sentences[w.first:w.last+1]]})
    return {"schema": "sentence-clip-preview/1", "duration": data["duration"],
            "synthetic": data.get("synthetic", False), "formats": data["formats"],
            "captions": data.get("captions", True),
            "retention_source": data.get("retention_source") if retention else None,
            "limitations": ["Needs trustworthy complete-sentence timestamps; ASR and YouTube acquisition are not implemented.",
                            "Heuristic content ranking is not a learned semantic or virality model.",
                            "Preserves the full frame by padding; no face tracking or smart cropping.",
                            "Real video accuracy and unseen 60-minute acceptance scenarios are not yet validated."],
            "clips": clips}

def timestamp(seconds: float) -> str:
    ms = int(round(max(seconds, 0) * 1000))
    h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def srt(clip: dict) -> str:
    cues = []
    for sentence in clip["sentences"]:
        # Render plain text, not user-supplied subtitle markup.
        text = sentence["text"].replace("<", "(").replace(">", ")").replace("{", "(").replace("}", ")")
        pages = textwrap.wrap(text, width=58) or [text]
        width = (sentence["end"] - sentence["start"]) / len(pages)
        for i, page in enumerate(pages):
            start = sentence["start"] - clip["start"] + width * i
            end = sentence["start"] - clip["start"] + width * (i + 1)
            cues.append(f"{len(cues)+1}\n{timestamp(start)} --> {timestamp(end)}\n" + "\n".join(textwrap.wrap(page, width=30)))
    return "\n\n".join(cues) + "\n"

def probe(path: Path) -> dict:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path.resolve())], capture_output=True, text=True, timeout=30, check=True)
        return json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ClipError("ffprobe could not inspect the local media file") from exc

def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""): h.update(chunk)
    return h.hexdigest()

def render(document: dict, source: Path, directory: Path, only: list[str] | None = None) -> dict:
    if document.get("schema") != "sentence-clip-preview/1": raise ClipError("Unknown plan schema")
    if not source.is_file() or source.stat().st_size > 1024**3: raise ClipError("Expected a local source up to 1 GiB")
    meta = probe(source)
    if not any(x.get("codec_type") == "video" for x in meta["streams"]): raise ClipError("Source has no video")
    actual_duration = number(float(meta["format"]["duration"]), "source duration")
    if abs(actual_duration - document["duration"]) > 0.25: raise ClipError("Source duration does not match the reviewed plan")
    ids = [c["id"] for c in document["clips"]]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"clip-\d{2}", i) for i in ids): raise ClipError("Invalid clip IDs")
    if only and any(i not in ids for i in only): raise ClipError("Unknown selective revision ID")
    formats = document["formats"]
    if not formats or any(f not in FORMATS for f in formats): raise ClipError("Unsupported output format")
    directory.mkdir(parents=True, exist_ok=True)
    receipt = {"synthetic": document.get("synthetic", False), "source_sha256": file_hash(source), "rendered": [], "preserved": []}
    for clip in document["clips"]:
        start, end = number(clip["start"], "start"), number(clip["end"], "end")
        if not 0 <= start < end <= actual_duration + 0.05: raise ClipError("Clip outside the source")
        for fmt in formats:
            target = directory / f"{clip['id']}-{fmt}.mp4"
            if only and clip["id"] not in only:
                if target.exists(): receipt["preserved"].append({"file": target.name, "sha256": file_hash(target)})
                continue
            width, height = FORMATS[fmt]
            vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24"
            if document.get("captions"):
                subtitle = directory / f"{clip['id']}.srt"
                subtitle.write_text(srt(clip), encoding="utf-8")
                vf += f",subtitles={subtitle.name}:force_style='FontSize=22,MarginV=24,Outline=2'"
            temporary = target.with_suffix(".part.mp4")
            args = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-threads", "2", "-filter_threads", "1", "-ss", str(start), "-i", str(source.resolve()), "-t", str(end-start), "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "25", "-threads", "2", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", temporary.name]
            try:
                subprocess.run(args, cwd=directory, check=True, capture_output=True, timeout=180)
                output = probe(temporary)
                video = next(s for s in output["streams"] if s["codec_type"] == "video")
                seconds = float(output["format"]["duration"])
                if (video["width"], video["height"]) != (width, height) or abs(seconds-(end-start)) > 0.2:
                    raise ClipError("Rendered dimensions or duration failed verification")
                temporary.replace(target)
                receipt["rendered"].append({"file": target.name, "width": width, "height": height,
                                            "duration": seconds, "sha256": file_hash(target), "reason": clip["reason"]})
            except (subprocess.SubprocessError, OSError) as exc:
                raise ClipError(f"Rendering failed for {target.name}; existing final output was not overwritten") from exc
            finally:
                temporary.unlink(missing_ok=True)
    return receipt

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    a = sub.add_parser("plan"); a.add_argument("manifest", type=Path); a.add_argument("output", type=Path)
    b = sub.add_parser("render"); b.add_argument("plan", type=Path); b.add_argument("source", type=Path); b.add_argument("directory", type=Path); b.add_argument("--only", nargs="+")
    args = parser.parse_args()
    try:
        if args.action == "plan":
            result = plan(json.loads(args.manifest.read_text(encoding="utf-8")))
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
        else:
            result = render(json.loads(args.plan.read_text(encoding="utf-8")), args.source, args.directory, args.only)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ClipError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")

if __name__ == "__main__":
    main()
