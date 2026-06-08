# Real-Time Comprehension Accessibility Assistant

课堂/会议中的实时理解无障碍助手第一阶段 Demo。

这个项目不是普通会议纪要工具。第一阶段先完成一个本地 Web Demo：上传课堂/会议录音，或粘贴 B 站、YouTube 视频链接后，系统使用本地 `faster-whisper` 进行转写，并在三栏界面里展示字幕、时间戳、模拟说话人和后续 AI 辅助入口。

## 项目结构

```text
.
├── backend/          # FastAPI + faster-whisper 转写服务
│   └── app/sources/  # 可拓展的视频来源解析器
├── docs/             # 项目文档
├── frontend/         # 无构建静态前端，不需要 npm
├── samples/          # 本地测试音频，默认不纳入 git
├── scripts/          # 环境检查脚本
├── PHASE_1_PLAN.md   # 第一阶段细化计划
└── README.md
```

## 后端运行

第一阶段默认使用 Windows 本机 GPU，要求 CUDA 可用。后端不会静默降级到 CPU；如果 CUDA 不可用，接口会返回清晰错误。

## 一键启动/关闭

推荐直接使用根目录下的批处理脚本：

```powershell
cd C:\Users\qinmy\Documents\WhisperProject
.\start_demo.bat
```

启动后会打开两个终端窗口：

- 后端：`http://127.0.0.1:8010`
- 前端：`http://127.0.0.1:5173`

关闭两个服务：

```powershell
cd C:\Users\qinmy\Documents\WhisperProject
.\stop_demo.bat
```

关闭脚本会按端口停止 `8010`、`8000` 和 `5173` 上的监听进程。`8000` 是旧版兼容清理端口。

## 手动运行后端

```powershell
cd C:\Users\qinmy\Documents\WhisperProject\backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

如果需要重新安装后端依赖：

```powershell
cd C:\Users\qinmy\Documents\WhisperProject\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/health
```

后端测试：

```powershell
cd C:\Users\qinmy\Documents\WhisperProject\backend
.\.venv\Scripts\python.exe -m pytest
```

## 前端运行

前端已经改成无构建静态页面，不需要 Node.js、npm、Vite 或 React。

```powershell
cd C:\Users\qinmy\Documents\WhisperProject\frontend
python -m http.server 5173 --bind 127.0.0.1
```

然后打开：

```text
http://127.0.0.1:5173
```

注意：不要直接双击打开 `index.html` 做正式联调。用上面的本地静态服务器启动，可以避免浏览器跨域和文件协议带来的小问题。

## 第一阶段能力

- 上传 `.mp3`、`.wav`、`.m4a`、`.mp4`
- 粘贴 B 站或 YouTube 视频链接并转写
- 本地 `faster-whisper` 转写
- 统一转写 JSON 结构
- 三栏式课堂助手界面
- 带时间戳字幕流
- 模拟 `Speaker A/B`
- 当前讨论焦点占位摘要
- AI 辅助按钮占位
- 前端不依赖 npm，启动更轻

## 视频来源拓展

链接输入走后端的可插拔来源解析架构：

```text
POST /api/transcribe-url
        ↓
SourceRegistry
        ↓
SourceResolver，例如 YtDlpSourceResolver
        ↓
本地媒体文件
        ↓
WhisperTranscriber
```

当前内置来源：

- YouTube：`youtube.com`、`youtu.be`
- Bilibili：`bilibili.com`、`b23.tv`

后续新增视频来源时，在 `backend/app/sources/` 下新增一个 resolver，实现：

- `supports(url: str) -> bool`
- `resolve(url: str, output_dir: Path) -> ResolvedMedia`

然后在 `backend/app/sources/__init__.py` 的 `create_default_registry()` 里注册即可，不需要修改转写接口或前端调用方式。

注意：部分 B 站或 YouTube 视频可能需要登录、cookies 或网络访问权限，`yt-dlp` 无法下载时后端会返回清晰错误。

### B 站 HTTP 412 / 需要登录态时

B 站有时会对非浏览器请求返回 `HTTP Error 412: Precondition Failed`。后端已经默认给 `yt-dlp` 加了浏览器 User-Agent、中文 `Accept-Language` 和 B 站 Referer。

如果仍然失败，在前端“视频链接”模式中选择一个已经登录 B 站的浏览器，再点击“解析并转写”。后端会通过 `yt-dlp` 直接读取该浏览器的本地登录态，不需要用户导出 cookies 文件。

建议顺序：

1. 匿名下载
2. Firefox 登录态，Windows 下通常更稳定
3. Edge 或 Chrome 登录态；如果浏览器正在运行导致 cookie 数据库被锁定，可以完全关闭浏览器后重试
4. 稍后再试；B 站也可能临时限制当前 IP，此时 cookies 不一定能解决

对于自动化部署或高级用户，仍可以选择通过环境变量指定 Netscape 格式 cookies 文件：

```powershell
$env:YTDLP_COOKIES_FILE="C:\Users\qinmy\Documents\WhisperProject\cookies.txt"
cd C:\Users\qinmy\Documents\WhisperProject
.\start_demo.bat
```

也可以自定义下载请求的 User-Agent：

```powershell
$env:YTDLP_USER_AGENT="Mozilla/5.0 ..."
```

不要把 `cookies.txt` 提交到 git。它包含你的登录态。普通桌面使用不需要创建这个文件。

## 第一阶段暂不包含

- 实时麦克风输入
- 真正说话人分离
- LLM 解释和提问生成
- 用户登录
- 数据库
- 云端部署
- 永久保存会议记录

## 环境检查

仓库提供一个轻量检查脚本，用于确认 Python、后端依赖和 CUDA 相关环境是否准备好：

```powershell
cd C:\Users\qinmy\Documents\WhisperProject
backend\.venv\Scripts\python.exe scripts\check_environment.py
```
