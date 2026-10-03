"""数字锁：LLM 改写报告时，改写稿不得新增或改动数字（CLAUDE.md 设计规范 9）。

可读性复核会删句、调序、改措辞，所以允许数字减少；但改写稿里的每个“数字 + 单位”都必须原样出现在改写前的文稿里，
引用的外部来源编号也必须是原稿已有的。数字与指标的配对仍由改写后重跑的 guard 核对。
"""

from __future__ import annotations

import re
from typing import Any

from .guard import NUM_UNIT_RE

MARK = re.compile(r"\[(S\d+)\]")


def _tokens(text: str) -> list[str]:
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    body = MARK.sub("", body)
    out = []
    for m in NUM_UNIT_RE.finditer(body):
        raw, unit = m.group(1).replace(",", ""), m.group(2) or ""
        if not unit and re.fullmatch(r"(19|20)\d{2}|\d", raw):  # 年份、一位序号不锁
            continue
        out.append(raw + unit)
    return out


def numlock(before: str, after: str) -> dict[str, Any]:
    """返回 {ok, added: 改写稿新出现的数字, new_sources: 新出现的来源编号, removed: 删掉的数字个数}。"""
    old, new = _tokens(before), _tokens(after)
    added = sorted({t for t in new if t not in set(old)})
    new_sources = sorted(set(MARK.findall(after)) - set(MARK.findall(before)))
    return {"ok": not (added or new_sources), "added": added, "new_sources": new_sources,
            "removed": max(len(old) - len(new), 0)}
