from fastapi.testclient import TestClient

import pytest
import httpx

from app.assistant import (
    AssistProviderFactory,
    LiteLLMAssistProvider,
    OpenAICompatibleAssistProvider,
    RuleBasedAssistProvider,
    UnderstandingAssistant,
    action_instruction,
)
from app.main import app, get_understanding_assistant
from app.schemas import AssistRequest, TranscriptSegment


def sample_segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            id=1,
            start=0.0,
            end=18.0,
            speaker="Speaker A",
            text="我们需要先确认课堂助手的使用场景。",
        ),
        TranscriptSegment(
            id=2,
            start=18.0,
            end=42.0,
            speaker="Speaker B",
            text="我认为下一步应该先测试中文音频转写。",
        ),
        TranscriptSegment(
            id=3,
            start=42.0,
            end=70.0,
            speaker="Speaker A",
            text="然后再安排实时理解辅助功能。",
        ),
    ]


def test_explain_uses_recent_window():
    assistant = UnderstandingAssistant(RuleBasedAssistProvider())

    response = assistant.assist(
        AssistRequest(action="explain", segments=sample_segments(), window_seconds=30)
    )

    assert response.action == "explain"
    assert "最近 30 秒" in response.summary
    assert any("实时理解辅助" in bullet for bullet in response.bullets)
    assert not any("使用场景" in bullet for bullet in response.bullets)


def test_question_returns_user_confirmable_drafts():
    assistant = UnderstandingAssistant(RuleBasedAssistProvider())

    response = assistant.assist(
        AssistRequest(action="question", segments=sample_segments())
    )

    assert response.action == "question"
    assert len(response.bullets) == 3
    assert "由你决定" in response.caution


def test_actions_extracts_possible_followups():
    assistant = UnderstandingAssistant(RuleBasedAssistProvider())

    response = assistant.assist(
        AssistRequest(action="actions", segments=sample_segments())
    )

    assert any("下一步" in bullet for bullet in response.bullets)
    assert any("安排" in bullet for bullet in response.bullets)


def test_assist_api_returns_structured_result():
    app.dependency_overrides[get_understanding_assistant] = lambda: UnderstandingAssistant(
        RuleBasedAssistProvider()
    )
    client = TestClient(app)

    try:
        response = client.post(
            "/api/assist",
            json={
                "action": "catchup",
                "window_seconds": 180,
                "segments": [segment.model_dump() for segment in sample_segments()],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["action"] == "catchup"
    assert response.json()["provider"] == "rule_based"
    assert response.json()["title"] == "缺席补偿摘要"
    assert response.json()["bullets"]


def test_assist_api_rejects_unknown_action():
    client = TestClient(app)

    response = client.post(
        "/api/assist",
        json={"action": "speak-for-me", "segments": []},
    )

    assert response.status_code == 422


def test_provider_factory_creates_rule_provider():
    provider = AssistProviderFactory.create("rule-based")

    assert isinstance(provider, RuleBasedAssistProvider)


def test_provider_factory_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported assist provider"):
        AssistProviderFactory.create("unknown")


def test_openai_compatible_provider_converts_json_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        body = json_loads(request.content)
        seen["model"] = body["model"]
        seen["messages"] = body["messages"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"title":"LLM解释","summary":"这是模型生成的摘要",'
                                '"bullets":["要点一","要点二"],"caution":"请用户确认"}'
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleAssistProvider(
        base_url="http://127.0.0.1:11434/v1",
        model="qwen2.5:7b",
        api_key="local-key",
        client=client,
    )

    response = provider.assist(
        AssistRequest(action="explain", segments=sample_segments(), window_seconds=60)
    )

    assert response.provider == "openai_compatible"
    assert response.title == "LLM解释"
    assert response.bullets == ["要点一", "要点二"]
    assert seen["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert seen["auth"] == "Bearer local-key"
    assert seen["model"] == "qwen2.5:7b"
    assert seen["messages"][0]["role"] == "system"


def test_provider_factory_creates_openai_compatible_provider_with_config():
    provider = AssistProviderFactory.create(
        "local-llm",
        base_url="http://127.0.0.1:1234/v1",
        model="local-model",
    )

    assert isinstance(provider, OpenAICompatibleAssistProvider)


def test_litellm_provider_converts_json_response():
    seen = {}

    def fake_completion(**kwargs):
        seen.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"title":"LiteLLM解释","summary":"统一供应商输出",'
                            '"bullets":["统一接口","保留用户确认"],"caution":"仅供参考"}'
                        )
                    }
                }
            ]
        }

    provider = LiteLLMAssistProvider(
        model="openai/gpt-4o-mini",
        api_key="test-key",
        base_url="http://proxy.example/v1",
        completion_func=fake_completion,
    )

    response = provider.assist(
        AssistRequest(action="question", segments=sample_segments(), window_seconds=60)
    )

    assert response.provider == "litellm"
    assert response.title == "LiteLLM解释"
    assert response.bullets == ["统一接口", "保留用户确认"]
    assert seen["model"] == "openai/gpt-4o-mini"
    assert seen["api_key"] == "test-key"
    assert seen["api_base"] == "http://proxy.example/v1"
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["messages"][0]["role"] == "system"
    assert "辅助动作：question" in seen["messages"][1]["content"]
    assert "完整问题" in seen["messages"][1]["content"]


def test_provider_factory_creates_litellm_provider_with_config():
    provider = AssistProviderFactory.create(
        "litellm",
        base_url="http://proxy.example/v1",
        model="anthropic/claude-3-5-sonnet",
        api_key="test-key",
    )

    assert isinstance(provider, LiteLLMAssistProvider)


def test_action_instructions_are_distinct():
    assert "完整问题" in action_instruction("question")
    assert "行动项" in action_instruction("actions")
    assert "观点关系" in action_instruction("conflict")
    assert action_instruction("question") != action_instruction("actions")


def json_loads(content: bytes):
    import json

    return json.loads(content.decode("utf-8"))
