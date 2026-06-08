# 使用 FastAPI 实现前后端分离的方法论

## 1. 核心目标

前后端分离的本质不是把文件放进两个目录，而是建立清晰、稳定的协作边界：

```text
浏览器前端
  -> HTTP API 契约
  -> FastAPI 路由层
  -> 业务服务层
  -> 模型、数据库或外部服务
```

前端负责交互和状态展示，后端负责业务规则、资源访问、安全控制和结构化数据。双方只通过 API 契约通信，不依赖彼此内部实现。

## 2. 先设计 API 契约

实现界面前，先明确请求和响应结构。契约至少包含：

- 路径和 HTTP 方法；
- 请求字段、类型和限制；
- 成功响应结构；
- 错误响应结构；
- 状态码；
- 是否为同步任务；
- 是否需要认证。

例如音频上传：

```text
POST /api/transcribe
Content-Type: multipart/form-data
file: audio file
```

成功响应：

```json
{
  "language": "zh",
  "duration": 123.4,
  "segments": []
}
```

失败响应：

```json
{
  "detail": "Unsupported audio format."
}
```

统一契约可以让前端独立开发，也让后端实现替换时不影响界面。

## 3. 建立清晰的后端分层

推荐结构：

```text
backend/
  app/
    main.py          # 创建 FastAPI 应用和挂载路由
    config.py        # 集中配置
    schemas.py       # 请求和响应模型
    dependencies.py  # 依赖注入
    transcriber.py   # 业务服务
    sources/         # 可替换的外部来源适配器
  tests/
```

各层职责：

| 层 | 职责 |
| --- | --- |
| 路由层 | 接收请求、调用服务、返回响应 |
| Schema 层 | 定义和校验 API 数据结构 |
| 业务服务层 | 实现业务流程与规则 |
| 适配器层 | 调用模型、数据库或第三方服务 |
| 配置层 | 管理端口、模型、路径和环境变量 |

路由函数应保持简短。复杂流程放进服务层，否则路由会快速变成难以测试的“大函数”。

## 4. 使用 Pydantic 固化数据边界

FastAPI 使用 Pydantic 定义请求和响应模型。它的价值不只是自动文档，还包括：

- 自动校验输入；
- 明确字段类型和可选性；
- 避免返回结构随实现细节漂移；
- 生成 OpenAPI 文档；
- 让测试直接验证契约。

示例：

```python
class TranscriptSegment(BaseModel):
    id: int
    start: float
    end: float
    speaker: str
    text: str


class TranscriptionResponse(BaseModel):
    language: str
    duration: float
    segments: list[TranscriptSegment]
```

接口应显式声明 `response_model`，让 FastAPI 对输出进行校验和过滤。

## 5. 使用依赖注入管理服务

模型实例、配置和业务服务不应在每个路由中重复创建。FastAPI 的依赖注入可以负责提供这些对象：

```python
def get_transcriber() -> Transcriber:
    return transcriber


@app.post("/api/transcribe")
async def transcribe(
    file: UploadFile,
    transcriber: Transcriber = Depends(get_transcriber),
):
    return await transcriber.transcribe_upload(file)
```

依赖注入带来的好处：

- 测试时可以替换为假实现；
- 资源生命周期更明确；
- 路由只关注调用流程；
- 避免业务代码与全局变量紧密耦合。

## 6. 前端只依赖 API

无论前端使用 React、Vue，还是无构建静态页面，都应通过统一的 API 客户端调用后端：

```javascript
async function transcribeFile(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE}/api/transcribe`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Transcription failed.");
  }

  return response.json();
}
```

前端不应了解模型如何运行，也不应解析后端日志或底层异常。它只处理 API 的成功数据和标准错误。

## 7. 管理前端状态

每个长操作都应有明确状态机：

```text
idle
  -> uploading
  -> processing
  -> success
  -> error
```

界面根据状态决定按钮是否可用、显示什么提示、是否允许再次提交。避免只使用一个模糊的 `loading` 布尔值承载所有状态。

状态设计应包含：

- 当前输入；
- 请求是否进行中；
- 成功结果；
- 错误消息；
- 是否允许取消或重试。

## 8. 正确处理跨域

开发阶段前端和后端通常运行在不同端口，因此浏览器会执行跨域检查：

```text
Frontend: http://127.0.0.1:5173
Backend:  http://127.0.0.1:8010
```

FastAPI 可配置 CORS：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

开发阶段可以适当放宽，生产环境应明确允许的域名。不要把 CORS 当作认证或权限控制，它只是一项浏览器访问策略。

## 9. 设计可理解的错误

后端负责把不同错误映射到合适状态码：

| 状态码 | 使用场景 |
| --- | --- |
| `400` | 参数或文件格式错误 |
| `401` / `403` | 未认证或无权限 |
| `404` | 资源不存在 |
| `413` | 上传文件过大 |
| `422` | 请求结构校验失败 |
| `500` | 未预期的服务错误 |
| `503` | 模型或外部依赖暂不可用 |

前端应显示面向用户的消息，同时保留重试入口。详细异常和堆栈只写入后端日志。

## 10. 区分短请求与长任务

普通 CRUD 请求可以同步完成，但模型推理、视频下载和长音频转写可能持续数十秒甚至更久。

原型阶段可以使用同步接口：

```text
提交文件 -> 等待处理 -> 返回完整结果
```

随着任务变长，应演进为异步任务：

```text
POST /api/jobs
  -> 返回 job_id

GET /api/jobs/{job_id}
  -> 返回 queued / processing / completed / failed

GET /api/jobs/{job_id}/result
  -> 返回最终结果
```

实时进度可以使用轮询、Server-Sent Events 或 WebSocket。不要在没有必要时一开始就引入复杂消息队列，但要避免让同步接口成为无法扩展的永久结构。

## 11. 测试策略

前后端分离项目至少需要三类测试：

### 后端单元测试

替换模型或外部服务，验证业务规则和异常转换。

### API 契约测试

通过 FastAPI 测试客户端验证：

- 状态码；
- 响应字段；
- 文件格式校验；
- 依赖不可用时的错误；
- 路由是否调用正确服务。

### 端到端验收

在浏览器中完成一次真实操作，验证前端状态、跨域、接口和结果展示共同工作。

只测试后端接口不能证明前端可用，只测试界面也不能稳定覆盖错误分支。

## 12. 本地运行与部署演进

开发阶段可以分别启动：

```text
前端静态服务器 -> 5173
FastAPI/Uvicorn -> 8010
```

生产部署通常有两种方式：

1. 前端静态文件由 Nginx/CDN 托管，API 请求转发到 FastAPI。
2. FastAPI 同时托管静态前端和 API，适合较小的本地应用。

部署时需要额外考虑：

- HTTPS；
- 认证和权限；
- 上传大小限制；
- 超时；
- 日志和监控；
- 反向代理；
- 后端进程数与模型显存占用；
- 临时文件和结果存储策略。

## 13. 可扩展性原则

为了让系统后续容易增加新能力：

- 使用统一 API 前缀，例如 `/api`；
- 保持响应结构稳定；
- 业务服务与外部来源使用接口或适配器；
- 新视频来源通过注册机制扩展；
- 配置集中管理；
- 前端 API 地址集中配置；
- 通过依赖注入替换模型和服务；
- 长任务预留任务状态模型。

## 14. 常见误区

- 将所有逻辑写在 `main.py`。
- 前端直接依赖模型返回格式。
- 使用 HTTP `200` 返回所有错误。
- 生产环境允许任意 CORS 来源。
- 每个请求创建一次模型或数据库连接。
- 长任务一直占用同步 HTTP 请求，却没有超时和状态设计。
- 前后端分别修改接口，但没有契约测试。
- 只按目录区分前后端，没有建立职责边界。

## 15. 推荐落地顺序

1. 定义核心用户流程。
2. 设计请求、响应和错误契约。
3. 创建 FastAPI 路由与 Pydantic Schema。
4. 将业务流程放入服务层。
5. 使用依赖注入连接路由与服务。
6. 实现前端 API 客户端和状态机。
7. 配置 CORS 并完成本地联调。
8. 编写 API 测试和端到端验收。
9. 根据任务时长决定是否引入异步任务。
10. 再考虑认证、数据库和生产部署。

优秀的前后端分离设计，应让前端可以在后端使用假数据时独立开发，也让后端可以在没有界面的情况下通过 API 测试完整验证。
