#!/usr/bin/env python3
"""用 TTS 按逐字稿生成旁白，逐句放到成片时间码上，再和现有配乐混成带旁白的试听版。

    GEMINI_API_KEY=... python3 tools/tts_gemini.py [--voice Fola] [--model gemini-3.8-flash-tts] [--dry]
    ELEVENLABS_API_KEY=... python3 tools/tts_gemini.py --provider elevenlabs [--voice <voice_id>] [--model eleven_multilingual_v2]
    ELEVENLABS_API_KEY=... python3 tools/tts_gemini.py --provider elevenlabs --list-voices

- 读 逐字稿.md 的表格：开口时刻、须收住时刻、旁白。每句单独请求一次，存 assets/vo/line-NN.wav（24 kHz 单声道）。
- 句子超出窗口时用 atempo 最多加速到 1.12 倍；仍超出就照原长放，并在报告里列出，留给人工改稿。
- 输出 assets/vo/narration.wav（48 kHz，全片长度）、assets/master-vo.wav（配乐整体压低 + 旁白处侧链让位）、
  renders/final-vo.mp4（画面直接复用 renders/final.mp4）。key 只从环境变量读，不写进任何文件。
"""
import argparse
import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = "用冷静、确定的普通话朗读，像在陈述账目，不煽情，语速中等。LEDGER 读作英文单词 ledger。"


def sec(x):
    m, s = x.split(":")
    return int(m) * 60 + float(s)


def lines():
    out = []
    for ln in (ROOT / "逐字稿.md").read_text(encoding="utf-8").split("\n"):
        m = re.match(r"\| (\d+:\d+\.\d) \| (\d+:\d+\.\d) \| .+? \| (.+?) \| \d+ \| [\d.]+ \|$", ln)
        if m:
            out.append({"t0": sec(m.group(1)), "t1": sec(m.group(2)), "text": m.group(3)})
    return out


def tts(text, model, voice, key):
    body = {"contents": [{"role": "user", "parts": [{"text": f"{STYLE}\n## Transcript:\n{text}"}]}],
            "generationConfig": {"temperature": 1, "responseModalities": ["audio"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
    for attempt in range(5):
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=180).read())
            part = next(p for p in r["candidates"][0]["content"]["parts"] if "inlineData" in p)
            rate = int(re.search(r"rate=(\d+)", part["inlineData"]["mimeType"]).group(1))
            return base64.b64decode(part["inlineData"]["data"]), rate
        except urllib.error.HTTPError as e:
            msg = e.read().decode()
            if e.code == 429 and attempt < 4:
                time.sleep(20 * (attempt + 1))
                continue
            raise SystemExit(f"TTS 请求失败 HTTP {e.code}：{json.loads(msg)['error']['message'][:200]}")


def eleven(text, model, voice, key, prev="", nxt=""):
    """ElevenLabs：直接要 24 kHz 16-bit PCM；前后句一并传给模型，让语气连贯。"""
    body = {"text": text, "model_id": model, "previous_text": prev, "next_text": nxt,
            "voice_settings": {"stability": 0.55, "similarity_boost": 0.8, "style": 0.15, "use_speaker_boost": True}}
    if model.startswith(("eleven_flash", "eleven_turbo")):
        body["language_code"] = "zh"
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=pcm_24000",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "xi-api-key": key})
    for attempt in range(5):
        try:
            return urllib.request.urlopen(req, timeout=180).read(), 24000
        except urllib.error.HTTPError as e:
            msg = e.read().decode()
            if e.code == 429 and attempt < 4:
                time.sleep(15 * (attempt + 1))
                continue
            raise SystemExit(f"ElevenLabs 请求失败 HTTP {e.code}：{msg[:300]}")


def list_voices(key):
    req = urllib.request.Request("https://api.elevenlabs.io/v2/voices?page_size=100", headers={"xi-api-key": key})
    for v in json.loads(urllib.request.urlopen(req, timeout=60).read())["voices"]:
        lab = v.get("labels") or {}
        print(v["voice_id"], v["name"], lab.get("gender", ""), lab.get("accent", ""), lab.get("language", ""), lab.get("descriptive", lab.get("description", "")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "elevenlabs"], default="gemini")
    ap.add_argument("--voice", default=None, help="Gemini 音色名或 ElevenLabs voice_id")
    ap.add_argument("--model", default=None)
    ap.add_argument("--list-voices", action="store_true", help="列出 ElevenLabs 账户里可用的音色")
    ap.add_argument("--dry", action="store_true", help="只解析逐字稿，不请求")
    a = ap.parse_args()
    el = a.provider == "elevenlabs"
    a.model = a.model or ("eleven_multilingual_v2" if el else "gemini-3.8-flash-tts")
    a.voice = a.voice or ("JBFqnCBsd6RMkjVDRZzb" if el else "Fola")   # ElevenLabs 默认先用 George，正式版换中文母语音色
    if a.list_voices:
        return list_voices(os.environ["ELEVENLABS_API_KEY"])
    L = lines()
    plan = json.loads((ROOT / "plan.json").read_text())
    print(f"{len(L)} 句旁白")
    if a.dry:
        for x in L:
            print(f"{x['t0']:7.1f}–{x['t1']:7.1f}  {x['text']}")
        return
    env = "ELEVENLABS_API_KEY" if el else "GEMINI_API_KEY"
    key = os.environ.get(env)
    if not key:
        raise SystemExit("缺少 " + env)
    vo = ROOT / "assets" / "vo" / f"{a.provider}-{a.voice}"
    vo.mkdir(parents=True, exist_ok=True)
    report = []
    for i, x in enumerate(L, 1):
        raw = vo / f"line-{i:02d}.wav"
        if not raw.exists():
            pcm, rate = (eleven(x["text"], a.model, a.voice, key, L[i - 2]["text"] if i > 1 else "", L[i]["text"] if i < len(L) else "")
                         if el else tts(x["text"], a.model, a.voice, key))
            with wave.open(str(raw), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)
        # 去掉首尾静音，按窗口决定是否加速
        trim = vo / f"trim-{i:02d}.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af",
                        "silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse",
                        "-ar", "48000", str(trim)], check=True)
        d = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(trim)]))
        win = x["t1"] - x["t0"]
        speed = min(1.12, d / win) if d > win else 1.0
        fit = vo / f"fit-{i:02d}.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(trim), "-af", f"atempo={speed:.4f}", str(fit)], check=True)
        report.append({"line": i, "at": x["t0"], "window": round(win, 2), "duration": round(d, 2), "speed": round(speed, 3),
                       "overrun": round(max(0, d / speed - win), 2), "text": x["text"]})
        print(f"{i:02d} {x['t0']:6.1f}s 窗口 {win:4.1f}s 原长 {d:4.1f}s ×{speed:.2f}" + ("  ⚠ 超出" if d / speed > win + 0.05 else ""))
    # 拼成全片长度的旁白轨
    ins, fl = [], []
    for k, r in enumerate(report):
        ins += ["-i", str(vo / f"fit-{r['line']:02d}.wav")]
        fl.append(f"[{k}:a]adelay={round(r['at'] * 1000)}:all=1[v{k}]")
    fl.append("".join(f"[v{k}]" for k in range(len(report))) + f"amix=inputs={len(report)}:normalize=0,apad,atrim=duration={plan['duration']}[o]")
    narr = vo / "narration.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fl), "-map", "[o]", "-ar", "48000", "-ac", "1", "-t", str(plan["duration"]), str(narr)], check=True)
    # 配乐整体压低 7 dB，旁白出现时再侧链让位；旁白统一到 -16 LUFS 附近
    out = ROOT / "assets" / f"master-vo-{a.provider}.wav"
    graph = ("[1:a]loudnorm=I=-17:TP=-2,asplit=2[vo][key];[0:a]volume=-7dB[bed];"
             "[bed][key]sidechaincompress=threshold=0.02:ratio=6:attack=20:release=350[duck];"
             "[duck][vo]amix=inputs=2:normalize=0,alimiter=limit=0.84[m]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ROOT / "assets" / "master.wav"), "-i", str(narr), "-filter_complex", graph,
                    "-map", "[m]", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", str(out)], check=True)
    mp4 = ROOT / "renders" / f"final-vo-{a.provider}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ROOT / "renders" / "final.mp4"), "-i", str(out), "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-t", str(plan["duration"]), str(mp4)], check=True)
    (ROOT / "evidence" / f"vo-report-{a.provider}.json").write_text(json.dumps({"provider": a.provider, "model": a.model, "voice": a.voice, "style": None if el else STYLE, "lines": report},
                                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print("写出", narr, out, mp4)


if __name__ == "__main__":
    main()
