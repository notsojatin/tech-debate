"""Outputs: transcript.md, evidence.json, judge.json, debate.srt, debate.wav and debate.mp3."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass

from app.config import Config
from app.state import DebateState, Phase
from app.tools.tts import SAMPLE_RATE, KokoroClient, Pronunciation, clean_for_speech, split_sentences

SIDE_LABEL = {"pro": "Pro", "con": "Con", "narrator": "Narrator"}
PHASE_HEADINGS = {
    Phase.OPENINGS: "Opening statements",
    Phase.REBUTTAL_1: "Rebuttals, round one",
    Phase.REBUTTAL_2: "Rebuttals, round two",
    Phase.CLOSINGS: "Closing lines",
}


def spoken_model(name: str) -> str:
    """'qwen3:4b' -> 'Qwen 3, 4 billion'; 'llama3.2:3b' -> 'Llama 3.2, 3 billion'."""
    base, _, tag = name.partition(":")
    base = re.sub(r"(?<=[a-zA-Z])(?=\d)", " ", base.split("/")[-1]).replace("-", " ").title()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)b", tag.lower())
    return f"{base}, {m.group(1)} billion" if m else base


@dataclass
class Segment:
    speaker: str  # pro | con | narrator
    text: str


def build_script(state: DebateState) -> list[Segment]:
    m = state.models
    segs = [Segment("narrator",
                    f"Tonight's motion: {state.topic.rstrip('.')}. Arguing for, {spoken_model(m['pro'])}. "
                    f"Arguing against, {spoken_model(m['con'])}. Judging, {spoken_model(m['judge'])}.")]
    for phase, heading in PHASE_HEADINGS.items():
        turns = state.turns_in(phase)
        if not turns:
            continue
        segs.append(Segment("narrator", heading + "."))
        segs.extend(Segment(t.side, t.text) for t in turns)
    if state.judge:
        segs.append(Segment("narrator", verdict_line(state.judge)))
    return segs


def verdict_line(j: dict) -> str:
    winner = {"pro": "the side arguing for", "con": "the side arguing against", "tie": "nobody: it's a tie"}
    line = (f"The verdict. Averaged over two judging passes with the speaking order swapped, "
            f"Pro scores {_num(j['totals']['pro'])} and Con scores {_num(j['totals']['con'])} out of 40. "
            f"The winner is {winner[j['winner']]}. {j['reason'].rstrip('.')}.")
    if not j.get("position_consistent", True):
        line += " One caveat: the judge picked a different winner when the order was swapped."
    return line


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"


# ---------------------------------------------------------------- audio + captions

def _ts(ms: int) -> str:
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def caption_text(text: str) -> str:
    return clean_for_speech(text, Pronunciation({}))


def render_audio(state: DebateState, cfg: Config, tts: KokoroClient, log=print) -> float:
    pron = Pronunciation()
    silence = lambda ms: b"\x00\x00" * int(SAMPLE_RATE * ms / 1000)  # noqa: E731
    voices = {"pro": cfg.voices.pro, "con": cfg.voices.con, "narrator": cfg.voices.narrator}
    pcm = bytearray()
    cues: list[tuple[int, int, str]] = []
    segs = build_script(state)
    for i, seg in enumerate(segs):
        if i:
            pcm += silence(cfg.render.speaker_gap_ms)
        sentences = split_sentences(caption_text(seg.text))
        log(f"  tts {i + 1}/{len(segs)} {seg.speaker}: {len(sentences)} sentences")
        for j, sentence in enumerate(sentences):
            if j:
                pcm += silence(cfg.render.sentence_gap_ms)
            spoken = clean_for_speech(sentence, pron)
            if not re.search(r"\w", spoken):
                continue
            start = len(pcm) // 2 * 1000 // SAMPLE_RATE
            pcm += tts.synth(spoken, voices[seg.speaker])
            end = len(pcm) // 2 * 1000 // SAMPLE_RATE
            cues.append((start, end, f"[{SIDE_LABEL[seg.speaker]}] {sentence}"))

    wav_path = state.run_dir / "debate.wav"
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(pcm))

    (state.run_dir / "debate.srt").write_text(
        "\n".join(f"{n}\n{_ts(a)} --> {_ts(b)}\n{text}\n" for n, (a, b, text) in enumerate(cues, 1)),
        encoding="utf-8",
    )
    encode_mp3(state, cfg, log)
    return len(pcm) / 2 / SAMPLE_RATE


def encode_mp3(state: DebateState, cfg: Config, log=print) -> None:
    if not shutil.which("ffmpeg"):
        log("  ! ffmpeg not found; leaving debate.wav only")
        return
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(state.run_dir / "debate.wav"),
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-codec:a", "libmp3lame",
         "-b:a", cfg.render.mp3_bitrate, str(state.run_dir / "debate.mp3")],
        check=True,
    )


# ---------------------------------------------------------------- text outputs

def write_json_outputs(state: DebateState) -> None:
    (state.run_dir / "evidence.json").write_text(
        json.dumps([e.model_dump() for e in state.ledger.items], indent=2, ensure_ascii=False), encoding="utf-8")
    if state.judge:
        (state.run_dir / "judge.json").write_text(
            json.dumps(state.judge, indent=2, ensure_ascii=False), encoding="utf-8")


def transcript_markdown(state: DebateState) -> str:
    m = state.models
    out = [
        f"# {state.topic}",
        "",
        f"- **Pro (for):** `{m['pro']}`",
        f"- **Con (against):** `{m['con']}`",
        f"- **Judge:** `{m['judge']}`",
        "",
    ]
    for phase, heading in PHASE_HEADINGS.items():
        turns = state.turns_in(phase)
        if not turns:
            continue
        out += [f"## {heading.replace(', round', ' — round')}", ""]
        for t in turns:
            out.append(f"**{SIDE_LABEL[t.side]}** (`{t.model}`)")
            out.append("")
            if t.quote:
                mark = "" if t.quote_matched else " *(quote not found verbatim)*"
                out.append(f"> Quoting opponent: “{t.quote}”{mark}")
                out.append("")
            refs = "".join(f"[^{c}]" for c in t.cites)
            out.append(f"{t.text} {refs}".rstrip())
            out.append("")
            for w in t.warnings:
                out.append(f"<sub>⚠ {w}</sub>  ")
            if t.warnings:
                out.append("")

    j = state.judge
    if j:
        out += ["## Verdict", "", f"**Winner: {j['winner'].upper()}** — {j['reason']}", ""]
        out += ["| Criterion | Pro | Con |", "|---|---|---|"]
        for k in j["average"]["pro"]:
            out.append(f"| {k.replace('_', ' ')} | {_num(j['average']['pro'][k])} | {_num(j['average']['con'][k])} |")
        out.append(f"| **total (of 40)** | **{_num(j['totals']['pro'])}** | **{_num(j['totals']['con'])}** |")
        out.append("")
        consistent = "yes" if j["position_consistent"] else "**no**, so the result is order-sensitive"
        out.append(f"Judged twice with the speaking order swapped. Same winner both times: {consistent}.")
        for r in j["runs"]:
            out.append(f"- {r['order']}: winner {r['winner']} — {r['reason']}")
        out.append("")

    if state.warnings:
        out += ["## Run warnings", ""] + [f"- {w}" for w in state.warnings] + [""]

    cited = list(dict.fromkeys(c for t in state.turns for c in t.cites))
    if cited:
        out += ["## Sources", ""]
        for c in cited:
            e = state.ledger.get(c)
            if e:
                out.append(f"[^{c}]: [{e.title or e.domain}]({e.url}) — {e.domain}")
        out.append("")
    return "\n".join(out)


def write_transcript(state: DebateState) -> None:
    (state.run_dir / "transcript.md").write_text(transcript_markdown(state), encoding="utf-8")
