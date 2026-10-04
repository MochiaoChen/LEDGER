"""反向 DCF：参考股价隐含了什么。

正向 DCF 由假设推出每股价值；这里反过来，固定其余假设为基准情景，只动一个变量，
用二分法解出“每股价值恰好等于参考股价”时该变量的取值：
  收入增速：预测期每年增速同加一个常数（保持基准的年度形态），报告隐含的预测期收入复合增速；
  EBIT 利润率：预测期每年利润率同加一个常数，报告隐含的预测期平均利润率；
  折现率：WACC 同加一个常数，即按基准现金流、现价买入的隐含年化回报率；
  永续增长率 / 退出倍数：随终值方法二选一。
每个变量单独求解（其余不动），不是联合解；只动 DCF 层，不回推三表模型（口径简化，写入 notes）。

可行性分档由程序按历史与基准对照给出，文字解读只能引用这里的分档，不自行判断。
比率存小数（0.08 表示 8%），金额为百万元，每股为元。
"""

from __future__ import annotations

from typing import Any, Callable

from ..financials.analyze import FactTable
from . import dcf
from .build_plan import EBIT_PARTS

TOL = 1e-6        # 每股价值求解精度（元）
MAX_ITER = 200
HISTORY_YEARS = 5  # 往前看几年历史
SCAN_STEPS = 400   # 求解前的网格扫描点数


def _bisect(f: Callable[[float], float | None], lo: float, hi: float) -> float | None:
    """解 f(x) = 0；端点不变号或函数无定义时返回 None。"""
    flo, fhi = f(lo), f(hi)
    if flo is None or fhi is None or flo * fhi > 0:
        return None
    for _ in range(MAX_ITER):
        mid = (lo + hi) / 2
        fm = f(mid)
        if fm is None:
            return None
        if abs(fm) <= TOL or hi - lo <= 1e-12:
            return mid
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2


def _solve(f: Callable[[float], float | None], lo: float, hi: float, steps: int = SCAN_STEPS
           ) -> tuple[float | None, tuple[float, float] | None]:
    """先按网格扫描找离基准（0）最近的变号区间再二分；每股价值对增速不一定单调
    （增长越快，营运资本与资本开支占用越多），所以不能只看两个端点。
    返回（解，网格上 f 的最大值点 (x, f)）；无解时第二项用于说明“该变量最多能把每股价值推到多少”。"""
    xs = [lo + (hi - lo) * i / steps for i in range(steps + 1)]
    ys = [f(x) for x in xs]
    pts = [(x, y) for x, y in zip(xs, ys) if y is not None]
    best = max(pts, key=lambda t: t[1]) if pts else None
    brackets = [(a, b) for (a, fa), (b, fb) in zip(pts, pts[1:]) if fa == 0 or fa * fb < 0]
    if not brackets:
        return None, best
    a, b = min(brackets, key=lambda ab: min(abs(ab[0]), abs(ab[1])))
    return _bisect(f, a, b), best


def _vps(plan: dict[str, Any], **kw: Any) -> float | None:
    try:
        return dcf.run_scenario(plan, "base", **kw)["value_per_share"]
    except ZeroDivisionError:
        return None


def history(truth_table: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    """最近几个年度的收入增速与 EBIT 利润率（EBIT 口径与 DCF 一致），按年份升序。"""
    t = FactTable(truth_table)
    y = int(str(period)[:4])
    rows = []
    for yy in range(y - HISTORY_YEARS + 1, y + 1):
        rev, prev = t.v("revenue", str(yy)), t.v("revenue", str(yy - 1))
        parts = [t.v(m, str(yy)) for m, _ in EBIT_PARTS]
        ebit = sum(s * (v or 0.0) for (_, s), v in zip(EBIT_PARTS, parts)) if parts[0] is not None else None
        if rev is None:
            continue
        rows.append({"year": str(yy),
                     "revenue_growth": rev / prev - 1 if prev else None,
                     "ebit_margin": ebit / rev if ebit is not None and rev else None})
    return rows


def _cagr(rows: list[dict[str, float]], start: float) -> float:
    return (rows[-1]["revenue"] / start) ** (1 / len(rows)) - 1


def _avg_margin(rows: list[dict[str, float]]) -> float:
    return sum(r["ebit_margin"] for r in rows) / len(rows)


def _grade(implied: float, base: float, hist_max: float | None, higher_is_harder: bool = True) -> str:
    """隐含值相对基准与历史最好水平的分档。"""
    sign = 1 if higher_is_harder else -1
    if sign * (implied - base) <= 0:
        return "不高于基准假设"
    if hist_max is None:
        return "高于基准假设（无历史可比）"
    if sign * (implied - hist_max) <= 0:
        return "高于基准假设，但在历史区间内"
    return "超出历史最好水平"


def run(plan: dict[str, Any], valuation: dict[str, Any], current_price: float | None,
        hist: list[dict[str, Any]]) -> dict[str, Any]:
    if valuation.get("status") != "ok" or not current_price:
        return {"status": "skipped", "reason": "缺少参考股价或 DCF 未完成"}
    p = dcf.normalize_plan(plan)
    price = float(current_price)
    base_run = dcf.run_scenario(p, "base")
    base_rows = base_run["forecast_rows"]
    rev0 = float(p["historicals"]["revenue"])
    base_cagr, base_margin = _cagr(base_rows, rev0), _avg_margin(base_rows)
    base_wacc = base_run["discount_rate"]
    g_hist = [h["revenue_growth"] for h in hist if h["revenue_growth"] is not None]
    m_hist = [h["ebit_margin"] for h in hist if h["ebit_margin"] is not None]
    method = p["terminal_value"]["method"]
    g_base = base_run["terminal"]["terminal_growth_rate"]
    levers: list[dict[str, Any]] = []

    def gap(key: str) -> Callable[[float], float | None]:
        def f(x: float) -> float | None:
            v = _vps(p, **{key: x})
            return None if v is None else v - price
        return f

    def solve(key: str, lo: float, hi: float, row: dict[str, Any], implied_of: Callable[[float], float],
              grade_of: Callable[[float], str]) -> None:
        row.setdefault("historical_max", None)
        row.setdefault("historical_avg", None)
        d, best = _solve(gap(key), lo, hi)
        if d is None:
            row.update(implied=None, grade="单独调整达不到参考股价")
            if best is not None:  # 网格上该变量能把每股价值推到的最高点
                row.update(max_value_per_share=best[1] + price, implied_at_max=implied_of(best[0]),
                           max_inside_range=lo < best[0] < hi)
        else:
            implied = implied_of(d)
            row.update(implied=implied, delta_vs_base=implied - row["base"], annual_shift=d, grade=grade_of(implied))
        levers.append(row)

    # 1. 收入增速
    g_max = max(g_hist) if g_hist else None
    solve("growth_delta", -0.9, 2.0,
          {"lever": "revenue_growth", "name": "预测期收入复合增速", "base": base_cagr, "historical_max": g_max,
           "historical_avg": sum(g_hist) / len(g_hist) if g_hist else None},
          lambda d: _cagr(dcf.forecast(p, "base", growth_delta=d), rev0),
          lambda v: _grade(v, base_cagr, g_max))

    # 2. EBIT 利润率
    m_max = max(m_hist) if m_hist else None
    solve("margin_delta", -1.0, 1.0,
          {"lever": "ebit_margin", "name": "预测期平均 EBIT 利润率", "base": base_margin, "historical_max": m_max,
           "historical_avg": sum(m_hist) / len(m_hist) if m_hist else None},
          lambda d: base_margin + d, lambda v: _grade(v, base_margin, m_max))

    # 3. 折现率（隐含回报率）：越高说明现价越便宜
    floor = (g_base - base_wacc + 1e-4) if method == "perpetual_growth" else -base_wacc + 1e-4
    solve("wacc_delta", floor, 1.0, {"lever": "wacc", "name": "隐含折现率（按基准现金流）", "base": base_wacc},
          lambda d: base_wacc + d,
          lambda v: "现价隐含回报率高于基准 WACC" if v > base_wacc else "现价隐含回报率不高于基准 WACC")

    # 4. 终值参数（随终值方法二选一）
    above = lambda base: (lambda v: "高于基准假设" if v > base else "不高于基准假设")  # noqa: E731
    if method == "perpetual_growth":
        solve("g_delta", -0.5, base_wacc - g_base - 1e-4,
              {"lever": "terminal_growth", "name": "隐含永续增长率", "base": g_base},
              lambda d: g_base + d, above(g_base))
    else:
        m_base = float(p["terminal_value"].get("exit_ebitda_multiple") or 0)
        solve("multiple_delta", -m_base, 200.0,
              {"lever": "exit_multiple", "name": "隐含退出 EV/EBITDA 倍数", "base": m_base},
              lambda d: m_base + d, above(m_base))

    base_vps = base_run["value_per_share"]
    return {
        "status": "ok",
        "current_price": price,
        "base_value_per_share": base_vps,
        "price_vs_base": price / base_vps - 1 if base_vps else None,
        "terminal_method": method,
        "levers": levers,
        "history": hist,
        "notes": [
            "每个变量单独求解，其余假设保持基准情景；不是联合解。",
            "收入增速与利润率为预测期每年同加一个常数，保持基准的年度形态；只动 DCF 层，三表模型不随之重算。",
            "历史区间取财报真值表最近年度，EBIT 口径与 DCF 一致（剔除投资收益与公允价值变动）。",
        ],
    }
