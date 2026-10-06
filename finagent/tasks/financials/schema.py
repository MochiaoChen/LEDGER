"""A 股财务指标字典：标准指标 ID、中文名、财报科目别名、研报常见说法。

kind: amount（金额，内部统一为元）| per_share（元/股）| pct（百分比数值）| shares（股）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Metric:
    id: str
    name: str
    statement: str  # key_data / income / balance / cashflow / non_recurring / derived
    kind: str = "amount"
    aliases: tuple[str, ...] = ()
    claim_aliases: tuple[str, ...] = ()  # 研报里的口语化说法（用于核查）


METRICS: list[Metric] = [
    Metric("revenue", "营业收入", "income", aliases=("营业收入", "营业总收入", "一、营业总收入"),
           claim_aliases=("营业收入", "营业总收入", "营收", "收入")),
    Metric("operating_cost", "营业成本", "income", aliases=("营业成本",), claim_aliases=("营业成本",)),
    Metric("tax_surcharge", "税金及附加", "income", aliases=("税金及附加",), claim_aliases=("税金及附加",)),
    Metric("selling_expense", "销售费用", "income", aliases=("销售费用",), claim_aliases=("销售费用",)),
    Metric("admin_expense", "管理费用", "income", aliases=("管理费用",), claim_aliases=("管理费用",)),
    Metric("rd_expense", "研发费用", "income", aliases=("研发费用",), claim_aliases=("研发费用", "研发投入")),
    Metric("finance_expense", "财务费用", "income", aliases=("财务费用",), claim_aliases=("财务费用",)),
    # 非经营性损益：计算经营性 EBIT 时从利润总额中剔除（见 valuation/build_plan.py）
    Metric("investment_income", "投资收益", "income", aliases=("投资收益",), claim_aliases=("投资收益",)),
    Metric("fair_value_change", "公允价值变动收益", "income", aliases=("公允价值变动收益",),
           claim_aliases=("公允价值变动收益",)),
    Metric("operating_profit", "营业利润", "income", aliases=("营业利润", "三、营业利润"),
           claim_aliases=("营业利润",)),
    Metric("total_profit", "利润总额", "income", aliases=("利润总额", "四、利润总额"),
           claim_aliases=("利润总额",)),
    Metric("income_tax", "所得税费用", "income", aliases=("所得税费用",), claim_aliases=("所得税",)),
    Metric("net_profit", "净利润", "income", aliases=("净利润", "五、净利润"),
           claim_aliases=("净利润",)),
    Metric("np_parent", "归属于上市公司股东的净利润", "key_data",
           aliases=("归属于上市公司股东的净利润", "归属于母公司所有者的净利润", "归属于母公司股东的净利润"),
           claim_aliases=("归母净利润", "归属于上市公司股东的净利润", "归属于母公司股东的净利润")),
    Metric("np_parent_deducted", "归属于上市公司股东的扣除非经常性损益的净利润", "key_data",
           aliases=("归属于上市公司股东的扣除非经常性损益的净利润",),
           claim_aliases=("扣非归母净利润", "扣非净利润", "扣除非经常性损益后的净利润")),
    Metric("non_recurring", "非经常性损益合计", "non_recurring", aliases=("合计", "非经常性损益合计"),
           claim_aliases=("非经常性损益",)),
    Metric("gov_subsidy", "计入当期损益的政府补助", "non_recurring",
           aliases=("计入当期损益的政府补助", "计入当期损益的政府补助（与公司正常经营业务密切相关、符合国家政策规定、按照确定的标准享有、对公司损益产生持续影响的政府补助除外）"),
           claim_aliases=("政府补助",)),
    Metric("ocf", "经营活动产生的现金流量净额", "cashflow", aliases=("经营活动产生的现金流量净额",),
           claim_aliases=("经营活动现金流量净额", "经营活动产生的现金流量净额", "经营性现金流", "经营现金流")),
    Metric("capex", "购建固定资产、无形资产和其他长期资产支付的现金", "cashflow",
           aliases=("购建固定资产、无形资产和其他长期资产支付的现金",), claim_aliases=("资本开支", "资本性支出")),
    Metric("depreciation", "固定资产折旧、油气资产折耗、生产性生物资产折旧", "cashflow",
           aliases=("固定资产折旧、油气资产折耗、生产性生物资产折旧", "固定资产折旧")),
    Metric("amortization", "无形资产摊销", "cashflow", aliases=("无形资产摊销",)),
    Metric("cash", "货币资金", "balance", aliases=("货币资金",), claim_aliases=("货币资金",)),
    Metric("accounts_receivable", "应收账款", "balance", aliases=("应收账款",), claim_aliases=("应收账款",)),
    Metric("inventory", "存货", "balance", aliases=("存货",), claim_aliases=("存货",)),
    Metric("fixed_assets", "固定资产", "balance", aliases=("固定资产",), claim_aliases=("固定资产",)),
    Metric("construction_in_progress", "在建工程", "balance", aliases=("在建工程",), claim_aliases=("在建工程",)),
    Metric("accounts_payable", "应付账款", "balance", aliases=("应付账款",), claim_aliases=("应付账款",)),
    Metric("contract_liab", "合同负债", "balance", aliases=("合同负债",), claim_aliases=("合同负债", "预收款")),
    Metric("short_debt", "短期借款", "balance", aliases=("短期借款",)),
    Metric("current_ltd", "一年内到期的非流动负债", "balance", aliases=("一年内到期的非流动负债",)),
    Metric("long_debt", "长期借款", "balance", aliases=("长期借款",)),
    Metric("bonds_payable", "应付债券", "balance", aliases=("应付债券",)),
    Metric("lease_liab", "租赁负债", "balance", aliases=("租赁负债",)),
    Metric("total_assets", "资产总计", "balance", aliases=("资产总计", "总资产"), claim_aliases=("总资产",)),
    Metric("total_liabilities", "负债合计", "balance", aliases=("负债合计",), claim_aliases=("总负债",)),
    Metric("equity_parent", "归属于母公司所有者权益合计", "balance",
           aliases=("归属于母公司所有者权益合计", "归属于母公司所有者权益（或股东权益）合计", "归属于上市公司股东的净资产"),
           claim_aliases=("归母净资产",)),
    Metric("minority_equity", "少数股东权益", "balance", aliases=("少数股东权益",)),
    Metric("total_equity", "所有者权益合计", "balance",
           aliases=("所有者权益合计", "所有者权益（或股东权益）合计", "股东权益合计")),
    Metric("total_liab_equity", "负债和所有者权益总计", "balance",
           aliases=("负债和所有者权益总计", "负债和所有者权益（或股东权益）总计", "负债和股东权益总计")),
    Metric("eps_basic", "基本每股收益", "key_data", kind="per_share",
           aliases=("基本每股收益（元／股）", "基本每股收益（元/股）", "基本每股收益"),
           claim_aliases=("基本每股收益", "每股收益", "EPS")),
    Metric("roe_weighted", "加权平均净资产收益率", "key_data", kind="pct",
           aliases=("加权平均净资产收益率", "加权平均净资产收益率（%）"), claim_aliases=("ROE", "净资产收益率")),
    Metric("total_shares", "总股本", "key_data", kind="shares", aliases=("总股本", "股份总数"),
           claim_aliases=("总股本",)),
    # 派生指标（由 analyze 计算，供核查使用）
    Metric("gross_margin", "毛利率", "derived", kind="pct", claim_aliases=("毛利率",)),
    Metric("net_margin", "净利率", "derived", kind="pct", claim_aliases=("净利率", "销售净利率")),
    Metric("debt_ratio", "资产负债率", "derived", kind="pct", claim_aliases=("资产负债率",)),
    Metric("rd_ratio", "研发费用率", "derived", kind="pct", claim_aliases=("研发费用率",)),
    Metric("selling_ratio", "销售费用率", "derived", kind="pct", claim_aliases=("销售费用率",)),
    Metric("admin_ratio", "管理费用率", "derived", kind="pct", claim_aliases=("管理费用率",)),
    Metric("ocf_to_np", "经营现金流/归母净利润", "derived", kind="ratio", claim_aliases=("净现比",)),
    Metric("da", "折旧摊销", "derived", claim_aliases=("折旧摊销", "折旧与摊销")),
]

BY_ID = {m.id: m for m in METRICS}


def is_flow(metric_id: str) -> bool:
    """期间发生额（利润表、现金流量表、非经常性损益、归母/扣非净利润）：累计数可以相减拆出单季。
    时点数（资产负债表）、每股收益、比率、股本不能相减。"""
    m = BY_ID.get(metric_id)
    return m is not None and m.kind == "amount" and m.statement not in ("balance", "derived")

# 只在“非经常性损益”表中生效的别名（“合计”这类泛化词不能全局匹配）
SCOPED_ALIASES = {"合计": "non_recurring"}

_PREFIX_RE = re.compile(r"^(?:[一二三四五六七八九十]+、|其中[:：]|加[:：]|减[:：]|\d+[.、])\s*")
_SUFFIX_RE = re.compile(r"[（(](?:元|元／股|元/股|%|万元|亿元|股)[)）]$")
# 利润表科目的填列说明，如“投资收益（损失以“－”号填列）”“三、营业利润（亏损以“-”号填列）”
_SIGN_NOTE_RE = re.compile(r"[（(][^（()）]*以[^（()）]*号填列[)）]$")


def clean_label(label: str) -> str:
    s = (label or "").replace(" ", "").replace("　", "").replace("\n", "").strip()
    s = _PREFIX_RE.sub("", s)
    return _SIGN_NOTE_RE.sub("", s)


def _alias_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    for m in METRICS:
        for a in m.aliases:
            if a in SCOPED_ALIASES:
                continue
            idx[clean_label(a)] = m.id
            idx[_SUFFIX_RE.sub("", clean_label(a))] = m.id
    return idx


ALIAS_INDEX = _alias_index()


def match_label(label: str, table_caption: str = "") -> str | None:
    """财报科目名 → 指标 ID。精确匹配（去前缀/单位后缀），避免“净利润”误配“归母净利润”。"""
    s = clean_label(label)
    if not s:
        return None
    if s in ALIAS_INDEX:
        return ALIAS_INDEX[s]
    s2 = _SUFFIX_RE.sub("", s)
    if s2 in ALIAS_INDEX:
        return ALIAS_INDEX[s2]
    if "非经常性损益" in table_caption and s2 in SCOPED_ALIASES:
        return SCOPED_ALIASES[s2]
    return None


def claim_alias_list() -> list[tuple[str, str]]:
    """(说法, 指标ID)，按长度降序，便于最长匹配。"""
    pairs = [(a, m.id) for m in METRICS for a in m.claim_aliases]
    return sorted(pairs, key=lambda x: len(x[0]), reverse=True)
