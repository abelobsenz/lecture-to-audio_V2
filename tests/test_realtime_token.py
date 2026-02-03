from fastapi.testclient import TestClient

from app.config import settings
from app.db import Lecture, LectureStatus, get_engine, get_session, init_db
from app.main import app


def test_realtime_token_response_shape(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    test_engine = get_engine(f"sqlite:///{db_path}")
    init_db(test_engine)

    monkeypatch.setattr("app.main.engine", test_engine)
    monkeypatch.setattr("app.main.worker.start", lambda: None)

    async def _noop():
        return None

    monkeypatch.setattr("app.main.worker.stop", _noop)
    settings.openai_api_key = "test-key"

    chunks_path = tmp_path / "chunks.json"
    chunks_path.write_text(
        '[{"chunk_id": 0, "approx_seconds": 10, "text": "hello"}]', encoding="utf-8"
    )

    with get_session(test_engine) as session:
        lecture = Lecture(
            id="lecture1",
            title="Test Lecture",
            source_filename="test.pdf",
            status=LectureStatus.done,
            lecture_script_json_path=str(tmp_path / "script.json"),
            chunks_json_path=str(chunks_path),
        )
        session.add(lecture)
        session.commit()

    def fake_mint(*_args, **_kwargs):
        return {"value": "abc123", "expires_at": 1234567890}

    monkeypatch.setattr("app.main.mint_realtime_client_secret", fake_mint)

    client = TestClient(app)
    response = client.post("/lectures/lecture1/realtime-token")
    assert response.status_code == 200
    data = response.json()
    assert data["client_secret"]["value"] == "abc123"
    assert data["client_secret"]["expires_at"] == 1234567890
    assert data["lecture_id"] == "lecture1"
    assert data["realtime_model"] == settings.openai_realtime_model
    assert data["voice"] == settings.openai_realtime_voice
