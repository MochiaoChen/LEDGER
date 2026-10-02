"""Fresh-context editorial review of a DeepSeek report against verified run artifacts.

The review is an additional adversarial screen, not proof that every inference is true.
It cannot be authored through model write_file; only this fixed procedure writes review.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .core.config import get_settings
from .core.llm import LLMClient


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_review(raw: Any, narrative_hash: str, run_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("narrative_sha256") != narrative_hash or raw.get("run_id") != run_id:
        raise ValueError("审读记录与当前文稿或估值运行不一致")
    issues = raw.get("issues")
    if not isinstance(issues, list) or len(issues) > 30:
        raise ValueError("审读记录 issues 格式错误")
    for issue in issues:
        if not isinstance(issue, dict) or issue.get("severity") not in {"blocker", "warning"}:
            raise ValueError("审读问题缺 severity")
        if not all(isinstance(issue.get(k), str) and issue[k].strip() for k in ("excerpt", "reason", "fix")):
            raise ValueError("审读问题须包含摘录、原因与修正建议")
    escalate_material_issues(issues)
    if raw.get("pass") is not (not any(x["severity"] == "blocker" for x in issues)):
        raise ValueError("审读 pass 与 blocker 不一致")
    return raw


def escalate_material_issues(issues: list[dict[str, Any]]) -> None:
    """Fail closed when the reviewer understates a factual or caliber defect."""
    material_terms = ("无法核实", "无依据", "不一致", "不平衡", "未披露", "未得到支撑", "与已核验事实", "口径", "预案", "数字错误", "差异", "相差", "未实施", "误导", "交叉验证结论实际并不成立", "确定性", "因果", "歧义", "内部术语")
    for issue in issues:
        if isinstance(issue, dict) and any(term in str(issue.get("reason", "")) for term in material_terms):
            issue["severity"] = "blocker"


def review(ws: Path, run: Path, narrative: Path, *, model: str = "deepseek-flash") -> dict[str, Any]:
    if model != "deepseek-flash":
        raise ValueError("审读固定使用 deepseek-flash，以便测评可比")
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise ValueError("缺 DeepSeek API Key，无法做独立审读")
    text = narrative.read_text(encoding="utf-8")
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    analysis = _read(run / "financials/analysis.json")
    extras = _read(run / "financials/extras.json")
    forecast = _read(run / "valuation/forecast_summary.json")
    valuation = _read(run / "valuation/valuation.json")
    assumptions = _read(ws / "data/extractions" / _read(ws / "sample.json")["key"] / "valuation_assumptions.json")
    bridge_path = run / "valuation/non_operating_assets.json"
    evidence = {
        "historical_facts": analysis.get("truth_table", []),
        "quarterly": analysis.get("quarterly", {}),
        "verified_business_tables": extras.get("tables", []),
        "forecast_summary": forecast,
        "analyst_assumptions": assumptions,
        "non_operating_assets_bridge": _read(bridge_path) if bridge_path.is_file() else {},
        "valuation": {"scenarios": valuation.get("scenarios"), "value_range": valuation.get("value_range"),
                      "sensitivities": valuation.get("sensitivities")},
    }
    system = (
        "你是独立审读者，不是研报作者。只返回 JSON 对象，字段 issues 数组。每项含 severity(blocker/warning)、"
        "excerpt(原文短摘)、reason、fix。严格用提供的已核验事实和预测产物对照，不猜来源。"
        "出现以下情形列 blocker：核心结论没有两到三环关键数字支撑；把不同口径分母或收入/销量直接推成份额；"
        "历史事实与预测混淆；无依据的因果、确定性断言或估值下限；估值数字与产物不符；把内部流程、年报佐证、"
        "投资收益和公允价值变动收益从 EBIT 剔除却遗漏对应的非经营性资产股权桥处理，或无解释地删去原有已核验资产；"
        "自我解释写给投资者；冗余否定句式、明显口语化；预测图表未标历史/预测。"
        "无法核实且重要的论断也列 blocker，并建议删去或移至待核清单；不重要的不确定论断建议删去。"
        "警告 warning 只用于不影响事实、口径、结论的轻微文字问题；预案写成已实施、数字桥加总不平、"
        "交叉验证不成立、行情日期或价格称谓误导，均必须列 blocker。"
        "如果证据中没有相关材料，不能武断认定事实错误，应明确证据不足。不要为了凑问题凭空指控。"
        "最多 20 项，优先重大问题。"
    )
    payload = json.dumps({"narrative": text, "evidence": evidence}, ensure_ascii=False)
    client = LLMClient(get_settings(llm_base_url="https://api.deepseek.com", llm_model=model,
                                    llm_api_key=key, llm_mode="live",
                                    cache_dir=str(ws / ".pipeline/review_cache"), llm_timeout=180))
    raw = client.chat_json(system, payload, purpose=f"independent-review:{run.name}")
    if not isinstance(raw, dict) or not isinstance(raw.get("issues"), list):
        raise ValueError("审读模型未返回规定 JSON")
    issues = raw["issues"]
    # Same-model reviewers sometimes label a material unsupported assertion as a warning.
    # Fail closed on evidence/caliber failures regardless of that subjective label.
    escalate_material_issues(issues)
    result = {"narrative_sha256": sha, "run_id": run.name, "model": model,
              "request_sha256": client.last_call.get("request_sha256"), "usage": client.last_call.get("usage"),
              "issues": issues, "pass": not any(isinstance(x, dict) and x.get("severity") == "blocker" for x in issues)}
    validate_review(result, sha, run.name)
    path = narrative.parent / "review.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def apply_replacements(text: str, replacements: Any) -> str:
    """Atomic, unique-substring prose patch; reject markup and broad rewrites."""
    if not isinstance(replacements, list) or not 1 <= len(replacements) <= 12:
        raise ValueError("局部修订须包含 1–12 处替换")
    result = text
    for item in replacements:
        if not isinstance(item, dict) or set(item) != {"old", "new"}:
            raise ValueError("每处替换只允许 old/new")
        old, new = item["old"], item["new"]
        if not isinstance(old, str) or not isinstance(new, str) or not old or len(old) > 1500 or len(new) > 2000:
            raise ValueError("局部修订的原句或新句长度无效")
        if "<!--" in old or "<!--" in new or "<script" in new.lower():
            raise ValueError("不能修改章节标记或加入 HTML")
        if result.count(old) != 1:
            raise ValueError("修订原句须在当前文稿中恰好出现一次")
        result = result.replace(old, new, 1)
    return result


def untouched_citations(blockers: list[dict[str, Any]], before: str, after: str) -> list[str]:
    """Exact cited phrases present before and after a proposed repair."""
    return [x["excerpt"] for x in blockers if x["excerpt"] in before and x["excerpt"] in after]


def revise(ws: Path, run: Path, narrative: Path, *, model: str = "deepseek-flash") -> dict[str, Any]:
    """Use a fresh, narrow DeepSeek call to patch only current review blockers."""
    if model != "deepseek-flash":
        raise ValueError("局部修订固定使用 deepseek-flash")
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise ValueError("缺 DeepSeek API Key")
    text = narrative.read_text(encoding="utf-8")
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    previous = validate_review(_read(narrative.parent / "review.json"), sha, run.name)
    blockers = [x for x in previous["issues"] if x["severity"] == "blocker"]
    if not blockers:
        raise ValueError("当前审读没有 blocker，无需局部修订")
    client = LLMClient(get_settings(llm_base_url="https://api.deepseek.com", llm_model=model,
                                    llm_api_key=key, llm_mode="live",
                                    cache_dir=str(ws / ".pipeline/review_cache"), llm_timeout=180))
    system = ("你只做投资研报原文的局部修订，返回 JSON 对象 {\"replacements\":[{\"old\":\"...\",\"new\":\"...\"}]}。"
              "每个 old 必须是正文中原样存在且只出现一次的连续短句；逐条修复本轮全部 blocker，不重写其他段落。"
              "审读指出摘要时必须改摘要本身，改正文相似句不算；指出重复口径提醒时删去重复位置，只在一处保留简短说明。"
              "财务归因桥若没有完整可加总的正负分项，就不要在摘要只罗列正向贡献；直接写核实的净增额，注明完整桥在正文。"
              "收入与销量增速差只能表述为单位收入变化，不可直接断言为主动降价、让利或份额变化。"
              "不新增未核验数字，不把不同口径数据推为份额变化，不写内部流程解释，直接写给投资研究读者。"
              "没有足够证据的确定性结论删除或改为有前提的判断。不要修改章节标记。最多 12 处替换。")
    feedback = ""
    for attempt in range(3):
        raw = client.chat_json(system + feedback,
                               json.dumps({"blockers": blockers, "narrative": text}, ensure_ascii=False),
                               purpose=f"targeted-revision:{run.name}:{attempt + 1}")
        if not isinstance(raw, dict):
            raise ValueError("修订模型未返回 JSON 对象")
        new_text = apply_replacements(text, raw.get("replacements"))
        # A replacement elsewhere is not a fix for the cited sentence. Several
        # real reviews previously repeated the exact same blocker for this reason.
        untouched = untouched_citations(blockers, text, new_text)
        if new_text != text and not untouched:
            narrative.write_text(new_text, encoding="utf-8")
            return {"replacements": len(raw["replacements"]),
                    "narrative_sha256": hashlib.sha256(new_text.encode("utf-8")).hexdigest(),
                    "request_sha256": client.last_call.get("request_sha256"), "usage": client.last_call.get("usage")}
        feedback = " 上一稿仍保留以下被点名的原句；这次必须直接删除或改写这些原句：" + "；".join(untouched[:8])
    raise ValueError("三次局部修订后仍保留已指明的 blocker 原句")


def review_until_clear(ws: Path, run: Path, narrative: Path, *, max_reviews: int = 5) -> dict[str, Any]:
    """Bounded review/fix cycle. A failed numeric guard stops; it never waives a blocker."""
    if not 1 <= max_reviews <= 5:
        raise ValueError("最多五轮独立审读")
    history = []
    prior: dict[str, Any] | None = None
    path = narrative.parent / "review.json"
    if path.is_file():
        try:
            text_hash = hashlib.sha256(narrative.read_bytes()).hexdigest()
            prior = validate_review(_read(path), text_hash, run.name)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            prior = None
    for index in range(max_reviews):
        env = {k: v for k, v in os.environ.items() if k != "DEEPSEEK_API_KEY"}
        guard = subprocess.run([sys.executable, "-m", "finagent", "guard", "--run-dir", str(run),
                                "--text", str(narrative)], cwd=ws, env=env, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
        if guard.returncode:
            return {"pass": False, "rounds": len(history), "reason": "数字护栏未通过",
                    "guard": (guard.stdout + guard.stderr)[-3000:], "history": history}
        finding = prior if prior is not None else review(ws, run, narrative)
        prior = None
        blockers = [x for x in finding["issues"] if x["severity"] == "blocker"]
        history.append({"review": index + 1, "blockers": len(blockers),
                        "narrative_sha256": finding["narrative_sha256"]})
        if not blockers:
            return {"pass": True, "rounds": len(history), "reason": "数字护栏与独立审读均通过", "history": history}
        if index + 1 == max_reviews:
            return {"pass": False, "rounds": len(history), "reason": "审读上限内仍有 blocker",
                    "blockers": blockers, "history": history}
        revise(ws, run, narrative)
    raise AssertionError("unreachable")
