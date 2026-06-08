# LiteLLM Provider 配置指南

项目已经将 LiteLLM 接入 `AssistProvider` 架构。前端和 `/api/assist` 契约保持不变，只需通过环境变量切换供应商。

## 基础配置

```powershell
$env:ASSIST_PROVIDER="litellm"
$env:ASSIST_MODEL="openai/gpt-4o-mini"
$env:ASSIST_API_KEY="你的 API Key"
.\start_demo.bat
```

常见模型命名示例：

- `openai/gpt-4o-mini`
- `anthropic/claude-3-5-sonnet`
- `gemini/gemini-1.5-flash`
- `openrouter/openai/gpt-4o-mini`
- `ollama_chat/qwen2.5:7b`

具体模型名称应以当前 LiteLLM 供应商文档为准。

## 连接代理或本地服务

如果使用 LiteLLM Proxy、OpenAI-compatible 网关或本地服务：

```powershell
$env:ASSIST_PROVIDER="litellm"
$env:ASSIST_MODEL="openai/local-model"
$env:ASSIST_BASE_URL="http://127.0.0.1:4000/v1"
$env:ASSIST_API_KEY="local-key"
$env:ASSIST_TIMEOUT_SECONDS="60"
.\start_demo.bat
```

## 环境变量

| 环境变量 | 说明 |
| --- | --- |
| `ASSIST_PROVIDER` | 设置为 `litellm` |
| `ASSIST_MODEL` | LiteLLM 模型名称，通常包含供应商前缀 |
| `ASSIST_API_KEY` | 供应商或代理服务的 API Key |
| `ASSIST_BASE_URL` | 可选，代理或自定义服务地址 |
| `ASSIST_TIMEOUT_SECONDS` | 可选，请求超时，默认 60 秒 |

## 配置诊断

启动后端后，可以先检查 LiteLLM provider 是否配置完整：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/api/assist/provider
```

返回示例：

```json
{
  "provider": "litellm",
  "ready": true,
  "mode": "litellm",
  "required": ["ASSIST_MODEL", "litellm package"],
  "missing": [],
  "details": ["Uses LiteLLM as a unified provider layer."],
  "next_step": "LiteLLM configuration is complete. Test with a short /api/assist request."
}
```

如果 `ready=false`，先根据 `missing` 字段补齐环境变量或依赖，再重新运行 `start_demo.bat`。

## 架构位置

```text
/api/assist
  -> UnderstandingAssistant
  -> LiteLLMAssistProvider
  -> litellm.completion(...)
  -> OpenAI / Anthropic / Gemini / OpenRouter / 本地服务
```

LiteLLM 输出会被转换为统一的 `AssistResponse`：

```json
{
  "action": "explain",
  "provider": "litellm",
  "title": "刚刚发生了什么",
  "summary": "最近讨论的主要内容……",
  "bullets": ["要点一", "要点二"],
  "caution": "这是辅助草稿，是否采用仍由你决定。"
}
```

## 设计约束

- LiteLLM 只负责统一供应商调用，不接管业务流程。
- 默认 provider 仍然是 `rule_based`，无 API Key 时项目仍可运行。
- LLM 必须返回结构化 JSON，后端再转换为 `AssistResponse`。
- AI 输出只作为理解和表达草稿，不自动替用户发言。
