# FinAgent 架构说明（截至 2026-10-05）

本文按代码现状说明整条链路：从一份年报 PDF 到一份过了质检的深度研报。讲**有哪几层、每层谁干活、靠什么交接、闸门在哪里**；
实现细节以对应 skill 和源码为准。

## 一、总览

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ④ 质检循环   report_pipeline refine + finagent/evaluation                     │
│    程序检查(L0/L1) + 盲评会话(L2/L3/负向) → Python 计分 → 问题单路由 → 回滚最佳轮 │
├──────────────────────────────────────────────────────────────────────────────┤
│ ③ 多 Agent 编排   report_pipeline build / run / status / collect / scorecard   │
│    隔离工作区 + 五个无头 Claude Code 会话 + 11 道程序闸门                       │
├──────────────────────────────────────────────────────────────────────────────┤
│ ② 角色说明   .claude/skills/（4 个）+ 工作区 CLAUDE.md                          │
├──────────────────────────────────────────────────────────────────────────────┤
│ ① 计算引擎   python -m finagent …（确定性，不调用模型；标准库 + pdfplumber）    │
│    locate · verify-facts · verify-extra · verify-sources · financials ·        │
│    valuation · check · guard · numlock；全程 tracing 记录哈希                   │
└──────────────────────────────────────────────────────────────────────────────┘
```

分工原则：**模型读、抄、写、判断；程序校验、计算、拦截。** 模型给出的每个数字要么能在原文里找到，
要么由程序从真值表算出，要么登记在外部来源表里并带 `[S编号]`，否则被拒收或被 guard 拦下。

**Harness**：每个模型角色是一次 `claude -p` 无头会话（`--output-format stream-json --verbose`，`--permission-mode acceptEdits`，
工具白名单由编排器传入）。事件流原样落盘到工作区 `.pipeline/agents/<时间>-claude-<角色>.jsonl`，
轮数、费用、token 汇总到 `.pipeline/agent_runs.json`。编排器（`finagent/report_pipeline.py`）是确定性 Python，不是模型。

## 二、① 计算引擎

入口 `python -m finagent`（`finagent/__main__.py`）。三条固定流水线定义在 `finagent/pipelines.py`，每步用 `Pipeline.step`
注册，产物写入 `runs/<run_id>/` 并记录哈希。

| 流水线 | 步骤 | 主要产物 |
|---|---|---|
| financials（财报分析） | parse → extract → analyze → extras → earnings → report | `financials/analysis.json`（含 **truth_table**）、`report.md` |
| valuation（自动化估值建模） | three_statement → build_plan → dcf → reverse_dcf → scenarios → forecast_summary → comps → valuation_report | `valuation/model.xlsx`、`valuation.json`、`reverse_dcf.json`、`forecast_summary.json`（含程序评级） |
| report_check（研究报告纠错核查） | parse_report → claims → verify → consistency | `check/report.md`、`findings.json`、`consistency.json` |

抽取有两个来源：带 `--facts` 时接入分析师会话写下的 `facts.json`（逐条证据校验后与规则通道合并，冲突阻断估值）；
不带时只走规则通道（样例回归与测试用）。研报断言同理（`--claims`）。

供模型会话调用的校验命令（不生成运行目录）：

| 命令 | 作用 |
|---|---|
| `locate` | 定位关键页、母公司报表页、单位、扫描页 |
| `schema` | 可抽取的指标清单 |
| `verify-facts` | facts.json 在所写页码逐字回查；规则通道比对；勾稽；冲突、拒收、勾稽失败、核心缺失都阻断估值 |
| `verify-extra` | 经营数据表逐格回查，派生比率由程序算 |
| `verify-sources` | 外部来源登记的结构与“数字在摘句中”检查 |
| `guard` | 文稿每个数字要在本次运行的结论性产物或来源登记中找到（按展示精度）；指标与期间绑定；外部数字须带 `[S编号]`；前后矛盾；出处分类 |
| `numlock` | 改写稿的数字与来源编号必须是初稿的子集 |

估值链：**分部预测（销量 × 单价 → 收入，毛利率、费用率）→ 三表联动 → FCFF DCF**，DCF 的情景向量逐期取自三表模型同一情景；
企业价值经逐项列示的股权价值桥得到每股价值；评级由程序按“基准每股价值相对参考股价的上行空间”给出
（≥ 20% 买入、≥ 5% 增持、≥ −5% 中性、≥ −20% 减持、其余卖出），研报只引用。

## 三、② 角色说明

| Skill | 谁用 | 做什么 |
|---|---|---|
| `finagent-pipeline` | 仓库里的你（编排入口） | 搭工作区、起会话、查闸门、收回、测评；自己不写研报 |
| `finagent-research` | 分析师 | 读 PDF 抽 facts / extras / claims，跑校验与估值，起草估值假设 |
| `finagent-report` | 研究助理、主笔、排版设计师 | 资料搜集与深度调研方法、分析框架推导、文稿模板与写作规范、reportkit 排版 |
| `finagent-review` | 复核编辑 | 以没参与写作的质控编辑身份改写：删机器腔、理顺论证、前后对账；拿不准的写进 `review.md` |

`build` 只把后三个复制进工作区，并生成工作区 `CLAUDE.md`：11 个阶段各自读什么、不读什么、跑什么命令、闸门是什么。

## 四、③ 多 Agent 编排

### 4.1 生命周期

```
build ──► run ──► status ──► collect ──► (scorecard 多工作区对比)
  │        │        │           │
  │        │        │           └─ 抽取/调研/文稿 → data/extractions/<公司>_<年度>/
  │        │        │              运行目录 → runs/，PDF + sheet.xlsx + 复核清单 → report/交付/<MMDD> <公司> <标签>/
  │        │        └─ 11 道闸门逐项核对（含“输入改了、产物过期”检测）
  │        └─ 依次起五个无头会话，已通过的阶段跳过
  └─ ~/finagent-samples/<公司>_<年度>[_<标签>]，在仓库目录树之外
```

`refine` = `run` + 盲评 + 多轮返工（第五节）。

### 4.2 隔离工作区

工作区只放：三个执行 skill、计算引擎（**不含** `finagent/evaluation/`）、这家公司的年报与 `locate.json`、人给的外部输入
（`inputs/market.json`、`inputs/peers.csv`）、格式样例、解释器包装 `./py`。理由：仓库里有别家公司的框架和文稿（模型会照抄），
也有评分标准（生成方不应看到）。

`.claude/settings.json` 权限：

- 允许：`./py -m finagent *`、`./py -m finagent.report_pipeline *`、对 `data/` 的读写、`WebSearch`、`WebFetch` 等白名单工具；
- 禁止：读取仓库所在目录及其上级目录；修改 `finagent/`、`.claude/`、年报原件、`sample.json`、`py`、`CLAUDE.md`。

无头执行时同一份白名单再经 `--allowedTools` 传入。`build` 拒绝把工作区建在仓库目录树内，
也拒绝建在任何上级目录含 `CLAUDE.md` 的位置（Claude Code 会沿父目录加载它）。

### 4.3 五个会话与十一道闸门

会话之间**不继承上下文**，只靠工作区文件交接。每个会话做完自己的阶段就运行 `status` 并停止；编排器确认闸门通过才起下一个。

| 会话（默认模型） | 阶段 | 产物 | 闸门（程序判） |
|---|---|---|---|
| **研究助理**（Opus） | 1 资料搜集 | `research/sources.json`、`research/dossier.md`、可选 `research/peers.csv` | 七个类别全覆盖；检索 ≥ 20 次；近 90 天来源 ≥ 3 个；verify-sources 通过 |
| **分析师**（Opus） | 2 财务抽取 | `facts.json` → `facts.verified.json` | 拒收 / 冲突 / 勾稽失败均为 0，且校验晚于修改 |
| | 3 分析框架 | `report/framework.md` | 含“外部调研清单”和 ≥ 3 个深度专题 |
| | 4 深度调研 | `research/topics/*.md` | 专题笔记 ≥ 3 份，每份 ≥ 1500 字、≥ 3 个独立来源；补充检索 ≥ 8 个问题；sources.json 晚于 framework |
| | 5 经营数据 | `extras.json` | verify-extra 拒收 0 格 |
| | 6 估值假设 | `valuation_assumptions.json` | 有股价及来源；依据引用了资料包 `[S编号]` |
| | 7 估值运行 | `runs/<id>/valuation/...` | 运行晚于所有输入，且带了 `--extras` / `--peers` |
| **主笔**（Opus） | 8 文稿 | `report/narrative.md` | guard（含 `--sources`）通过且核对的是当前稿；正文 ≥ 15,000 字、深度研究 ≥ 60% |
| **复核编辑**（Sonnet） | 9 复核改写 | `narrative.draft.md`、`edit_log.md`、`review.md` | numlock 通过（数字只减不增不改） |
| **排版设计师**（Opus） | 10 排版 | `report/build_report.py` → PDF | PDF 晚于文稿和脚本；25～32 页；≥ 60 个图表；已命名 |
| | 11 交付说明 | `report/delivery.md` | 文件存在 |

前序阶段没过，后面即使文件齐全也一律判“未通过”，避免拿过期产物当成果。七个资料类别：最新定期报告与经营数据、
股价与市值、一致预期与目标价、可比公司与倍数、行业规模与景气、竞争格局与份额、近三个月重大事件。

### 4.4 交接文件一览

| 文件 | 谁写 | 谁读 |
|---|---|---|
| `research/sources.json`、`dossier.md` | 研究助理（分析师补充检索时追加） | 分析师、主笔；guard |
| `facts.json` / `facts.verified.json` | 分析师 / verify-facts | 引擎 |
| `report/framework.md`、`research/topics/*.md` | 分析师 | 主笔 |
| `extras.json`、`valuation_assumptions.json` | 分析师 | 引擎 |
| `runs/<id>/` | 引擎 | 主笔、排版、盲评 |
| `report/narrative.md` | 主笔 → 复核编辑改写 | 排版、盲评 |
| `narrative.draft.md`、`edit_log.md`、`review.md` | 复核编辑 | 人工；numlock |
| `report/build_report.py`、PDF、`delivery.md` | 排版设计师 | 人工；盲评 |

## 五、④ 质检循环（`refine`）

```
          ┌─────────────────────────── 第 n 轮 ───────────────────────────┐
 run ───► │ 11 道闸门全过？ ──否──► 停下，交给人                           │
          │      │是                                                     │
          │      ▼                                                       │
          │ 盲评：程序检查(L0/L1) + Sonnet 评审(L2/L3/N) → Python 计分     │
          │      │                                                       │
          │  达标？──是──► 结束                                           │
          │      │否                                                     │
          │      ▼ 问题单（只有理由和证据，不含条目原文与分值）           │
          │  数据 / 假设    ──► 修订会话(Opus)；删初稿备份，复核与排版重做   │
          │  措辞 / 结构    ──► 复核编辑(Sonnet)，数字锁照常               │
          │  版面（阶段 10）──► 排版设计师(Opus)                          │
          └───────────────────────────────────────────────────────────────┘
 停止：达标 / 满 3 轮 / 连续两轮提升 < 2 分 / 无可回传问题
 结束时回滚到得分最高的一轮；仍未达标则把剩余问题追加进 review.md
```

盲评在仓库与工作区之外单独建立的目录里进行（默认 `~/finagent-evals/<工作区名>/r<n>/blind/`），目录里只有交付物
（PDF、文稿、估值产物、来源登记、复核清单）和评审条目（只含编号、标题、判定标准、反例，不含分值）。
评审会话只能读本目录、写 `judgments.json`，不联网；“拿不准判不通过”。`loop.json` 记录每轮分数、最佳轮次与停止原因。

**评分标准 `eval/rubrics/report_v2.json`**（改权重或门槛后用 `python -m finagent.evaluation score` 重算，不必重跑评审）：

| 层 | 条目数 | 分值 | 谁判 | 内容 |
|---|---:|---:|---|---|
| L0 硬闸门 | 5 | 不计分，未过封顶 40 | 程序 | 数字护栏、三表勾稽、DCF 与三表同口径、免责声明、评级与估值一致 |
| L1 数据闭合 | 13 | 35 | 程序 | 抽取校验、分部基期闭合、价值桥加总、每股价值复算、情景排序、敏感性方向、终值占比、预测衔接、正文估值一致、外部信息可追溯、股价来源、数字锁、复核清单 |
| L2 分析质量 | 12 | 45 | 盲评 | 核心结论、预期差、商业模式、驱动拆解、业绩归因、行业竞争、预测依据、估值方法、交叉验证、情景敏感性、风险落到假设、跟踪与失效条件 |
| L3 表达与合规 | 7 | 20 | 盲评 | 故事线、事实/推论/观点、结论先行、无机器腔、数字密度、图表服务论点、假设与局限透明 |
| N 负向 | 4 | −8 / −8 / −6 / −8 | 程序（N-02）/ 盲评 | 无来源外部数据（并封顶 70）、数字前后矛盾、聚合数构成描述错误、结论前后冲突 |

交付标准：总分 ≥ 75，L1 ≥ 80%、L2 ≥ 60%、L3 ≥ 60%，且不命中负向条目。

**评审校准**（`finagent/evaluation/calibrate.py`，结果 `eval/calibration/report.md`）：同稿重复盲评看稳定性；
七种程序劣化（删交叉验证、删预期差、风险泛化、删跟踪指标、无来源数字、评级矛盾、机器腔）看判出率与连带改判；
人工质检导出算“判不通过”的精确率。

## 六、追踪与复现

| 层 | 记录 | 能否离线复现 |
|---|---|---|
| 引擎 | `runs/<id>/events.jsonl`（文件读取哈希、步骤、工具调用、产物）、`manifest.json`（输入与产物哈希、命令行、版本） | 能：用保存的抽取文件与假设逐位复算 |
| 会话 | `.pipeline/agents/*.jsonl` 事件流、`agent_runs.json` | 可查看，不能离线重放模型输出 |
| 质检 | `judgments.json`、`score.json`、`issues.json`、`loop.json` | 计分可重算；重新盲评需要模型 |

## 七、目前跑到哪一步

| 批次 | 公司 | 总分（评分标准 v0） | 达标 |
|---|---|---:|---|
| v0（旧流程：无资料搜集与独立复核） | 贵州茅台 / 宁德时代 / 招商轮船 | 48 / 49 / 46 | 否 |
| v1（先搜集 + 独立复核） | 中际旭创 / 宇树科技 | 74 / 67 | 否 |
| v2（+ 深度专题调研与篇幅闸门） | 中际旭创 / 宇树科技 | 90 / 88 | 是 |

均为单次盲评；重复盲评总分极差 7～8，版本间不是对照实验。

## 八、一条命令链（新公司出研报）

```bash
python -m finagent.report_pipeline build --company <公司> --year 2025 --price <股价> --price-source "<来源>"
```

```bash
python -m finagent.report_pipeline refine --workspace ~/finagent-samples/<公司>_2025
```

```bash
python -m finagent.report_pipeline status --workspace ~/finagent-samples/<公司>_2025
```

```bash
python -m finagent.report_pipeline collect --workspace ~/finagent-samples/<公司>_2025 --label Opus
```

只生成、不要质检循环时把 `refine` 换成 `run`；比较不同模型或配置时，各建一个带 `--tag` 的工作区后用 `scorecard`。
