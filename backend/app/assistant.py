from .schemas import AssistRequest, AssistResponse, TranscriptSegment


class UnderstandingAssistant:
    def assist(self, request: AssistRequest) -> AssistResponse:
        segments = self._select_window(request.segments, request.window_seconds)
        if not segments:
            return AssistResponse(
                action=request.action,
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

        return AssistResponse(
            action=request.action,
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
            title="会后行动项草稿",
            summary="系统从最近字幕中提取了可能需要跟进的内容。",
            bullets=bullets,
            caution="行动项需要用户确认后才能视为正式任务。",
        )
