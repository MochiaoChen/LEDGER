"""统一命令行：finagent <命令组> ...

原来分散在 python -m finagent / finagent.report_pipeline / finagent.evaluation / calibrate / doctor 与
eval/run_eval.py 的入口收在一处；各命令组的参数与原入口完全相同，旧入口继续可用。
"""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
from typing import Callable

from .core.config import PROJECT_ROOT

# 财报分析、估值建模、纠错核查的计算、校验与护栏命令（原 python -m finagent <task>）
RESEARCH_TASKS = ("financials", "valuation", "check", "all", "locate", "schema", "verify-facts",
                  "verify-extra", "guard", "verify-sources", "numlock")


def _research(argv: list[str]) -> int:
    from .__main__ import main
    return main(argv)


def _report(argv: list[str]) -> int:
    from .report_pipeline import main
    return main(argv)


def _eval(argv: list[str]) -> int:
    from .evaluation.__main__ import main
    return main(argv)


def _calibrate(argv: list[str]) -> int:
    from .evaluation.calibrate import main
    return main(argv)


def _doctor(argv: list[str]) -> int:
    from .doctor import main
    return main(argv)


def _bench(argv: list[str]) -> int:
    sys.argv = [str(PROJECT_ROOT / "eval" / "run_eval.py"), *argv]
    try:
        runpy.run_path(sys.argv[0], run_name="__main__")
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def _test(argv: list[str]) -> int:
    return subprocess.call([sys.executable, "-m", "pytest", "-q", str(PROJECT_ROOT / "tests"), *argv])


def _tui(argv: list[str]) -> int:
    try:
        from finagent_tui.app import main
    except ImportError as e:
        if "textual" not in str(e):
            raise
        print("终端界面需要 Textual：pip install 'textual>=1.0'（可选依赖，见 requirements.txt）", file=sys.stderr)
        return 2
    return main(argv)


def _ls(argv: list[str]) -> int:
    from . import catalog

    ws, rs = catalog.workspaces(), catalog.runs(limit=10)
    if "--json" in argv:
        print(json.dumps({"workspaces": [{"company": s.company, "path": str(s.workspace), "run": str(s.run)} for s in ws],
                          "runs": [{"id": s.title, "company": s.company, "path": str(s.run)} for s in rs]},
                         ensure_ascii=False, indent=2))
        return 0
    print(_b("研报工作区") + _dim(f"  {ws[0].workspace.parent if ws else '（无）'}"))
    for s in ws:
        g = catalog.gates(s) or {}
        stages = g.get("stages", [])
        passed = sum(st["ok"] for st in stages)
        sc = catalog.scores(s)
        last = f"  质检 {sc[-1]['total']:g} 分" if sc else ""
        state = _green("✓ 全部闸门通过") if g.get("done") else _yellow(f"{passed}/{len(stages)} 闸门 · 下一步：{g.get('next', '—')}")
        print(f"  {s.title:<14} {state}{last}")
    print(_b("\n仓库运行目录") + _dim("  runs/（最近 10 个含财务分析的）"))
    for s in rs:
        print(f"  {s.title:<28} {s.company}")
    return 0


GROUPS: dict[str, tuple[Callable[[list[str]], int], str]] = {
    "research": (_research, "财报分析 / 估值 / 研报纠错与 Skill 辅助命令（financials、all、verify-facts、guard…）"),
    "report": (_report, "研报流水线：build 工作区、run 无头执行、status 闸门、refine 多 Agent 循环、collect"),
    "eval": (_eval, "研报评测：run 盲评、score 重算、compare 对比、pack 质检包"),
    "calibrate": (_calibrate, "评审校准：重复评审稳定性、劣化命中、人工一致"),
    "bench": (_bench, "样例评测集：抽取准确率与纠错召回 / 准确率（改代码后必跑）"),
    "test": (_test, "运行全部测试"),
    "doctor": (_doctor, "运行环境自检"),
    "ls": (_ls, "列出研报工作区与运行目录"),
    "tui": (_tui, "终端界面：闸门、真值表回溯、估值、质检、追溯回放、Agent 日志"),
}


def _color(code: str) -> Callable[[str], str]:
    on = sys.stdout.isatty() and not os.getenv("NO_COLOR")
    return lambda s: f"\033[{code}m{s}\033[0m" if on else s


_b, _dim, _green, _yellow, _cyan = _color("1"), _color("2"), _color("32"), _color("33"), _color("36")


def usage() -> str:
    lines = [_b("FinAgent") + " 金融投研智能体 · 财报分析 · 自动化估值建模 · 研报纠错核查", "",
             _b("用法") + "  finagent <命令组> [参数]      " + _dim("各命令组 -h 查看参数"), ""]
    for name, (_, desc) in GROUPS.items():
        lines.append(f"  {_cyan(name.ljust(10))} {desc}")
    lines += ["", _b("常用"),
              "  finagent research all --input 年报.pdf --year 2025 --company 公司 --assumptions 假设.json --report 研报.md",
              "  finagent report build --company 宁德时代 --year 2025 --price 250 --price-source \"收盘价\"",
              "  finagent report refine --workspace ~/finagent-samples/宁德时代_2025",
              "  finagent tui", "",
              _dim("兼容：finagent financials|all|verify-facts… 等同 finagent research <命令>；python -m finagent 照旧可用。")]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    head, rest = argv[0], argv[1:]
    if head in RESEARCH_TASKS:
        return _research(argv)
    if head not in GROUPS:
        print(usage(), file=sys.stderr)
        print(f"\n未知命令：{head}", file=sys.stderr)
        return 2
    return GROUPS[head][0](rest)


if __name__ == "__main__":
    sys.exit(main())
