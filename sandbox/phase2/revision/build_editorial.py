"""Build the reader-facing revision from unchanged, verified valuation runs.

The original PDF files are preserved under revision/original. This script
changes only narrative selection, figure selection, display wording, and
cover-chart styling; all numbers remain sourced from the existing runs.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNS = {
    "宁德时代": "20261002-003730-valuation",
    "招商轮船": "20261002-005015-valuation",
}
sys.path.insert(0, str(ROOT / ".claude/skills/finagent-report"))
from reportkit import layout  # noqa: E402


DROP = {
    "宁德时代": (
        "前六大股东持股比例", "员工专业构成", "盈利质量：ROE 与净现比", "2025 年行业需求", "分季度主要财务数据",
        "电池系统平均单位售价", "主营业务构成", "产能利用与库存", "电池系统产销存",
        "境内与境外营业收入", "境内与境外毛利率", "研发费用明细", "管理费用明细",
        "财务费用明细", "非主业损益项目", "非主业损益占比", "主要资产占总资产比例", "资产减值损失",
        "经营性负债", "分季度经营现金流", "现金流量主要项目", "每 10 股派息",
        "分产品收入预测", "三情景营业收入",
    ),
    "招商轮船": (
        "前四大股东持股比例", "盈利质量：ROE 与净现比", "主要控股参股公司", "分季度主要财务数据",
        "油轮运输成本构成", "分部报告：", "船队经营指标", "主要新造船项目累计投入",
        "报告期末船队概况", "折旧与摊销", "筹资性负债构成", "负债与偿债能力",
        "分季度经营现金流", "投资与筹资主要现金流", "年度现金股东回报构成",
        "营业收入增速假设", "参考股价对应的估值水平",
    ),
}

HEADINGS = {
    "宁德时代": {
        "投资逻辑：以量换价份额再升，单位盈利稳住": "投资逻辑：出货增长与成本改善共同驱动利润",
        "公司概况与行业：动力与储能双龙头，A+H 两地上市": "业务结构：动力电池为主，储能贡献增量",
        "业绩回顾：量增驱动收入增长，利润增速快于收入": "业绩回顾：成本增速低于收入，利润率抬升",
        "产品与量价：动力电池放量，平均售价随原材料下行": "产品与量价：销量快于收入，单位收入承压",
        "产能、库存与区域：满产扩产，境外毛利率更高": "产能与库存：交付扩张伴随库存占用",
        "盈利能力：毛利率逆势提升，非主业贡献可观": "盈利能力：材料成本与产品结构改善毛利率",
        "资产负债与现金流：占款增强现金流，存货与质保需跟踪": "资产与现金流：经营现金增长，库存周转待观察",
        "股东回报：分红率 50%，叠加回购": "股东回报：现金流支持分红与回购",
        "盈利预测：量价拆分，收入保持两位数增长": "盈利预测：量增与降价并行，利润增速趋缓",
    },
    "招商轮船": {
        "投资逻辑：油轮景气推升业绩，估值已透支中枢盈利": "投资逻辑：油轮利润增长，估值取决于运价路径",
        "公司概况：油散双核，招商局控股的全船型航运平台": "业务结构：油轮贡献主要利润增量",
        "业绩回顾：收入稳增、扣非持平，四季度利润近半": "业绩回顾：归母增长，扣非利润基本持平",
        "分船型：油轮量价齐升，散货与集运以量补价": "分船型：油轮利润增长，租船成本压制其他业务",
        "船队与资本开支：订单占运力两成，LNG 船队规模将翻倍": "船队与资本开支：新船交付提高资金需求",
        "盈利能力：燃油降、租金与折旧升，卖船收益抬高利润": "盈利能力：成本上行，非经常性收益抬高净利",
        "资产负债与现金流：净负债上行，现金流覆盖资本开支但余量有限": "资产与现金流：扩表增杠杆，投资占用现金",
        "股东回报：分红率 43%，回购注销常态化": "股东回报：分红与船队更新并行",
        "盈利预测：2026 年见顶，2027～2028 年回落至周期中枢": "盈利预测：基准情景假设运价冲高后回落",
    },
}


def build(company: str) -> None:
    spec = importlib.util.spec_from_file_location(
        "finagent_editorial_company_layout",
        ROOT / f"data/extractions/{company}_2025/report/build_report.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.CFG.output_name = ""
    mod.CFG.rating_note = ""

    base_cover = layout.cover_side

    def cover_side(doc, cfg):
        side = base_cover(doc, cfg).replace("当前股价（元）", "参考股价（元）")
        side = side.replace("较当前股价空间", "较参考股价空间")
        return side.replace(
            "</aside>",
            '<div class="note">图例：红/蓝为实际，浅金/浅蓝为预测；A 为实际年度，E 为基准情景预测年度。</div></aside>',
        )

    layout.cover_side = cover_side
    base_notes = layout.appendix_notes
    layout.appendix_notes = lambda run, cfg, secs: base_notes(run, cfg, secs).replace(
        "当前股价为外部行情数据", "参考股价为外部行情数据"
    )
    base_css = layout.css
    layout.css = lambda cfg, run: base_css(cfg, run) + """
    .appendix { font-size: 8.5pt; }
    .appendix .small { font-size: 7.2pt; line-height: 1.43; }
    .appendix h3 { margin-top: 2mm; margin-bottom: 0.7mm; }
    .appendix .fin td, .appendix .fin th { padding-top: 0.6mm; padding-bottom: 0.6mm; }
    """
    if company == "招商轮船":
        mod.CFG.method_note = (
            "年报未披露分船型 TCE，预测采用合并收入与毛利率；营业成本已含船舶折旧。"
            "使用权资产摊销与租赁负债处理可能重复扣减；长期股权投资按账面加回，"
            "长期应付款按类负债扣减。"
        )
        original_notes = layout.appendix_notes
        layout.appendix_notes = lambda run, cfg, secs: re.sub(
            r'<h3>投资评级说明</h3>\s*<p class="small">.*?</p>', "",
            original_notes(run, cfg, secs), flags=re.S,
        )

    mod.two = lambda a, b: f'<div class="two">{a}{b}</div>' if a and b else (a or b)
    original_body = mod.body

    def selected_body(doc, sections):
        original_fig = doc.fig
        original_h2 = doc.h2

        def fig(title, body, note="", cls=""):
            if any(x in title for x in DROP[company]):
                return ""
            note = note.replace("由程序按", "按")
            return original_fig(title, body, note, cls)

        def h2(n, title):
            return original_h2(n, HEADINGS[company].get(title, title))

        doc.fig = fig
        doc.h2 = h2
        return original_body(doc, sections)

    run = ROOT / "sandbox/phase2/runs" / RUNS[company]
    narrative = ROOT / "sandbox/phase2/reports" / company / "editorial.md"
    raise SystemExit(layout.main(mod.CFG, selected_body,
                                 ["--run-dir", str(run), "--narrative", str(narrative)]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("company", choices=RUNS)
    build(parser.parse_args().company)
