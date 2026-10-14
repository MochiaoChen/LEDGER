#!/usr/bin/env python3
"""ElevenLabs 旁白：选音色 → 试音 → 逐句多版本生成 → 语音转写自动校对 → 选最好的一版 → 对位混音。

key 只从环境变量 ELEVENLABS_API_KEY 读，不写进任何文件。

    python3 tools/vo_eleven.py voices                       # 从音色库挑普通话旁白音色，写 evidence/vo-voices.json
    python3 tools/vo_eleven.py audition --voices a,b,c      # 每个音色读同两段试音，出 renders/vo-audition/*.wav
    python3 tools/vo_eleven.py full --voice <voice_id> [--takes 3]
                                                            # 整篇逐句生成，转写校对选版，拼轨混音，出 renders/final-vo-elevenlabs.mp4

做法（依据 ElevenLabs 文档，2026-10）：
- 模型用 eleven_v4（官方推荐的最高质量模型，支持普通话；不支持 SSML、style、speed，只有 stability / similarity 两个设置）。
- 每句开头放一个英文的语气方向标签（v4 的 audio tags），并把前后句作为 previous_text / next_text 传入，保证语气连贯。
- 同一句生成多版（不同 seed），用 Scribe 语音转写回文字，与稿子逐字比对（字符错误率），再看时长是否放得进时间窗，
  自动选最好的一版；比对结果写 evidence/vo-takes.json，人只需要听最终版。
- 稿子里的 LEDGER 送进模型前写成 Ledger，避免被逐字母读。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.elevenlabs.io"
MODEL = "eleven_v4"
DIRECTION = ""   # 免费账户只能用自带音色；不加方向标签，省字符，也避免标签被读出来
AUDITION = ["这是一份 AI 写的研报，带单位的数字有六百五十个。哪一个，是模型编的？在 Ledger 里，答案必须是：零。",
            "抄下来的数，程序并不相信。这段代码会回到模型写的那一页，按数字边界逐字查找。找不到，拒收。"]


def key():
    k = os.environ.get("ELEVENLABS_API_KEY", "")
    if not k.startswith("sk_"):
        sys.exit("ELEVENLABS_API_KEY 需要以 sk_ 开头的 key（不是 key 的 ID）")
    return k


def call(method, path, body=None, raw=False, files=None, timeout=180):
    headers = {"xi-api-key": key()}
    data = None
    if files is not None:   # multipart，供语音转写上传音频
        b = uuid.uuid4().hex
        parts = []
        for k, v in (body or {}).items():
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for k, (name, blob) in files.items():
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + blob + b"\r\n")
        data = b"".join(parts) + f"--{b}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={b}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = r.read()
                return (out, dict(r.headers)) if raw else json.loads(out)
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")
            if e.code in (429, 500, 502, 503) and attempt < 5:
                time.sleep(8 * (attempt + 1))
                continue
            sys.exit(f"{method} {path} → HTTP {e.code}: {msg[:400]}")


def tts(text, voice, seed, prev="", nxt="", stability=0.5, similarity=0.75):
    body = {"text": text, "model_id": MODEL, "language_code": "zh", "seed": seed, "previous_text": prev, "next_text": nxt,
            "voice_settings": {"stability": stability, "similarity_boost": similarity}}
    pcm, headers = call("POST", f"/v1/text-to-speech/{voice}?output_format=pcm_24000", body, raw=True)
    return pcm, headers.get("request-id") or headers.get("Request-Id")


def save_wav(path, pcm, rate=24000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)


STT_CACHE = ROOT / "evidence" / "vo-stt-cache.json"


def transcribe(path):
    cache = json.loads(STT_CACHE.read_text()) if STT_CACHE.exists() else {}
    k = f"{path.name}:{path.stat().st_size}"
    if k in cache:
        return cache[k]
    cache[k] = _transcribe(path)
    STT_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    return cache[k]


def _transcribe(path):
    r = call("POST", "/v1/speech-to-text", {"model_id": "scribe_v1", "language_code": "zho", "tag_audio_events": "false"},
             files={"file": (path.name, path.read_bytes())})
    return r.get("text", "")


def norm(s):
    s = unicodedata.normalize("NFKC", s).lower().replace("ledger", "ledger")
    return re.sub(r"[\s\W_]+", "", s)


def cer(ref, hyp):
    a, b = norm(ref), norm(hyp)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1] / max(1, len(a))


def dur(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]))


def trim(src, dst):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af",
                    "silenceremove=start_periods=1:start_threshold=-48dB,areverse,silenceremove=start_periods=1:start_threshold=-48dB,areverse",
                    "-ar", "48000", str(dst)], check=True)


def script_lines():
    def sec(x):
        m, s = x.split(":"); return int(m) * 60 + float(s)
    out = []
    for ln in (ROOT / "逐字稿.md").read_text(encoding="utf-8").split("\n"):
        m = re.match(r"\| (\d+:\d+\.\d) \| (\d+:\d+\.\d) \| .+? \| (.+?) \| \d+ \| [\d.]+ \|$", ln)
        if m:
            out.append({"t0": sec(m.group(1)), "t1": sec(m.group(2)), "text": m.group(3).replace("LEDGER", "Ledger")})
    return out


# ------------------------------------------------------------------ 选音色
def cmd_voices(a):
    found = {}
    for uc in ["narrative_story", "informative_educational", "advertisement", None]:
        q = "language=zh&page_size=100&sort=usage_character_count_1y" + (f"&use_cases={uc}" if uc else "")
        for v in call("GET", f"/v1/shared-voices?{q}")["voices"]:
            found.setdefault(v["voice_id"], v)
    mine = call("GET", "/v2/voices?page_size=100")["voices"]
    rows = []
    for v in found.values():
        langs = {x.get("language") for x in v.get("verified_languages") or []}
        rows.append({k: v.get(k) for k in ("voice_id", "public_owner_id", "name", "gender", "age", "accent", "locale", "descriptive", "use_case",
                                           "usage_character_count_1y", "cloned_by_count", "free_users_allowed", "preview_url", "description")}
                    | {"zh_verified": "zh" in langs})
    rows.sort(key=lambda r: -(r["usage_character_count_1y"] or 0))
    (ROOT / "evidence" / "vo-voices.json").write_text(json.dumps({"library": rows, "mine": [{"voice_id": v["voice_id"], "name": v["name"], "category": v.get("category"),
                                                                    "labels": v.get("labels")} for v in mine]}, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in rows[:30]:
        print(f"{r['voice_id']}  {r['name'][:26]:26} {r['gender'] or '':7} {r['age'] or '':12} {r['descriptive'] or '':14} {r['use_case'] or '':24} "
              f"{(r['usage_character_count_1y'] or 0)/1e6:7.1f}M  zh✓={r['zh_verified']}")
    print(f"库里 {len(rows)} 个普通话音色；账户里已有 {len(mine)} 个音色")


def ensure_added(voice_id):
    """音色库里的音色要先加进账户才能用；已在账户里就直接返回。"""
    mine = {v["voice_id"] for v in call("GET", "/v2/voices?page_size=100")["voices"]}
    if voice_id in mine:
        return voice_id
    lib = json.loads((ROOT / "evidence" / "vo-voices.json").read_text())["library"]
    v = next((x for x in lib if x["voice_id"] == voice_id), None)
    if not v:
        sys.exit(f"{voice_id} 不在账户里，也不在 vo-voices.json 的候选里")
    r = call("POST", f"/v1/voices/add/{v['public_owner_id']}/{voice_id}", {"new_name": f"LEDGER-{v['name'][:20]}"})
    return r.get("voice_id", voice_id)


# ------------------------------------------------------------------ 试音
def cmd_audition(a):
    out = ROOT / "renders" / "vo-audition"
    clips = []
    for vid in a.voices.split(","):
        vid = ensure_added(vid.strip())
        for k, text in enumerate(AUDITION):
            p = out / f"{vid}-{k}.wav"
            if not p.exists():
                pcm, _ = tts(f"{DIRECTION} {text}", vid, seed=7 + k)
                save_wav(p, pcm)
            clips.append(p)
        print("试音", vid)
    # 每个音色两段接起来，中间留 0.8 秒，方便连着听
    lst = out / "list.txt"
    gap = out / "gap.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.8", str(gap)], check=True)
    lst.write_text("".join(f"file '{c.name}'\nfile 'gap.wav'\n" for c in clips))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-ar", "48000", str(out / "audition.wav")], check=True)
    print("写出", out / "audition.wav")


# ------------------------------------------------------------------ 整篇
def cmd_full(a):
    vid = ensure_added(a.voice)
    L = script_lines()
    plan = json.loads((ROOT / "plan.json").read_text())
    vo = ROOT / "assets" / "vo" / f"eleven-{vid}"
    vo.mkdir(parents=True, exist_ok=True)
    log = []
    for i, x in enumerate(L, 1):
        prev = L[i - 2]["text"] if i > 1 else ""
        nxt = L[i]["text"] if i < len(L) else ""
        win = x["t1"] - x["t0"]
        takes = []
        for t in range(a.takes):
            raw = vo / f"line-{i:02d}-take{t}.wav"
            if not raw.exists():
                pcm, rid = tts(f"{DIRECTION} {x['text']}".strip(), vid, seed=1000 * i + t, prev=prev, nxt=nxt, stability=a.stability)
                save_wav(raw, pcm)
            tr = vo / f"line-{i:02d}-take{t}-trim.wav"
            trim(raw, tr)
            hyp = transcribe(tr)
            d = dur(tr)
            spoken_tag = bool(DIRECTION) and bool(re.search(r"calm|confident|documentary|narration|measured", hyp, re.I))
            score = cer(x["text"], hyp) + (1.0 if spoken_tag else 0) + max(0, d / 1.08 - win) * 0.2
            takes.append({"take": t, "duration": round(d, 2), "cer": round(cer(x["text"], hyp), 3), "spoken_tag": spoken_tag, "hyp": hyp, "score": round(score, 3)})
        if min(z["cer"] for z in takes) > 0.25:
            for t in (10, 11):
                raw = vo / f"line-{i:02d}-take{t}.wav"
                if not raw.exists():
                    pcm, rid = tts(x["text"], vid, seed=1000 * i + t, stability=a.stability)
                    save_wav(raw, pcm)
                tr = vo / f"line-{i:02d}-take{t}-trim.wav"
                trim(raw, tr)
                hyp = transcribe(tr); d = dur(tr)
                takes.append({"take": t, "duration": round(d, 2), "cer": round(cer(x["text"], hyp), 3), "spoken_tag": False, "hyp": hyp, "context": False,
                              "score": round(cer(x["text"], hyp) + max(0, d / 1.08 - win) * 0.2, 3)})
        best = min(takes, key=lambda z: z["score"])
        src = vo / f"line-{i:02d}-take{best['take']}-trim.wav"
        best_i = takes.index(best)
        speed = min(1.08, best["duration"] / win) if best["duration"] > win else 1.0
        fit = vo / f"line-{i:02d}-fit.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", f"atempo={speed:.4f}", str(fit)], check=True)
        over = max(0, best["duration"] / speed - win)
        log.append({"line": i, "at": x["t0"], "window": round(win, 2), "text": x["text"], "best": best_i, "best_take": best["take"], "speed": round(speed, 3), "overrun": round(over, 2), "takes": takes})
        print(f"{i:02d} {x['t0']:6.1f}s 窗 {win:4.1f}s  选第 {best['take']} 版 {best['duration']:4.1f}s ×{speed:.2f} 错字率 {best['cer']:.2f}"
              + ("  ⚠ 超出 %.1fs" % over if over > 0.05 else "") + ("  ⚠ 读出了方向标签" if best["spoken_tag"] else ""))
    (ROOT / "evidence" / "vo-takes.json").write_text(json.dumps({"model": MODEL, "voice": vid, "direction": DIRECTION, "stability": a.stability, "lines": log},
                                                                ensure_ascii=False, indent=1), encoding="utf-8")
    # 拼轨：每句放在开口时刻
    ins, fl = [], []
    for k, r in enumerate(log):
        ins += ["-i", str(vo / f"line-{r['line']:02d}-fit.wav")]
        fl.append(f"[{k}:a]adelay={round(r['at'] * 1000)}:all=1[v{k}]")
    fl.append("".join(f"[v{k}]" for k in range(len(log))) + f"amix=inputs={len(log)}:normalize=0,apad,atrim=duration={plan['duration']}[o]")
    narr = vo / "narration.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fl), "-map", "[o]", "-ar", "48000", "-ac", "1",
                    "-t", str(plan["duration"]), str(narr)], check=True)
    # 混音：旁白轻压缩并做 EQ，配乐整体降 7 dB，旁白出现时侧链再让位；整体 -16 LUFS
    out = ROOT / "assets" / "master-vo-elevenlabs.wav"
    graph = ("[1:a]highpass=f=80,equalizer=f=3000:t=q:w=1.2:g=2,acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120,"
             "loudnorm=I=-17:TP=-2,asplit=2[vo][key];[0:a]volume=-7dB[bed];"
             "[bed][key]sidechaincompress=threshold=0.02:ratio=5:attack=25:release=400[duck];"
             "[duck][vo]amix=inputs=2:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=9[m]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ROOT / "assets" / "master.wav"), "-i", str(narr), "-filter_complex", graph,
                    "-map", "[m]", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", str(out)], check=True)
    mp4 = ROOT / "renders" / "final-vo-elevenlabs.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ROOT / "renders" / "final.mp4"), "-i", str(out), "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-t", str(plan["duration"]), str(mp4)], check=True)
    print("写出", narr, out, mp4)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("voices")
    p = sub.add_parser("audition"); p.add_argument("--voices", required=True)
    p = sub.add_parser("full"); p.add_argument("--voice", required=True); p.add_argument("--takes", type=int, default=3); p.add_argument("--stability", type=float, default=0.5)
    a = ap.parse_args()
    {"voices": cmd_voices, "audition": cmd_audition, "full": cmd_full}[a.cmd](a)


if __name__ == "__main__":
    main()
