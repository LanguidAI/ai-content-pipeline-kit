import pytest

from acpk.layout_qa import aspect, horizontal_assets, assess_shot_layout

HORIZONTAL = {"asset_id": "a", "width": 1664, "height": 928}
VERTICAL = {"asset_id": "b", "width": 928, "height": 1664}


def test_rejects_two_horizontal_images_side_by_side():
    shot = {"assets": [HORIZONTAL, dict(HORIZONTAL, asset_id="c")], "layout": "side_by_side"}
    result = assess_shot_layout(shot)
    assert result["status"] == "failed"
    assert "must not be side-by-side" in result["reason"]


def test_allows_single_horizontal_image_focus():
    shot = {"assets": [HORIZONTAL], "layout": "horizontal_focus"}
    assert assess_shot_layout(shot)["status"] == "pass"


@pytest.mark.parametrize("layout", ["horizontal_focus", "full_width", "single"])
def test_all_focus_layouts_pass_with_one_horizontal(layout):
    assert assess_shot_layout({"assets": [HORIZONTAL], "layout": layout})["status"] == "pass"


@pytest.mark.parametrize("layout", ["stacked", "split_shots"])
def test_multi_horizontal_passes_when_stacked_or_split(layout):
    shot = {"assets": [HORIZONTAL, dict(HORIZONTAL, asset_id="c")], "layout": layout}
    assert assess_shot_layout(shot)["status"] == "pass"


def test_multi_horizontal_without_stacked_layout_needs_review():
    shot = {"assets": [HORIZONTAL, dict(HORIZONTAL, asset_id="c")], "layout": "grid"}
    assert assess_shot_layout(shot)["status"] == "needs_review"


def test_vertical_only_assets_always_pass():
    shot = {"assets": [VERTICAL, dict(VERTICAL, asset_id="c")], "layout": "side_by_side"}
    assert assess_shot_layout(shot)["status"] == "pass"


def test_missing_layout_key_does_not_raise():
    assert assess_shot_layout({"assets": [VERTICAL]})["status"] == "pass"


def test_missing_assets_key_does_not_raise():
    assert assess_shot_layout({"layout": "stacked"})["status"] == "pass"


def test_aspect_returns_zero_for_missing_or_invalid_dimensions():
    assert aspect({}) == 0.0
    assert aspect({"width": 0, "height": 100}) == 0.0
    assert aspect({"width": 100, "height": None}) == 0.0


def test_aspect_ratio_value():
    assert aspect(HORIZONTAL) == pytest.approx(1664 / 928)


def test_horizontal_assets_filters_by_threshold():
    # 宽高比 1.3 低于阈值 1.4，不应被判为横向图
    borderline = {"asset_id": "d", "width": 1300, "height": 1000}
    assert horizontal_assets({"assets": [borderline]}) == []
    assert horizontal_assets({"assets": [HORIZONTAL, VERTICAL]}) == [HORIZONTAL]
