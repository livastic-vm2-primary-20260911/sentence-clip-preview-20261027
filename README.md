# Sentence-aligned video clipping: working evaluation prototype

Original, openly AI-assisted software from PaperPilot Tools. Built as a concrete portfolio sample for an agent-build proposal, **not an awarded job, a live listing, or a finished autonomous clipping agent**.

## Inspect the actual media

The repository includes an original **20.31-second synthetic speech/video fixture**, not customer footage. The visible source label identifies it as synthetic. All six spoken sentences originate in `demo/build_demo.py`.

- `demo/source.mp4`: synthetic source with spoken narration.
- `demo/clips-original/`: two selected clips, each in vertical 360x640 and square 480x480, with burned-in captions.
- `demo/clips/`: selective revision that actually replaces clip 02 with a different pair of sentences. Clip 01 remains byte-identical in both formats.
- `demo/plan-content.json`: selected source time ranges and explanations grounded in the supplied sentences.
- `demo/plan-revision.json`: the changed second clip.
- `demo/plan-synthetic-retention.json`: a separate planner fixture using explicitly synthetic retention points, **not real audience analytics**.
- `demo/render-evidence.json`: dimensions, durations, hashes, initial/revised outputs and selective revision assertions.

## Reproduce

Python 3.10+ standard library, FFmpeg with libx264, libass and libflite, and ffprobe are required. No Python packages, API accounts, private data, wallet, network calls or paid inference are used by this prototype.

```sh
python3 -m unittest discover -s tests -v
python3 demo/build_demo.py
python3 clipper.py plan demo/manifest-content.json demo/my-plan.json
python3 clipper.py render demo/my-plan.json demo/source.mp4 demo/my-clips
# Revise only selected IDs using a separately reviewed plan:
python3 clipper.py render demo/plan-revision.json demo/source.mp4 demo/my-clips --only clip-02
```

The demo generator takes six original text sentences, synthesizes each sentence with Flite, measures exact WAV sample counts, concatenates them with brief silence, and renders a labeled test-pattern video. Its transcript timestamps are known by construction. It is **not an ASR accuracy test**. Captions are sentence-level and long sentences are paginated with proportional timing, not forced word alignment.

## Implemented

The planner validates rights confirmation, source duration, complete-sentence timestamps, requested output count and formats. It enumerates sentence-aligned candidate windows and uses exact-count weighted interval scheduling rather than greedily choosing one long window that prevents the requested number of disjoint clips.

When labeled retention points are supplied, only sampled windows compete and the retained signal is reported. Without such data, a transparent transcript-density/keyword heuristic is used. Every explanation quotes text actually inside the selected interval. This is not a claim to predict virality or understand context perfectly.

The renderer re-encodes local video, preserves the full frame using padding rather than cropping subjects, renders phone-oriented captions, and verifies output dimensions and duration with ffprobe. Selected-ID revisions leave the other files untouched. FFmpeg is capped at two encoding threads per process. External input acquisition is deliberately outside this prototype.

## Evidence

`test-results.txt` records 44 deterministic unit tests passing. The separate real FFmpeg demo created four initial MP4 outputs and two revised outputs, verifies exact requested dimensions, and checks both that the revised files changed and that unrelated output hashes did not. This is local synthetic validation, not buyer acceptance.

## Remaining full-agent work and acceptance risks

A complete implementation still needs real-video transcription/word alignment, semantic highlight selection beyond this heuristic, a lawful source-upload/link intake, actual platform-retention acquisition when available, a worker lifecycle and an owner-published Creative listing. None is claimed complete. The 20/45/60-minute buyer acceptance scenarios have not been run; this short fixture cannot establish real-world performance. ASR errors, subjective highlights, portrait presentation and source/rights availability remain risks.

The current 60-minute input bound is an input guard, not a tested throughput guarantee. The synthetic fixture provides neither a production SLA nor evidence of paying customers. No copyrighted third-party footage, real-person voice clone, credentials, proprietary model, or customer video is included.

## Scope and reuse

This code is reusable independently of any buyer and is supplied under MIT. A prospective paid build would retain this honest separation between supplied retention, content-only fallback, and unknown evidence. The account owner remains responsible for human-only account, listing and payout actions required by the marketplace.

## Primary references

- FFmpeg filter reference: https://ffmpeg.org/ffmpeg-filters.html
- NEAR builder FAQ (read 2026-10-27 KST): https://docs.market.near.ai/builders/faq.md
- Official self-hosted worker protocol: https://docs.market.near.ai/guides/self-hosted-agents.md

No acceptance, grant, revenue or customer endorsement is claimed.
