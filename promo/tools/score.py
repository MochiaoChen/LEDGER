#!/usr/bin/env python3
"""LEDGER 宣传片原创配乐（代码合成，固定随机种子，可复现）。

    uv run --with numpy --with scipy python tools/score.py            # 写出 assets/music.wav

D 小调 / F 大调，100 BPM，124 小节（297.6 秒），段落边界取自 plan.json 的镜头起止：
暗场（模型会话）用小调进行 Dm–Bb–F–C，配脉冲低音、琶音与鼓；纸面（账页）换成 F–C–Dm–Bb，只留键盘与铺底，
让“程序算过的账”听起来更稳、更亮。过闸门的时刻放冲击，读字和看代码的段落抽掉鼓。
没有外部采样；画面动作的点击、键入、提示音不在这里，由独立音效轨处理。
"""
import json
import wave
from pathlib import Path

import numpy as np
from scipy import signal

ROOT = Path(__file__).resolve().parents[1]
plan = json.loads((ROOT / "plan.json").read_text())
SR, BPM = 48000, plan["audio"]["beatGrid"]["bpm"]
BEAT, BAR = 60 / BPM, 240 / BPM
DUR = plan["duration"]
NB = round(DUR / BAR)
N = int(DUR * SR)
rng = np.random.default_rng(20261018)
SH = {s["id"]: (round(s["start"] / BAR), round(s["end"] / BAR)) for s in plan["shots"]}
ACT = {a["id"]: s["start"] + a["at"] for s in plan["shots"] for a in s["actions"]}


def bus():
    return np.zeros((N, 2))


def put(buf, t, sig, gain=1.0, pan=0.0):
    i = int(t * SR)
    if i >= N or i < 0:
        return
    sig = sig[: N - i]
    buf[i:i + len(sig), 0] += sig * gain * (1 - max(0, pan))
    buf[i:i + len(sig), 1] += sig * gain * (1 + min(0, pan))


def tt(d):
    return np.arange(int(d * SR)) / SR


def hz(m):
    return 440 * 2 ** ((m - 69) / 12)


def saw(f, t, ph=0.0):
    return 2 * ((t * f + ph) % 1) - 1


def lp(x, fc, order=2):
    return signal.sosfilt(signal.butter(order, fc, fs=SR, output="sos"), x, axis=0)


def hp(x, fc, order=2):
    return signal.sosfilt(signal.butter(order, fc, btype="high", fs=SR, output="sos"), x, axis=0)


# ---------------------------------------------------------------- 和声
DARK = [(50, [62, 65, 69, 72]), (46, [62, 65, 70, 74]), (41, [60, 65, 69, 72]), (48, [60, 64, 67, 72])]   # Dm Bb F C
LIGHT = [(41, [60, 65, 69, 72]), (48, [60, 64, 67, 72]), (50, [62, 65, 69, 72]), (46, [62, 65, 70, 74])]  # F C Dm Bb
TONE = ["dark"] * NB
for sid in ("brand", "truth", "compute", "check", "end"):
    for b in range(*SH[sid]):
        TONE[b] = "light"


def chord(b):
    first = next(s for s, e in SH.values() if s <= b < e)
    return (LIGHT if TONE[b] == "light" else DARK)[(b - first) % 4]


def bars(*ranges):
    """[(镜头 id 或 (起, 止) 小节, 强度)] → 每小节强度。镜头内可用相对小节 (id, 起, 止)。"""
    out = np.zeros(NB)
    for r, v in ranges:
        if isinstance(r, str):
            a, b = SH[r]
        elif isinstance(r[0], str):
            a, b = SH[r[0]][0] + r[1], SH[r[0]][0] + r[2]
        else:
            a, b = r
        out[int(a):int(b)] = v
    return out


def env_of(per_bar, smooth=0.12):
    """小节强度 → 逐采样包络（边界做短淡变，避免咔哒声）。"""
    e = np.repeat(per_bar, int(BAR * SR))[:N]
    e = np.pad(e, (0, N - len(e)), mode="edge")
    k = int(smooth * SR)
    return np.convolve(e, np.ones(k) / k, mode="same")[:, None]


# 各声部按镜头编排（数值是音量系数；0 表示这一段没有）
L_PAD = bars(("hook", .55), ("brand", .8), ("rule", .7), ("cmd", .7), ("search", .8), ("read", .75), ("code", .6), ("truth", .8), ("depth", .75), ("compute", .8),
             ("write", .75), ("review", .8), ("layout", .85), ("qc", .7), ("check", .75), ("trace", .85), ("end", .9))
L_BRIGHT = bars(("hook", 0), ("brand", .5), ("rule", .25), ("cmd", .4), ("search", .8), ("read", .3), ("code", .2), (("code", 5, 9), .55), ("truth", .5), ("depth", .4),
                ("compute", .75), ("write", .5), ("review", .45), ("layout", .9), ("qc", .2), ("check", .5), ("trace", .85), ("end", .6))
L_ARP = bars(("cmd", .5), ("search", .9), (("search", 6, 8), .35), ("read", .4), (("code", 5, 8), .7), (("code", 10, 12), .55), ("depth", .5), ("compute", .8), (("compute", 0, 1), .4),
             ("write", .55), ("review", .5), ("layout", .9), ("check", .35), ("trace", .9))
L_BASS = bars(("rule", .7), ("cmd", .8), ("search", .9), (("search", 6, 8), .5), ("code", .75), (("code", 8, 10), .9), (("depth", 2, 8), .65), ("compute", .85), ("write", .8), (("review", 3, 6), .6),
              ("layout", .9), (("qc", 5, 8), .5), ("check", .6), ("trace", .9))
L_KICK = bars((("rule", 1, 6), .7), ("cmd", .8), ("search", 1), (("search", 6, 8), 0), (("code", 5, 8), .9), (("code", 10, 12), .7), (("truth", 2, 7), .45), (("depth", 4, 8), .6), ("compute", .9),
              (("compute", 0, 1), 0), ("write", .8), (("review", 3, 6), .6), ("layout", 1), (("layout", 4, 6), 0), (("qc", 5, 8), .5), ("check", .55), ("trace", 1))
L_HAT = bars(("hook", .35), (("hook", 3, 6), 0), (("cmd", 2, 5), .6), ("search", .9), (("search", 6, 8), .4), (("read", 2, 7), .3), ("code", .5), ("depth", .4), ("compute", .8), (("compute", 0, 1), .3),
             ("write", .6), ("review", .45), ("layout", .9), (("layout", 4, 6), 0), (("qc", 4, 8), .35), ("check", .4), ("trace", .9))
L_CLAP = bars((("search", 2, 6), .8), (("search", 8, 11), .6), (("compute", 3, 8), .7), (("layout", 1, 4), .8), ("trace", .8))
L_KEYS = bars(("brand", .9), ("read", .45), ("truth", .9), ("depth", .4), (("compute", 0, 3), .5), ("review", .4), ("qc", .6), ("check", .8), ("end", 1))

# ---------------------------------------------------------------- 铺底（supersaw，暗 / 亮两路滤波后按段落交叉）
pad = bus()
for b in range(NB):
    root, notes = chord(b)
    d = BAR + 0.5
    t = tt(d)
    e = np.minimum(1, t / 0.5) * np.minimum(1, (d - t) / 0.55)
    for m in [root + 12] + notes[:3]:
        v = sum(saw(hz(m) * (1 + c / 1200), t, rng.random()) for c in (-11, -4, 0, 5, 12)) / 5
        put(pad, b * BAR - 0.02 if b else 0, v * e, 0.16, rng.uniform(-0.5, 0.5))
bright = env_of(L_BRIGHT, 0.6)
pad = (lp(pad, 700) * (1 - bright) * 1.5 + lp(pad, 3600) * bright * 1.25) * env_of(L_PAD, 0.5)

# ---------------------------------------------------------------- 琶音（十六分音符 pluck，附点八分延迟）
arp = bus()
PAT = [0, 2, 1, 3, 2, 1, 3, 2, 0, 2, 3, 1, 2, 3, 1, 2]
for b in range(NB):
    if L_ARP[b] <= 0:
        continue
    _, notes = chord(b)
    for k in range(16):
        m = notes[PAT[k]] + (12 if k % 8 in (3, 6) else 0)
        t = tt(0.26)
        v = (saw(hz(m), t) * 0.6 + np.sign(np.sin(2 * np.pi * hz(m) * t)) * 0.25) * np.exp(-t / 0.07)
        put(arp, b * BAR + k * BEAT / 4, v, 0.3 * (1.0 if k % 4 == 0 else 0.72), (-1) ** k * 0.35)
arp = (lp(arp, 900) * (1 - bright) * 1.3 + lp(arp, 5200) * bright) * env_of(L_ARP, 0.1)
dl = int(0.75 * BEAT * SR)
for _ in range(3):
    echo = np.zeros_like(arp)
    echo[dl:] = arp[:-dl][:, ::-1] * 0.36
    arp = arp + echo * 0.6 if _ == 0 else arp

# ---------------------------------------------------------------- 低音（八分音符脉冲）
bass = bus()
for b in range(NB):
    if L_BASS[b] <= 0:
        continue
    root, _ = chord(b)
    f = hz(root - 12)
    for k in range(8):
        t = tt(0.27)
        v = (np.sin(2 * np.pi * f * t) + 0.35 * saw(f, t)) * np.minimum(1, t / 0.006) * np.exp(-t / 0.12)
        put(bass, b * BAR + k * BEAT / 2, v, 0.25 * (1.0 if k % 2 == 0 else 0.7))
bass = lp(bass, 420) * env_of(L_BASS, 0.05)

# ---------------------------------------------------------------- 鼓
drums = bus()
kick_times = []
tk = tt(0.34)
KICK = np.sin(2 * np.pi * (46 * tk + (118 - 46) * 0.045 * (1 - np.exp(-tk / 0.045)))) * np.exp(-tk / 0.13) * np.minimum(1, tk / 0.002)
for b in range(NB):
    if L_KICK[b] > 0:
        for k in range(4):
            put(drums, b * BAR + k * BEAT, KICK, 0.5 * L_KICK[b])
            kick_times.append(b * BAR + k * BEAT)
    if L_HAT[b] > 0:
        for k in range(16):
            if L_HAT[b] < 0.5 and k % 2:
                continue
            th = tt(0.07 if k % 4 == 2 else 0.035)
            n = hp(rng.standard_normal(len(th)), 7500) * np.exp(-th / (0.022 if k % 4 == 2 else 0.011))
            put(drums, b * BAR + k * BEAT / 4, n, 0.1 * L_HAT[b] * (1.0 if k % 4 == 2 else 0.6), 0.25 if k % 2 else -0.25)
    if L_CLAP[b] > 0:
        for k in (1, 3):
            tc = tt(0.2)
            n = signal.sosfilt(signal.butter(2, [900, 3200], btype="band", fs=SR, output="sos"), rng.standard_normal(len(tc)))
            n *= sum(np.exp(-np.maximum(0, tc - o) / 0.05) * (tc >= o) for o in (0, 0.011, 0.023)) / 2
            put(drums, b * BAR + k * BEAT, n, 0.16 * L_CLAP[b])

# 侧链：底鼓落下时让铺底、低音、琶音让位
duck = np.ones(N)
for t0 in kick_times:
    i = int(t0 * SR)
    seg = min(N - i, int(0.3 * SR))
    duck[i:i + seg] = np.minimum(duck[i:i + seg], 1 - 0.45 * np.exp(-np.arange(seg) / (0.11 * SR)))
duck = duck[:, None]

# ---------------------------------------------------------------- 键盘（泛音衰减，纸面段落的动机）
keys = bus()
MOTIF = [(0, 2, 1.0), (1.5, 3, 0.7), (2, 1, 0.8), (3, 2, 0.6), (3.5, 0, 0.5)]   # (拍, 和弦音序号, 力度)
for b in range(NB):
    if L_KEYS[b] <= 0:
        continue
    root, notes = chord(b)
    line = MOTIF if b % 2 == 0 else [(0, 1, .9), (1, 2, .6), (2.5, 3, .8), (3, 1, .5)]
    for beat, idx, vel in line + [(0, -1, .8)]:
        m = root + 12 if idx < 0 else notes[idx] + 12
        t = tt(2.2)
        v = sum(np.sin(2 * np.pi * hz(m) * h * t) * a * np.exp(-t / d) for h, a, d in ((1, 1, .9), (2, .35, .5), (3, .12, .3), (4.02, .05, .18)))
        put(keys, b * BAR + beat * BEAT, v * np.minimum(1, t / 0.004), 0.11 * vel * L_KEYS[b], rng.uniform(-0.3, 0.3))

# ---------------------------------------------------------------- 上升音与冲击：落在闸门、问题、落版这些镜头里的关键动作上
fx = bus()


def riser(t_end, d=2.4, g=0.14):
    t = tt(d)
    n = rng.standard_normal(len(t))
    out = np.zeros(len(t))
    step = int(0.05 * SR)
    for i in range(0, len(t), step):   # 分段带通，中心频率随时间上升
        u = i / len(t)
        sos = signal.butter(2, [400 + 5000 * u ** 2, 900 + 9000 * u ** 2], btype="band", fs=SR, output="sos")
        out[i:i + step] = signal.sosfilt(sos, n[i:i + step])
    put(fx, t_end - d, out * (t / d) ** 2, g)


def impact(t0, g=0.5, major=None):
    t = tt(1.8)
    v = np.sin(2 * np.pi * (38 * t + 30 * 0.08 * (1 - np.exp(-t / 0.08)))) * np.exp(-t / 0.5)
    n = lp(rng.standard_normal(len(t)), 1800) * np.exp(-t / 0.16) * 0.35
    put(fx, t0, (v + n) * np.minimum(1, t / 0.003), g)
    if major is not None:   # 通过时叠一个明亮的和弦
        for m in major:
            tc = tt(2.4)
            put(fx, t0, sum(saw(hz(m) * (1 + c / 1200), tc) for c in (-7, 0, 7)) / 3 * np.exp(-tc / 0.7) * np.minimum(1, tc / 0.01), 0.07, rng.uniform(-.4, .4))


F_MAJ, D_MIN = [65, 69, 72, 77], [62, 65, 69, 74]
riser(ACT["hook-question"], 2.4, 0.16); impact(ACT["hook-question"], 0.5)
impact(ACT["hook-zero"], 0.55, F_MAJ)
impact(ACT["brand-seal"], 0.4)
riser(SH["search"][0] * BAR, 2.4, 0.12); impact(SH["search"][0] * BAR, 0.4)
impact(ACT["gate-1"], 0.5, F_MAJ)
riser(ACT["code-hit"], 1.8, 0.1); impact(ACT["code-hit"], 0.4, F_MAJ)
impact(ACT["code-reject"], 0.55)
impact(ACT["gate-2"], 0.42, F_MAJ)
riser(ACT["gate-7"], 2.4, 0.12); impact(ACT["gate-7"], 0.5, F_MAJ)
impact(ACT["gate-8"], 0.42, D_MIN)
impact(ACT["gate-9"], 0.42, D_MIN)
riser(ACT["gate-11"], 3.6, 0.17); impact(ACT["gate-10"], 0.3); impact(ACT["gate-11"], 0.65, F_MAJ)
impact(ACT["qc-total"], 0.45, F_MAJ)
riser(SH["end"][0] * BAR, 2.4, 0.12); impact(ACT["end-mark"], 0.5, F_MAJ); impact(ACT["end-seal"], 0.5)

# ---------------------------------------------------------------- 混响、合并、母带
wet_in = pad * 0.5 + arp * 0.55 + keys * 0.9 + fx * 0.35
ir_t = tt(2.4)
ir = np.stack([lp(rng.standard_normal(len(ir_t)), 5200) * np.exp(-ir_t / 0.55) for _ in range(2)], axis=1)
ir /= np.sqrt((ir ** 2).sum(axis=0))
wet = np.stack([signal.fftconvolve(wet_in[:, c], ir[:, c])[:N] for c in range(2)], axis=1)
mix = (pad + arp * 0.9 + bass) * duck + drums + keys + fx + wet * 0.2
mix = hp(mix, 28)
# 片尾：最后一个和弦自然衰减，末 1.6 秒收干净
tail = np.ones(N)
k = int(1.6 * SR)
tail[-k:] = np.linspace(1, 0, k) ** 1.6
head = np.minimum(1, np.arange(N) / (0.02 * SR))
mix *= (tail * head)[:, None]
mix = np.tanh(mix * 1.15) / np.tanh(1.15)
mix *= 10 ** (-3 / 20) / np.abs(mix).max()
out = ROOT / "assets" / "music.wav"
out.parent.mkdir(exist_ok=True)
with wave.open(str(out), "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((mix * 32767).astype("<i2").tobytes())
rms = [float(20 * np.log10(np.sqrt((mix[int(s * BAR * SR):int(e * BAR * SR)] ** 2).mean()) + 1e-9)) for s, e in SH.values()]
print(f"写出 {out}：{DUR}s，{NB} 小节，{BPM} BPM")
print("各镜头 RMS(dBFS)：", {k: round(v, 1) for k, v in zip(SH, rms)})
