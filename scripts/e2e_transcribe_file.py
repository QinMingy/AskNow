import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/e2e_transcribe_file.py <audio-file>")
        return 2

    audio_path = Path(sys.argv[1]).resolve()
    if not audio_path.exists():
        print(f"Audio file not found: {audio_path}")
        return 2

    client = TestClient(app)
    with audio_path.open("rb") as audio_file:
        response = client.post(
            "/api/transcribe",
            files={"file": (audio_path.name, audio_file, "audio/wav")},
        )

    if response.status_code != 200:
        print(f"Transcription request failed: HTTP {response.status_code}")
        print(response.text)
        return 1

    result = response.json()
    segments = result.get("segments") or []
    if not segments:
        print("Transcription returned no segments.")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    output_dir = ROOT / "transcripts"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "phase1_e2e_result.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Phase 1 E2E transcription passed: {len(segments)} segment(s)")
    print(f"Result saved to: {output_path}")
    print("Preview:")
    for segment in segments[:3]:
        print(f"- [{segment['start']:.2f}-{segment['end']:.2f}] {segment['speaker']}: {segment['text']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
