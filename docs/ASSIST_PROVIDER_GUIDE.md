# 理解辅助 Provider 配置指南

第二阶段的 `/api/assist` 已经拆成可替换 provider 架构。前端和 API 契约保持不变，后端可以通过环境变量切换实现。

## 默认规则引擎

默认配置不需要任何额外服务：

```powershell
$env:ASSIST_PROVIDER="rule_based"
.\start_demo.bat
```

能力特点：

- 不联网；
- 不依赖 LLM；
- 响应快；
- 结果更像模板化辅助；
- 适合课堂助手原型和可控测试。

## OpenAI-compatible 本地模型

如果本机启动了 Ollama、LM Studio、vLLM 或其他兼容 OpenAI Chat Completions 的服务，可以切换为：

```powershell
$env:ASSIST_PROVIDER="openai_compatible"
$env:ASSIST_BASE_URL="http://127.0.0.1:11434/v1"
$env:ASSIST_MODEL="qwen2.5:7b"
$env:ASSIST_API_KEY="local-key"
.\start_demo.bat
```

字段说明：

| 环境变量 | 说明 |
| --- | --- |
| `ASSIST_PROVIDER` | `rule_based` 或 `openai_compatible` |
| `ASSIST_BASE_URL` | OpenAI-compatible 服务地址，不包含 `/chat/completions` |
| `ASSIST_MODEL` | 本地模型名 |
| `ASSIST_API_KEY` | 可选；本地服务不需要时可以随便填或不填 |
| `ASSIST_TIMEOUT_SECONDS` | 可选；默认 `60` |

请求路径会自动拼成：

```text
{ASSIST_BASE_URL}/chat/completions
```

## Provider 输出契约

无论使用哪种 provider，后端都会返回统一结构：

```json
{
  "action": "explain",
  "provider": "rule_based",
  "title": "刚刚发生了什么",
  "summary": "最近 60 秒主要围绕……",
  "bullets": ["Speaker A: ..."],
  "caution": "这是辅助草稿，是否采用仍由你决定。"
}
```

前端只依赖这个结构，不关心具体由规则引擎还是 LLM 生成。

## 设计原则

- AI 只辅助理解和准备表达，不替用户发言。
- LLM 输出必须压回统一 JSON 结构。
- 失败时只影响辅助按钮，不影响字幕转写主链路。
- 默认保留 `rule_based`，保证无模型服务时 Demo 仍然可用。
