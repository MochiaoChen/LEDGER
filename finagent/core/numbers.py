"""数字与单位处理（中文财报口径）。内部统一以“元”为金额单位。"""

from __future__ import annotations

import math
import re

UNIT_FACTORS = {
    "元": 1.0,
    "千元": 1e3,
    "万元": 1e4,
    "百万元": 1e6,
    "亿元": 1e8,
    "万亿元": 1e12,
    "股": 1.0,
    "万股": 1e4,
    "亿股": 1e8,
}

NUM_RE = re.compile(r"^\(?[-−–]?\d[\d,，]*(?:\.\d+)?\)?%?$")


def parse_number(raw: str | float | int | None) -> float | None:
    """'1,234.50' / '(1,234.50)' / '-12.3%' / '—' → float；无法解析返回 None。百分号去掉但不除以 100。"""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace(" ", "").replace("　", "")
    if s in ("", "-", "—", "–", "--", "不适用", "N/A", "/"):
        return None
    s = s.replace("，", ",").replace("−", "-").replace("–", "-")
    if not NUM_RE.match(s):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").rstrip("%").replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def decimals_of(raw: str) -> int:
    s = str(raw).strip().rstrip("%")
    return len(s.split(".", 1)[1]) if "." in s else 0


def half_ulp(raw: str, factor: float = 1.0) -> float:
    """按展示精度计算的舍入容差，例如 '58.62' 亿元 → 0.005 亿元。"""
    return 0.5 * 10 ** (-decimals_of(raw)) * factor


def to_yuan(value: float, unit: str) -> float:
    return value * UNIT_FACTORS.get(unit or "元", 1.0)


def pct_change(cur: float | None, prev: float | None) -> float | None:
    """同比/环比变动（%）。基期为负时按 A 股惯例用 |基期| 作分母。"""
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / abs(prev) * 100.0


def safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def close(a: float, b: float, rel: float = 1e-4, abs_: float = 0.0) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)


def fmt_yi(yuan: float | None, digits: int = 2) -> str:
    return "—" if yuan is None else f"{yuan / 1e8:,.{digits}f} 亿元"


def fmt_pct(v: float | None, digits: int = 2) -> str:
    return "—" if v is None else f"{v:.{digits}f}%"
