# 研报断言拆分规范（claims.json）

你只负责把研报草稿里**可以用财报核验的数字**逐条拆出来；是否正确、错在哪（数值/单位/期间/口径/方向），
由程序对照财报真值表判断。不要在这里写对错判断。

## 文件格式

```json
{
  "report_file": "research_draft.md",
  "claims": [
    {"metric_id": "revenue", "period": "2024", "claim_type": "level", "value": "58.62", "unit": "亿元",
     "is_forecast": false, "quote": "2024年公司实现营业收入58.62亿元"},
    {"metric_id": "revenue", "period": "2024", "claim_type": "yoy", "value": "14.49", "unit": "%",
     "is_forecast": false, "quote": "同比增长14.49%"}
  ]
}
```

| 字段 | 要求 |
|---|---|
| `metric_id` | 从 `PY -m finagent schema` 输出的 `claim_metrics` 中选；对应不上的断言不要写 |
| `period` | 断言所说的期间，如 `2024`；没写年份的按研报主报告期 |
| `claim_type` | `level` 绝对值；`yoy` 同比增速（%）；`ratio` 比率（如毛利率，%）；`pp_change` 比率的同比变动（百分点） |
| `value` | 按原文数字填字符串；**下降、减少写负数**（“同比下降5.67%”写 `"-5.67"`） |
| `unit` | 按原文：`亿元/万元/元/%/元/股`；百分点写 `pp` |
| `is_forecast` | 预测值（“预计”“预测”“2025E”“目标价”）为 `true`，程序会判为“无法核实”而不计错 |
| `quote` | **研报原文中连续出现的一段**，必须包含该数字；程序逐字核对，不符则拒收 |

一句话里有多个数字（如“营收58.62亿元，同比增长14.49%”）要拆成多条，每条的 `quote` 都可以用同一句。
