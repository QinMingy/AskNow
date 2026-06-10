from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_live_microphone_ui_exposes_device_and_quality_controls():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    for element_id in (
        "microphoneSelect",
        "echoCancellationToggle",
        "noiseSuppressionToggle",
        "autoGainToggle",
        "audioQualityLabel",
        "audioLevelBar",
    ):
        assert f'id="{element_id}"' in html


def test_audio_worklet_uses_sinc_resampling_and_quality_metrics():
    worklet = (ROOT / "frontend" / "audio-worklet.js").read_text(encoding="utf-8")

    assert 'registerProcessor("classroom-audio-capture"' in worklet
    assert "sincResample" in worklet
    assert "measureAudio" in worklet
    assert 'event.data?.type === "flush"' in worklet


def test_frontend_prefers_audio_worklet_with_compatibility_fallback():
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "liveAudioContext.audioWorklet" in app
    assert "new AudioWorkletNode" in app
    assert "createScriptProcessor" in app
    assert "microphoneConstraints()" in app
