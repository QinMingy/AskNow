from fastapi.testclient import TestClient

from app.assistant import UnderstandingAssistant
from app.main import app
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
    assistant = UnderstandingAssistant()

    response = assistant.assist(
        AssistRequest(action="explain", segments=sample_segments(), window_seconds=30)
    )

    assert response.action == "explain"
    assert "最近 30 秒" in response.summary
    assert any("实时理解辅助" in bullet for bullet in response.bullets)
    assert not any("使用场景" in bullet for bullet in response.bullets)


def test_question_returns_user_confirmable_drafts():
    assistant = UnderstandingAssistant()

    response = assistant.assist(
        AssistRequest(action="question", segments=sample_segments())
    )

    assert response.action == "question"
    assert len(response.bullets) == 3
    assert "由你决定" in response.caution


def test_actions_extracts_possible_followups():
    assistant = UnderstandingAssistant()

    response = assistant.assist(
        AssistRequest(action="actions", segments=sample_segments())
    )

    assert any("下一步" in bullet for bullet in response.bullets)
    assert any("安排" in bullet for bullet in response.bullets)


def test_assist_api_returns_structured_result():
    client = TestClient(app)

    response = client.post(
        "/api/assist",
        json={
            "action": "catchup",
            "window_seconds": 180,
            "segments": [segment.model_dump() for segment in sample_segments()],
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "catchup"
    assert response.json()["title"] == "缺席补偿摘要"
    assert response.json()["bullets"]


def test_assist_api_rejects_unknown_action():
    client = TestClient(app)

    response = client.post(
        "/api/assist",
        json={"action": "speak-for-me", "segments": []},
    )

    assert response.status_code == 422
