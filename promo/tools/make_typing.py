#!/usr/bin/env python3
"""按画面键入时长生成连续的键入声（原创合成，固定种子）：assets/sfx/typing-<动作>.wav。

内置 typing.wav 只有 0.65 秒，盖不住 3～14 秒的连续键入；这里用带通噪声短脉冲按不规则间隔排出一段，音量很轻。
    uv run --with numpy --with scipy python tools/make_typing.py
"""
import json
import wave
from pathlib import Path

import numpy as np
from scipy import signal

ROOT = Path(__file__).resolve().parents[1]
SR = 48000
SPEC = json.loads((ROOT / "tools" / "typing-spec.json").read_text())   # {动作 id: [时长秒, 每秒键数]}
for k, (aid, (dur, rate)) in enumerate(sorted(SPEC.items())):
    rng = np.random.default_rng(7400 + k)
    n = int((dur + 0.15) * SR)
    out = np.zeros(n)
    t = 0.0
    while t < dur:
        m = int(0.03 * SR)
        tt = np.arange(m) / SR
        fc = rng.uniform(1800, 3600)
        click = signal.sosfilt(signal.butter(2, [fc, fc * 1.9], btype="band", fs=SR, output="sos"), rng.standard_normal(m)) * np.exp(-tt / 0.006)
        click += np.sin(2 * np.pi * rng.uniform(280, 420) * tt) * np.exp(-tt / 0.004) * 0.5
        i = int(t * SR)
        out[i:i + m] += click[: n - i] * rng.uniform(0.55, 1.0)
        t += rng.exponential(1 / rate) * 0.6 + 0.4 / rate
    out *= np.minimum(1, (dur + 0.15 - np.arange(n) / SR) / 0.25).clip(0, 1)
    out *= 10 ** (-13 / 20) / np.abs(out).max()
    with wave.open(str(ROOT / "assets" / "sfx" / f"typing-{aid}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((out * 32767).astype("<i2").tobytes())
    print(f"typing-{aid}.wav {dur}s")
