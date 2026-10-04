"""<公司> <年度> 年报点评暨深度研究：读 FinAgent 运行产物 → 图表 → HTML → PDF（目标 25～30 页、60 个以上图表）。

模板用法：复制到 data/extractions/<公司>_<年度>/report/build_report.py，改 CFG，按公司的投资主线改 body()。
标准章节（业绩、盈利能力、现金流、预测、估值）只用运行产物即可渲染；经营分析章节需要 extras.json 里的表，
在“公司专属图表”处用 run.cell()/run.ratios 取数后调用 reportkit 原语。章节、顺序、标题都可以改，这里只是起点。
templates/examples/ 下是三份 20 页级研报的定制脚本（参考样例，不是模板）：看它们的配图密度和写法。
深度研究各节（文稿里 deep_ 开头的节）的图表数据来自 research/sources.json 登记的外部资料与 research/topics/。
表格的同比、变动、上行空间列用 chg(文本, 变化量)（涨跌双色）；数值列用 td(文本, 数值)（只标负数）。

    .venv/bin/python data/extractions/<公司>_<年度>/report/build_report.py --run-dir runs/<run_id>
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / ".claude" / "skills" / "finagent-report").exists())
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "finagent-report"))

from reportkit import charts as C  # noqa: E402
from reportkit import tables as T  # noqa: E402
from reportkit.core import NAVY, SLATE, Run, md, md_parts, num, pct  # noqa: E402,F401
from reportkit.layout import Config, Doc, appendix, equity_bridge, main, two, valuation_ranges  # noqa: E402
from reportkit.tables import table, td, tr  # noqa: E402,F401


def side_rows(run: Run) -> list[tuple[str, str]]:
    """首页“基本数据”追加行（可选）：每股派息、控股股东持股等，数值从 extras 读出。"""
    return []


CFG = Config(
    company="<公司>", ticker="<代码>.SH", sector="<一级行业> · <二级行业>", date="<YYYY> 年 <M> 月 <D> 日",
    narrative=HERE / "narrative.md", output_name="",  # 如 "<公司>0929.pdf"
    side_rows=side_rows,
    method_note="",  # 公司特有的估值口径说明（如财务公司、少数股东、非经营性资产的处理），以分号结尾
)


# ================================================================== 公司专属图表（extras → 原语）
# 示例：分产品收入，上期 vs 本期，柱顶标同比。表名、行名、列名按 extras.json 改。
# def ch_segments(run, out):
#     rows = run.rows("product")
#     return C.grouped(out, "segments", rows,
#                      [(f"{run.prev} 年", [run.cell("product", r, "上期营业收入") / 1e8 for r in rows]),
#                       (f"{run.period} 年", [run.cell("product", r, "营业收入") / 1e8 for r in rows])],
#                      notes=[f"{run.cell('product', r, '营业收入同比'):+.2f}%" for r in rows],
#                      title="单位：亿元；灰字为同比")


# 深度研究各节的标题（键为文稿节名）：写结论，不写“行业分析”这类空标题
DEEP_TITLES: dict[str, str] = {
    "deep_industry": "行业：<一句话结论>",
    "deep_competition": "竞争格局：<一句话结论>",
    "deep_moat": "核心竞争力：<一句话结论>",
    "deep_expectations": "预期差：<一句话结论>",
}


# 关键假设的依据：键为“<分部名>销量增速 / <分部名><单价名称>增速 / <分部名>毛利率 / 销售费用率 / 其他费用率 / 现金分红率”，
# 值写依据并注明对应正文第几节。
BASIS: dict[str, str] = {}


# ================================================================== 第二部分 深度研究
def deep_part(doc: Doc, S: dict[str, str]) -> str:
    """文稿里 deep_ 开头的节按出现顺序成章；每章之后放该章的图表（TODO 处按专题补图）。"""
    out = [doc.part("第二部分 深度研究", "<一句导语：这一部分要回答的核心问题>")]
    for key in [k for k in S if k.startswith("deep_")]:
        out.append(doc.sec(DEEP_TITLES.get(key, f"<{key}：一句话结论>")))
        out.append(md(S[key]))
        out.append(f"<!-- TODO：{key} 的图表（市场空间、份额、对手对标、价格与产能……） -->")
    return "\n".join(out)


# ================================================================== 正文编排
def body(doc: Doc, S: dict[str, str]) -> str:
    run, img, fig = doc.run, doc.img, doc.fig
    I = lambda fn, w=83: img(fn(run, doc.ch), w)  # noqa: E731,E741  公司专属图：I(ch_segments)
    p, q = run.period, run.prev
    part = lambda k: md_parts(S.get(k, "")) + [""] * 4  # noqa: E731  按 ### 拆块，不足补空
    thesis, perf, prof, cash, val = part("thesis"), part("performance"), part("profitability"), part("cashflow"), part("valuation")
    has_seg = bool(run.seg)
    return f"""
<section class="body">
  {doc.h2(1, "投资逻辑：<一句话结论>")}
  {thesis[0]}
  {fig(f"营业收入与归母净利润（实际与预测）", img(C.history, 172), "预测为基准情景")}
  {thesis[1]}

  {doc.part("第一部分 年报点评", "<一句导语>")}
  {doc.h2(2, "公司概况：<一句话结论>")}
  {md(S.get("overview", ""))}
  {two(fig("盈利质量：ROE 与净现比", img(C.quality)), fig("近三年主要会计数据与财务指标", T.three_year(run)))}

  {doc.h2(3, "业绩回顾：<一句话结论>")}
  {perf[0]}
  {fig("主要财务指标", T.core(run), cls="split")}
  {perf[1]}
  {two(fig(f"{p} 年分季度营业收入与归母净利润（亿元）", img(C.quarterly)), fig(f"{p} 年分季度主要财务数据", T.quarterly(run)))
   if run.quarterly else ""}

  {doc.h2(4, "<经营分析：按公司主线命名，可拆成多节>")}
  {md(S.get("business", ""))}
  <!-- TODO：经营分析图表，例如 two(fig("分产品收入（亿元）", I(ch_segments)), fig(...)) -->

  {doc.h2(5, "盈利能力：<一句话结论>")}
  {prof[0]}
  {prof[1]}
  {fig(f"归母净利润变动归因（{q} 年至 {p} 年，亿元）", img(C.bridge, 172),
       "收入规模效应 = Δ营业收入 × 上年毛利率；毛利率效应 = 本年营业收入 × Δ毛利率")}

  {doc.h2(6, "资产负债与现金流：<一句话结论>")}
  {md(S.get("balance", ""))}
  {cash[0]}
  {two(fig("资产负债与营运资本", T.balance(run)), fig(f"{p} 年分季度经营现金流与归母净利润", img(C.cash_quarterly)))
   if run.quarterly else fig("资产负债与营运资本", T.balance(run))}

  {doc.h2(7, "年报之后：<一句话结论>")}
  {md(S.get("latest", ""))}
  <!-- TODO：最新季报 / 半年报对比图（外部资料登记的数值，src 写发布方与 [S编号]） -->

  {deep_part(doc, S)}

  {doc.sec("盈利预测：<一句话结论>")}
  {md(S.get("forecast", ""))}
  {fig("关键假设与依据", T.assumptions(run, BASIS), "假设为分析师观点") if has_seg else ""}
  {fig("分部收入预测", T.segment_forecast(run), "基准情景", cls="split") if has_seg else ""}
  {two(fig("分部收入预测", img(C.segment_forecast), "基准情景"), fig("利润率与销售费用率", img(C.margins), "基准情景"))
   if has_seg else fig("利润率", img(C.margins), "基准情景", cls="half")}
  {fig("盈利预测", T.forecast(run, last=5), "基准情景")}

  {doc.sec(f"估值：DCF 基准情景每股价值 {num(run.scen['base']['value_per_share'])} 元")}
  {val[0]}
  {two(fig("折现参数", T.wacc(run), "参数为分析师假设"), fig("三情景营业收入", img(C.scenarios))) if has_seg
   else fig("折现参数", T.wacc(run), "参数为分析师假设", cls="half")}
  {fig("FCFF 预测与折现（基准情景）", T.fcff(run))}
  {fig("从企业价值到每股价值", img(C.ev_bridge, 172))}
  {equity_bridge(doc)}
  {val[1]}
  {fig("三情景关键驱动与估值", T.scenario_table(run)) if has_seg else ""}
  {valuation_ranges(doc)}

  {doc.sec("投资建议")}
  {md(S.get("recommendation", ""))}

  {doc.sec("风险提示")}
  {md(S.get("risks", ""))}

  {doc.sec("跟踪指标与结论失效条件")}
  {md(S.get("tracking", ""))}
</section>
{appendix(doc, CFG, "第 7、8 节")}"""


if __name__ == "__main__":
    sys.exit(main(CFG, body))
