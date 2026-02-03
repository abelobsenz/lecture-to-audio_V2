from app.chunking import build_context_text


def test_context_window_selects_prior_chunks():
    chunks = [
        {"chunk_id": 0, "approx_seconds": 10, "text": "alpha"},
        {"chunk_id": 1, "approx_seconds": 12, "text": "bravo"},
        {"chunk_id": 2, "approx_seconds": 8, "text": "charlie"},
        {"chunk_id": 3, "approx_seconds": 15, "text": "delta"},
    ]
    context_text, approx_seconds = build_context_text(chunks, index=3, window_seconds=20)
    assert context_text == "bravo\ncharlie"
    assert approx_seconds == 20


def test_context_window_empty_when_first_chunk():
    chunks = [
        {"chunk_id": 0, "approx_seconds": 10, "text": "alpha"},
    ]
    context_text, approx_seconds = build_context_text(chunks, index=0, window_seconds=30)
    assert context_text == ""
    assert approx_seconds == 0
