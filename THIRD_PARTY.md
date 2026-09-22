# 第三方组件说明

| 名称 | 版本 | 来源 | 许可证 | 使用范围 |
|---|---|---|---|---|
| pdfplumber（可选依赖） | ≥0.11 | https://github.com/jsvine/pdfplumber | MIT | PDF 文本与表格抽取 |
| pytest（开发依赖） | ≥8.0 | https://pytest.org | MIT | 单元测试 |
| 大语言模型 API | 见 `.env`（如 deepseek-chat / qwen-plus / glm-4-plus） | 各模型服务商 | 各服务商服务条款 | 非标准表格抽取补漏、研报断言抽取补漏、分析文字解读、Agent 规划 |

除上述组件外，本仓库全部代码（编排、追踪、LLM 客户端、文档解析、财务抽取与分析、DCF 引擎、研报核查、报告与 xlsx 输出、评测与测试）均为自主开发，核心流程仅依赖 Python 标准库。
