"""Mix the film's soundtrack: voice-over (timeline.json) + Lyria score (music.opus) + synthesized sound effects.

    python video/audio/mix.py OUT.wav

Every sound effect is synthesized here (no samples), timed to the same moments as film.js.
Needs numpy, scipy, soundfile and ffmpeg.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

HERE = Path(__file__).resolve().parent
VIDEO = HERE.parent
SR = 48000
TL = json.loads((VIDEO / "timeline.json").read_text())
DUR = TL["duration"]
N = int(DUR * SR)
rng = np.random.default_rng(7)


def load(path: Path) -> np.ndarray:
    """Any audio file → float32 stereo at SR (via ffmpeg)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()


def place(track: np.ndarray, clip: np.ndarray, at: float, gain_db: float = 0.0, pan: float = 0.0) -> None:
    if clip.ndim == 1:
        clip = np.stack([clip * np.sqrt(0.5 * (1 - pan)), clip * np.sqrt(0.5 * (1 + pan))], axis=1) * np.sqrt(2)
    i = int(at * SR)
    j = min(len(track), i + len(clip))
    if j > i:
        track[i:j] += clip[: j - i] * 10 ** (gain_db / 20)


def env(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / SR
    return np.minimum(1, t / max(attack, 1e-4)) * np.exp(-np.maximum(0, t - attack) / decay)


def bandpass(x: np.ndarray, lo: float, hi: float, order: int = 2) -> np.ndarray:
    sos = signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    return signal.sosfilt(sos, x)


def lowpass(x: np.ndarray, f: float, order: int = 2) -> np.ndarray:
    return signal.sosfilt(signal.butter(order, f, btype="low", fs=SR, output="sos"), x)


# ---------------------------------------------------------------- effects
def kettle_click() -> np.ndarray:
    n = int(0.25 * SR)
    out = np.zeros(n)
    for k, (at, g) in enumerate([(0.0, 1.0), (0.011, 0.6)]):
        i = int(at * SR)
        m = n - i
        noise = bandpass(rng.standard_normal(m), 1800, 7000) * env(m, 0.0004, 0.006) * g
        thunk = np.sin(2 * np.pi * (190 - 60 * k) * np.arange(m) / SR) * env(m, 0.001, 0.03) * 0.5 * g
        out[i:] += noise + thunk
    return out / np.abs(out).max() * 0.6


def kettle_heat(dur: float) -> np.ndarray:
    """The element starting up: a low rumble and a hiss that grow, with a few early bubbles."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    grow = np.minimum(1, t / (dur * 0.6)) ** 1.5 * np.minimum(1, (dur - t) / 1.5)
    rumble = lowpass(rng.standard_normal(n), 220, 4) * 1.2
    hiss = bandpass(rng.standard_normal(n), 2500, 9000) * 0.25
    out = (rumble + hiss) * grow
    for _ in range(40):
        at = rng.uniform(0.6, dur - 0.3)
        m = int(0.03 * SR)
        f = rng.uniform(400, 1100)
        b = np.sin(2 * np.pi * f * np.arange(m) / SR * (1 + np.arange(m) / m * 0.4)) * env(m, 0.002, 0.008)
        i = int(at * SR)
        out[i:i + m] += b * 0.25 * grow[i]
    return out / np.abs(out).max() * 0.35


def buzz(dur: float = 0.34) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 168 + 4 * np.sin(2 * np.pi * 9 * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    tone = np.tanh(2.2 * np.sin(ph)) + 0.25 * np.sin(2 * ph)
    rattle = bandpass(rng.standard_normal(n), 900, 3000) * 0.12
    e = np.minimum(1, t / 0.02) * np.minimum(1, (dur - t) / 0.04)
    return lowpass((tone + rattle) * e, 2400) * 0.5


def ring(dur: float = 1.6) -> np.ndarray:
    """A soft landline ring heard across a kitchen (440 + 480 Hz with a 20 Hz warble)."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    tone = (np.sin(2 * np.pi * 440 * t) + np.sin(2 * np.pi * 480 * t)) * (0.6 + 0.4 * np.sin(2 * np.pi * 20 * t))
    e = np.minimum(1, t / 0.03) * np.minimum(1, (dur - t) / 0.06)
    return lowpass(tone * e, 1800) * 0.16


def tap() -> np.ndarray:
    n = int(0.06 * SR)
    t = np.arange(n) / SR
    return (np.sin(2 * np.pi * 1500 * t) * 0.5 + bandpass(rng.standard_normal(n), 2000, 6000) * 0.4) * env(n, 0.0005, 0.008) * 0.35


def chime(f0: float, dur: float = 3.0) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for ratio, amp, dec in [(1, 1.0, 1.3), (2.0, 0.35, 0.8), (3.01, 0.18, 0.5), (4.2, 0.08, 0.3)]:
        out += amp * np.sin(2 * np.pi * f0 * ratio * t) * np.exp(-t / dec)
    return out * np.minimum(1, t / 0.004) * 0.18


def whoosh(dur: float = 1.6, lo: float = 300, hi: float = 2400) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = rng.standard_normal(n)
    out = np.zeros(n)
    hop = 1024
    for i in range(0, n, hop):
        u = i / n
        fc = lo * (hi / lo) ** np.sin(np.pi * u * 0.5)
        seg = x[max(0, i - 4096): i + hop]
        y = bandpass(seg, fc * 0.7, min(fc * 1.4, SR / 2 - 100))
        out[i: i + hop] = y[-len(out[i: i + hop]):]
    e = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
    return out * e * 0.22


def wind(dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    base = bandpass(rng.standard_normal(n), 250, 1400)
    gust = 0.55 + 0.45 * np.sin(2 * np.pi * 0.11 * t) * np.sin(2 * np.pi * 0.047 * t + 1)
    e = np.minimum(1, t / 3) * np.minimum(1, (dur - t) / 3)
    return base * gust * e * 0.12


# ---------------------------------------------------------------- the mix
def vo_time(vid: str, word: str) -> float:
    v = next(x for x in TL["vo"] if x["id"] == vid)
    w = next(x for x in v["words"] if x[0].lower().strip(".,").startswith(word))
    return v["at"] + w[1]


def main(out: str) -> None:
    vo = np.zeros((N, 2), np.float32)
    for v in TL["vo"]:
        place(vo, load(VIDEO / v["file"]), v["at"])
    # a touch of room on the voice: short early reflections, very low
    room = np.zeros_like(vo)
    for d, g in [(0.013, 0.12), (0.029, 0.08), (0.047, 0.05)]:
        k = int(d * SR)
        room[k:] += vo[:-k] * g
    vo = vo + room

    music = load(HERE / "music.opus")[:N]
    music = np.pad(music, ((0, N - len(music)), (0, 0)))
    # score automation (dB), shaped to the film rather than to the generator
    keys = [(0, 3), (12, 3), (14, -4), (21.5, -4), (23, -9), (40.5, -9), (42, -5), (52, -6), (62, -6), (63.5, -2), (81, -2),
            (92, -3), (94.4, 1), (100, 1), (103, -1), (111, -1), (133, -3), (146, -3), (148, 0), (160, 0), (164.5, -2), (167.6, -60)]
    tk, gk = zip(*keys)
    tt = np.arange(N) / SR
    gain = 10 ** (np.interp(tt, tk, gk) / 20)
    # duck under the voice
    talk = (np.abs(vo).max(axis=1) > 0.01).astype(np.float32)
    talk = np.convolve(talk, np.ones(int(0.25 * SR)) / int(0.25 * SR), mode="same")
    talk = signal.sosfilt(signal.butter(1, 3, fs=SR, output="sos"), talk)
    duck = 10 ** (-5.5 * np.clip(talk * 1.5, 0, 1) / 20)
    music = music * (gain * duck)[:, None]

    fx = np.zeros((N, 2), np.float32)
    place(fx, kettle_click(), 0.48, -4)                          # the switch light comes on
    place(fx, kettle_click(), 94.40, -2)                         # and then... the kettle
    place(fx, kettle_heat(6.5), 94.5, -9)
    for at in (68.4, 71.0, 73.3):                                # Margaret's landline, unanswered
        place(fx, ring(1.5), at, -6, pan=-0.35)
    for at in (84.35, 84.75, 125.0, 125.4):                      # Priya's phone
        place(fx, buzz(), at, -4, pan=0.35)
    bz = vo_time("19", "every")                                  # every phone in Alberta
    for k in range(70):
        place(fx, buzz(0.28), bz + 0.05 + rng.uniform(0, 1.1), -24 + rng.uniform(-4, 3), pan=rng.uniform(-0.9, 0.9))
    place(fx, tap(), 88.0, -6, pan=0.35)
    place(fx, tap(), vo_time("17", "tap") - 0.05, -6, pan=-0.1)
    place(fx, chime(784, 3.0), 95.95, -14, pan=0.35)             # "Margaret's kettle just came on"
    place(fx, chime(659, 3.5), vo_time("17", "warm") - 0.1, -12) # the kitchen glows
    for at, dur in [(21.4, 1.6), (41.0, 1.8), (62.0, 2.0), (146.6, 1.8)]:
        place(fx, whoosh(dur), at, -8)
    place(fx, whoosh(2.6, 200, 1400), 110.4, -6)
    place(fx, wind(22.5), 110.8, -8)

    mix = vo * 1.0 + music * 0.9 + fx
    # fade in/out to match the picture
    fade = np.clip(tt / 0.8, 0, 1) * np.clip((DUR - 0.2 - tt) / 1.4, 0, 1)
    mix *= fade[:, None]
    tmp = Path(out).with_suffix(".pre.wav")
    sf.write(tmp, mix, SR, subtype="FLOAT")
    # broadcast-ish loudness for the web
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", str(SR), out], check=True)
    tmp.unlink()
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1])
