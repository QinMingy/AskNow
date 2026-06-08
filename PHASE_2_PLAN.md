# 第二阶段计划：实时理解辅助基础版

## Summary

第二阶段目标是把第一阶段右侧的占位按钮升级为真正的“参与辅助”能力。当前先不接 LLM，使用可测试、可替换的规则式辅助服务完成产品闭环：

```text
转写字幕 segments
  -> 最近上下文窗口
  -> 辅助动作
  -> 结构化解释 / 追问 / 补偿摘要 / 行动项草稿
  -> 前端展示给用户确认
```

关键原则仍然是：AI 只帮助用户理解和准备表达，不自动替用户发言。

## 本阶段范围

- 新增后端辅助接口：`POST /api/assist`
- 新增可替换的 `UnderstandingAssistant`
- 前端右侧按钮调用真实接口
- 输出结构化辅助结果
- 不接入 LLM
- 不做用户登录
- 不做永久存储
- 不做实时麦克风

## API 契约

请求：

```json
{
  "action": "explain",
  "window_seconds": 60,
  "segments": [
    {
      "id": 1,
      "start": 0.0,
      "end": 4.2,
      "speaker": "Speaker A",
      "text": "这里是字幕。"
    }
  ]
}
```

`action` 可选值：

- `explain`：我没听懂
- `conflict`：刚刚谁反对谁？
- `question`：帮我生成一个问题
- `catchup`：我离开了 3 分钟
- `actions`：生成会后行动项

响应：

```json
{
  "action": "explain",
  "title": "刚刚发生了什么",
  "summary": "最近 60 秒主要围绕……",
  "bullets": ["Speaker A: ..."],
  "caution": "这是基于字幕窗口的快速解释。"
}
```

## TODO List

- [x] 保存 `PHASE_2_PLAN.md`
- [x] 设计 `POST /api/assist` 契约
- [x] 创建 `UnderstandingAssistant`
- [x] 实现最近上下文窗口选择
- [x] 实现“我没听懂”
- [x] 实现“刚刚谁反对谁？”
- [x] 实现“帮我生成一个问题”
- [x] 实现“我离开了 3 分钟”
- [x] 实现“生成会后行动项”
- [x] 前端按钮接入真实接口
- [x] 补充后端测试
- [x] 运行测试

## 后续演进

后续接入 LLM 时，只需要替换或扩展 `UnderstandingAssistant` 的内部实现，保持 `/api/assist` 请求和响应结构稳定。
