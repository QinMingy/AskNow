import json
import logging
import time
from typing import Protocol

import httpx

from .schemas import AssistRequest, AssistResponse, TranscriptSegment

logger = logging.getLogger(__name__)


class AssistProvider(Protocol):
    name: str

    def assist(self, request: AssistRequest) -> AssistResponse:
        """Return an assistive response from a transcript context."""


class RuleBasedAssistProvider:
    name = "rule_based"

    def assist(self, request: AssistRequest) -> AssistResponse:
        segments = self._select_window(request.segments, request.window_seconds)
        if not segments:
            return AssistResponse(
                action=request.action,
                provider=self.name,
                title="还没有可用上下文",
                summary="请先完成一次音频或视频转写，再使用参与辅助。",
                bullets=["上传或解析音频后，系统会基于最近的字幕片段生成辅助内容。"],
                caution="AI 只提供辅助草稿，是否采用仍由你决定。",
            )

        if request.action == "explain":
            return self._explain(request, segments)
        if request.action == "conflict":
            return self._conflict(request, segments)
        if request.action == "question":
            return self._question(request, segments)
        if request.action == "catchup":
            return self._catchup(request, segments)
        if request.action == "actions":
            return self._actions(request, segments)
        if request.action == "custom":
            return self._custom(request, segments)

        return AssistResponse(
            action=request.action,
            provider=self.name,
            title="暂不支持的辅助类型",
            summary="当前版本还没有实现这个辅助动作。",
            bullets=[],
            caution="请更新前端或后端到匹配版本。",
        )

    @staticmethod
    def _select_window(
        segments: list[TranscriptSegment],
        window_seconds: int,
    ) -> list[TranscriptSegment]:
        if not segments:
            return []

        latest_end = max(segment.end for segment in segments)
        window_start = max(0.0, latest_end - max(10, window_seconds))
        selected = [segment for segment in segments if segment.end >= window_start]
        return selected or segments[-3:]

    @staticmethod
    def _join_text(segments: list[TranscriptSegment], max_chars: int = 220) -> str:
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars].rstrip()}..."

    @staticmethod
    def _speaker_lines(segments: list[TranscriptSegment], limit: int = 4) -> list[str]:
        return [
            f"{segment.speaker}: {segment.text.strip()}"
            for segment in segments[-limit:]
            if segment.text.strip()
        ]

    def _explain(
        self,
        request: AssistRequest,
        segments: list[TranscriptSegment],
    ) -> AssistResponse:
        return AssistResponse(
            action=request.action,
            provider=self.name,
            title="刚刚发生了什么",
            summary=f"最近 {request.window_seconds} 秒主要围绕这段内容展开：{self._join_text(segments)}",
            bullets=self._speaker_lines(segments),
            caution="这是基于字幕窗口的快速解释，不等同于完整会议纪要。",
        )

    def _conflict(
        self,
        request: AssistRequest,
        segments: list[TranscriptSegment],
    ) -> AssistResponse:
        if any(segment.speaker == "Speaker pending" for segment in segments):
            return AssistResponse(
                action=request.action,
                provider=self.name,
                title="观点关系暂待确认",
                summary=(
                    "实时字幕尚未完成说话人分离，因此现在不能可靠判断谁支持或反对谁。"
                ),
                bullets=self._speaker_lines(segments, limit=6),
                caution="请先根据内容理解观点；人物归属需等待说话人修订后确认。",
            )
        speakers = []
        for segment in segments:
            if segment.speaker not in speakers:
                speakers.append(segment.speaker)

        bullets = self._speaker_lines(segments, limit=6)
        if len(speakers) >= 2:
            summary = (
                f"最近窗口里出现了 {', '.join(speakers[:3])} 的连续发言。"
                " 第一阶段还没有真正判断立场，只先把可能相关的发言并排列出。"
            )
        else:
            summary = "最近窗口里主要是单一说话人发言，暂时看不出明确的反对关系。"

        return AssistResponse(
            action=request.action,
            provider=self.name,
            title="观点关系梳理",
            summary=summary,
            bullets=bullets,
            caution="当前版本不自动判定谁反对谁，避免把讨论误读成冲突。",
        )

    def _question(
        self,
        request: AssistRequest,
        segments: list[TranscriptSegment],
    ) -> AssistResponse:
        context = self._join_text(segments, max_chars=120)
        return AssistResponse(
            action=request.action,
            provider=self.name,
            title="可以这样追问",
            summary="下面是几种比较安全的课堂/会议追问方式，适合由你确认后再表达。",
            bullets=[
                f"我想确认一下，刚才这部分是不是主要在说：{context}",
                "这个结论成立时，最关键的前提条件是什么？",
                "如果换一个例子或场景，这个判断还适用吗？",
            ],
            caution="建议只把它当作提问草稿，最终语气和内容由你决定。",
        )

    def _catchup(
        self,
        request: AssistRequest,
        segments: list[TranscriptSegment],
    ) -> AssistResponse:
        return AssistResponse(
            action=request.action,
            provider=self.name,
            title="缺席补偿摘要",
            summary=f"你离开期间可以先抓住这一条主线：{self._join_text(segments)}",
            bullets=[
                f"时间范围：约 {segments[0].start:.0f}s 到 {segments[-1].end:.0f}s。",
                f"涉及说话人：{', '.join(sorted({segment.speaker for segment in segments}))}。",
                "建议先看最后两条字幕，再决定是否需要打断提问。",
            ],
            caution="补偿摘要会压缩细节，关键决策仍建议回看原字幕。",
        )

    def _actions(
        self,
        request: AssistRequest,
        segments: list[TranscriptSegment],
    ) -> AssistResponse:
        keywords = ("需要", "应该", "负责", "下一步", "作业", "提交", "确认", "安排")
        candidates = [
            segment.text.strip()
            for segment in segments
            if any(keyword in segment.text for keyword in keywords)
        ]
        bullets = candidates[:5] or [
            "暂未识别到明确行动项。",
            "可以会后人工确认是否有作业、负责人或截止时间。",
        ]

        return AssistResponse(
            action=request.action,
            provider=self.name,
            title="会后行动项草稿",
            summary="系统从最近字幕中提取了可能需要跟进的内容。",
            bullets=bullets,
            caution="行动项需要用户确认后才能视为正式任务。",
        )

    def _custom(
        self,
        request: AssistRequest,
        segments: list[TranscriptSegment],
    ) -> AssistResponse:
        prompt = (request.custom_prompt or "").strip()
        return AssistResponse(
            action=request.action,
            provider=self.name,
            title="自定义问题参考",
            summary=f"你想了解的是：{prompt or '未提供具体问题'}",
            bullets=[
                f"最近讨论上下文：{self._join_text(segments)}",
                "规则模式只能提供上下文摘录；使用 LiteLLM 时会针对你的问题生成回答。",
            ],
            caution="请结合原始字幕确认答案，避免遗漏上下文。",
        )


class OpenAICompatibleAssistProvider:
    name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ):
        if not base_url.strip():
            raise ValueError("ASSIST_BASE_URL is required for the openai_compatible provider.")
        if not model.strip():
            raise ValueError("ASSIST_MODEL is required for the openai_compatible provider.")

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.client = client or httpx.Client(timeout=timeout_seconds)

    def assist(self, request: AssistRequest) -> AssistResponse:
        started = time.perf_counter()
        logger.info(
            "llm.inference.start provider=%s model=%s action=%s segments=%s",
            self.name,
            self.model,
            request.action,
            len(request.segments),
        )
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={
                    "model": self.model,
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": self._system_prompt(),
                        },
                        {
                            "role": "user",
                            "content": self._user_prompt(request),
                        },
                    ],
                },
            )
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            result = build_llm_assist_response(request, self.name, content)
        except Exception:
            logger.exception("llm.inference.failed provider=%s model=%s", self.name, self.model)
            raise
        logger.info(
            "llm.inference.complete provider=%s model=%s elapsed_ms=%.1f",
            self.name,
            self.model,
            (time.perf_counter() - started) * 1000,
        )
        return result

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是课堂和会议中的实时理解无障碍助手。"
            "你只帮助用户理解上下文和准备表达，不替用户发言，也不把讨论自动判定为冲突。"
            "你必须严格根据用户给出的 action 类型生成不同风格的结果，不能对所有 action 使用同一种总结模板。"
            "请仅返回 JSON 对象，字段为 title、summary、bullets、caution；bullets 必须是字符串数组。"
            "title 必须明确体现当前 action 的任务类型。"
        )

    @staticmethod
    def _user_prompt(request: AssistRequest) -> str:
        lines = [
            f"[{segment.start:.2f}-{segment.end:.2f}] {segment.speaker}: {segment.text}"
            for segment in request.segments
        ]
        return (
            f"辅助动作：{request.action}\n"
            f"动作说明：{action_instruction(request.action)}\n"
            f"用户自定义问题：{request.custom_prompt or '无'}\n"
            f"上下文窗口：最近 {request.window_seconds} 秒\n"
            "输出要求：\n"
            "- 不要重复字幕原文作为唯一结果。\n"
            "- 不要替用户发言，只给用户可确认的理解或表达草稿。\n"
            "- bullets 应该服务于当前 action，而不是泛泛总结。\n"
            "- Speaker pending 表示尚未完成说话人识别，禁止据此判断谁支持或反对谁。\n"
            "字幕：\n"
            + "\n".join(lines)
        )


class LiteLLMAssistProvider:
    name = "litellm"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 60.0,
        completion_func=None,
    ):
        if not model.strip():
            raise ValueError("ASSIST_MODEL is required for the litellm provider.")

        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") if base_url else None
        self.timeout_seconds = timeout_seconds
        self.completion_func = completion_func

    def assist(self, request: AssistRequest) -> AssistResponse:
        started = time.perf_counter()
        logger.info(
            "llm.inference.start provider=%s model=%s action=%s segments=%s",
            self.name,
            self.model,
            request.action,
            len(request.segments),
        )
        completion = self.completion_func or self._load_completion()
        kwargs = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": OpenAICompatibleAssistProvider._system_prompt(),
                },
                {
                    "role": "user",
                    "content": OpenAICompatibleAssistProvider._user_prompt(request),
                },
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "timeout": self.timeout_seconds,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            kwargs["api_base"] = self.base_url

        try:
            response = completion(**kwargs)
            content = extract_chat_content(response)
            result = build_llm_assist_response(request, self.name, content)
        except Exception:
            logger.exception("llm.inference.failed provider=%s model=%s", self.name, self.model)
            raise
        logger.info(
            "llm.inference.complete provider=%s model=%s elapsed_ms=%.1f",
            self.name,
            self.model,
            (time.perf_counter() - started) * 1000,
        )
        return result

    @staticmethod
    def _load_completion():
        try:
            from litellm import completion
        except ImportError as exc:
            raise RuntimeError(
                "LiteLLM is not installed. Run `pip install -r backend/requirements.txt` "
                "inside the whisperproject environment."
            ) from exc
        return completion


def extract_chat_content(response) -> str:
    if isinstance(response, dict):
        return response["choices"][0]["message"]["content"]

    choice = response.choices[0]
    message = choice.message
    return message["content"] if isinstance(message, dict) else message.content


def build_llm_assist_response(
    request: AssistRequest,
    provider_name: str,
    content: str,
) -> AssistResponse:
    result = _parse_llm_json_object(content)
    title = str(result.get("title", "")).strip()
    summary = str(result.get("summary", "")).strip()
    bullets = result.get("bullets", [])
    if not title or not summary:
        raise ValueError("LLM assist response must include non-empty title and summary.")
    if not isinstance(bullets, list):
        raise ValueError("LLM assist response bullets must be a JSON array.")

    return AssistResponse(
        action=request.action,
        provider=provider_name,
        title=title,
        summary=summary,
        bullets=[str(item) for item in bullets],
        caution=str(
            result.get(
                "caution",
                "这是 AI 生成的辅助草稿，是否采用仍由你决定。",
            )
        ),
    )


def _parse_llm_json_object(content: str) -> dict:
    normalized = content.strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        normalized = "\n".join(lines).strip()

    object_start = normalized.find("{")
    if object_start < 0:
        raise ValueError("LLM assist response did not contain a JSON object.")
    try:
        result, _ = json.JSONDecoder().raw_decode(normalized[object_start:])
    except json.JSONDecodeError as exc:
        raise ValueError("LLM assist response contained invalid JSON.") from exc
    if not isinstance(result, dict):
        raise ValueError("LLM assist response must be a JSON object.")
    return result


def action_instruction(action: str) -> str:
    instructions = {
        "explain": (
            "解释最近讨论发生了什么。summary 用通俗语言讲清主线；"
            "bullets 列出 3-5 个关键点，帮助听漏的人补上理解。"
        ),
        "conflict": (
            "梳理观点关系。不要武断判断冲突；如果没有明确反对关系，要说明只能看到发言差异。"
            "bullets 按说话人或观点列出可能的支持、疑问、分歧点。"
        ),
        "question": (
            "生成用户可以亲自提出的追问。summary 简短说明提问策略；"
            "bullets 必须是 2-3 个完整问题，语气自然、克制、适合课堂或会议。"
        ),
        "catchup": (
            "生成缺席补偿摘要。summary 先给一句主线；"
            "bullets 包含时间范围、关键变化、现在应该先关注什么。"
        ),
        "actions": (
            "提取会后行动项草稿。summary 说明是否发现明确任务；"
            "bullets 尽量写成待办项，包含任务、负责人、截止时间；缺失信息要标注待确认。"
        ),
        "custom": (
            "直接回答用户自定义问题。必须基于字幕上下文，无法确定时明确说明；"
            "summary 给出简洁答案，bullets 列出支撑答案的上下文依据。"
        ),
    }
    return instructions.get(action, "根据字幕上下文生成辅助理解内容。")


class AssistProviderFactory:
    @staticmethod
    def create(
        provider_name: str,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> AssistProvider:
        normalized = provider_name.strip().lower().replace("-", "_")
        if normalized in {"rule", "rules", "rule_based", "rulebased"}:
            return RuleBasedAssistProvider()
        if normalized in {"openai", "openai_compatible", "local_llm", "llm"}:
            return OpenAICompatibleAssistProvider(
                base_url=base_url or "",
                model=model or "",
                api_key=api_key,
                timeout_seconds=timeout_seconds,
                client=client,
            )
        if normalized in {"litellm", "lite_llm"}:
            return LiteLLMAssistProvider(
                base_url=base_url,
                model=model or "",
                api_key=api_key,
                timeout_seconds=timeout_seconds,
            )
        raise ValueError(f"Unsupported assist provider: {provider_name}")


class UnderstandingAssistant:
    def __init__(
        self,
        provider: AssistProvider,
        fallback_provider: AssistProvider | None = None,
    ):
        self.provider = provider
        self.fallback_provider = (
            fallback_provider
            if fallback_provider is not None
            else (
                None
                if provider.name == RuleBasedAssistProvider.name
                else RuleBasedAssistProvider()
            )
        )

    def assist(self, request: AssistRequest) -> AssistResponse:
        started = time.perf_counter()
        logger.info(
            "assist.start provider=%s action=%s segments=%s window_seconds=%s",
            self.provider.name,
            request.action,
            len(request.segments),
            request.window_seconds,
        )
        try:
            response = self.provider.assist(request)
        except Exception:
            logger.exception(
                "assist.failed provider=%s action=%s",
                self.provider.name,
                request.action,
            )
            if self.fallback_provider is None:
                raise
            logger.warning(
                "assist.fallback primary_provider=%s fallback_provider=%s action=%s",
                self.provider.name,
                self.fallback_provider.name,
                request.action,
            )
            response = self.fallback_provider.assist(request)
        logger.info(
            "assist.complete provider=%s action=%s elapsed_ms=%.1f",
            response.provider,
            request.action,
            (time.perf_counter() - started) * 1000,
        )
        return response
