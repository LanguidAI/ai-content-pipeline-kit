"""竖版短视频的版式质检。

解决的问题：竖版（9:16）视频里如果横向图片并排摆放，每张图会被压到极小，
在手机上几乎不可读。这个错误在渲染阶段不会报错，只有人工看片才能发现，
因此必须在生成发布包之前用规则拦下来。
"""

from .core import (
    HORIZONTAL_ASPECT_THRESHOLD,
    FOCUS_LAYOUTS,
    MULTI_HORIZONTAL_LAYOUTS,
    aspect,
    horizontal_assets,
    assess_shot_layout,
)

__all__ = [
    "HORIZONTAL_ASPECT_THRESHOLD",
    "FOCUS_LAYOUTS",
    "MULTI_HORIZONTAL_LAYOUTS",
    "aspect",
    "horizontal_assets",
    "assess_shot_layout",
]
