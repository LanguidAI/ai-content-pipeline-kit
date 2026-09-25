"""竖版短视频版式判定规则。

三态返回值的设计意图：质检闸门不允许只有「通过 / 不通过」。
`needs_review` 表示规则无法确定对错、必须交人工判断的情况——
把它静默判为 pass 会放过问题，判为 failed 会误杀正常内容。
"""

from __future__ import annotations

from typing import Any

# 宽高比达到该值即视为「横向图片」。取 1.4 而非 16/9≈1.78，
# 是因为实拍截图和图表常落在 1.4~1.7 之间，用 16/9 会漏判。
HORIZONTAL_ASPECT_THRESHOLD = 1.4

# 只有一张横向图片时，这些版式是合理的：让它占据主要视觉区域。
FOCUS_LAYOUTS = frozenset({"horizontal_focus", "full_width", "single"})

# 有多张横向图片时，只有这些版式能避免并排压缩。
MULTI_HORIZONTAL_LAYOUTS = frozenset({"stacked", "split_shots"})


def aspect(asset: dict[str, Any]) -> float:
    """返回素材宽高比；尺寸缺失或非法时返回 0.0 而不是抛异常。

    返回 0.0 是有意的：上游数据经常缺 width/height，抛异常会中断整条产线，
    而 0.0 会让该素材被当作非横向图处理——最坏情况是少拦一条，
    不会让当天所有发布包都生产失败。
    """
    width = float(asset.get("width") or 0)
    height = float(asset.get("height") or 0)
    if width <= 0 or height <= 0:
        return 0.0
    return width / height


def horizontal_assets(shot: dict[str, Any]) -> list[dict[str, Any]]:
    """筛出一个分镜里的横向图片素材。"""
    return [
        asset
        for asset in shot.get("assets") or []
        if aspect(asset) >= HORIZONTAL_ASPECT_THRESHOLD
    ]


def assess_shot_layout(shot: dict[str, Any]) -> dict[str, str]:
    """判定单个分镜的版式是否适合竖版视频。

    返回 `{"status": "pass" | "failed" | "needs_review", "reason": str}`。
    `reason` 用英文，以便直接写进机器可读的质检报告。
    """
    layout = str(shot.get("layout") or "").strip()
    horizontals = horizontal_assets(shot)

    # 两张以上横向图并排是确定的错误，直接拦死，不留人工复核余地。
    if layout == "side_by_side" and len(horizontals) >= 2:
        return {
            "status": "failed",
            "reason": (
                "horizontal images must not be side-by-side in vertical video; "
                "use stacked layout or split into separate shots"
            ),
        }

    if len(horizontals) == 1 and layout in FOCUS_LAYOUTS:
        return {"status": "pass", "reason": "single horizontal image uses focus layout"}

    # 多张横向图但没有采用堆叠/拆分版式：可能是数据缺失，也可能是真错，
    # 规则无法区分，交人工。
    if len(horizontals) >= 2 and layout not in MULTI_HORIZONTAL_LAYOUTS:
        return {
            "status": "needs_review",
            "reason": "multiple horizontal images require stacked layout or separate shots",
        }

    return {"status": "pass", "reason": "layout accepted"}
