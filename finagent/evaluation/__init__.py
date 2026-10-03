"""研报评测：评分标准（eval/rubrics/*.json）+ 程序检查 + 盲评会话 + 程序计分。

  L0 硬闸门、L1 数据闭合 —— checks.py 读运行产物直接判定；
  L2 分析质量、L3 表达与合规、负向条目 —— judge.py 在仓库与工作区之外的盲评目录里起一个独立的
  Claude Code 会话（默认 Sonnet），只给交付物与评审条目（不给分值），逐条输出 passed / evidence / reason；
  计分 —— rubric.py 用 Python 汇总，权重与门槛改评分标准文件后可直接重算。

评分标准对生成方不可见：工作区复制引擎时排除本包，评分标准文件放在仓库 eval/ 下、不进工作区。
"""

from .rubric import Bundle, load_rubric, score  # noqa: F401
