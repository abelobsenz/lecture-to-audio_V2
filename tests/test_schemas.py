from app.schemas import LectureScript


def _build_script(axes):
    return LectureScript(
        title="Test Lecture",
        source_type="pdf",
        duration_estimate_sec=120,
        chapters=[
            {
                "name": "Chapter 1",
                "narration": "Narration",
                "spoken_math": [],
                "figure_narration": [
                    {
                        "figure_id": "fig-1",
                        "description": "A figure",
                        "chart_type": "line",
                        "axes": axes,
                        "trend": "upward",
                        "significance": "important",
                    }
                ],
            }
        ],
        final_recap="Recap",
    )


def test_figure_axes_dict_is_coerced_to_string():
    script = _build_script({"x": "Time (days)", "y": "Volatility (%)"})
    axes = script.chapters[0].figure_narration[0].axes
    assert axes == "x-axis: Time (days) y-axis: Volatility (%)"


def test_figure_axes_string_is_preserved():
    script = _build_script("x-axis: Time. y-axis: Price.")
    axes = script.chapters[0].figure_narration[0].axes
    assert axes == "x-axis: Time. y-axis: Price."
