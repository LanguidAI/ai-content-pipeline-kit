"""音视频质量闸门的阈值配置。

这些数字全部来自一条真实跑了一年多的自动视频产线的踩坑记录：
每一个默认值背后都有一次「程序说成功了、人去听/去看才发现不对」的事故。
阈值外置成配置，是因为平台音色、TTS 供应商、BGM 素材都会换，
换一次就可能要调一次数字，不该为此改代码。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

# 口播倍速上限。TTS 原文太长时产线会加速压缩到卡片时长内，
# 实测超过 1.35 倍开始明显失真（吞字、机械感），听众会直接划走。
DEFAULT_MAX_VOICEOVER_SPEED = 1.35

# 合成时为卡片尾部预留的呼吸时间（秒）。口播不会顶满卡片时长，
# 留一点尾巴避免「话音刚落就切卡」的急促感。
DEFAULT_SPEECH_TAIL_RESERVE_SECONDS = 0.18

# 单卡尾部静音上限（秒）。口播比卡片短太多时，ffmpeg 会用静音补位，
# 观众听到的是「念完了还在停」；实测单卡超过 1.5s 停顿就有拖沓感。
DEFAULT_MAX_TAIL_SILENCE_SECONDS = 1.5

# 全片静音占比上限。短包（30~40s）对死空气更敏感，
# 实测死空气占比 >10% 时整片节奏明显发散。
DEFAULT_MAX_TAIL_SILENCE_RATIO = 0.10

# BGM 音量（dB）允许区间。混音库的默认值是 -23，直接用它等于没做判断：
# 实测 -18~-22 才压得住口播又不抢戏，0dB 则完全盖住人声。
# 区间下沿取 -22，就是为了把「照抄默认值 -23」拦在门外。
DEFAULT_BGM_VOLUME_DB_RANGE = (-22.0, -14.0)

# 成片响度均值（dB）允许区间。口播轨统一 loudnorm I=-18，
# 混入 BGM 后实测落在 -20~-22；均值高于 -16 说明 BGM 或口播过响。
DEFAULT_LOUDNESS_MEAN_DB_RANGE = (-24.0, -16.0)

# 成片峰值（dB）上限。loudnorm 目标 TP=-2，峰值高于 -1 说明
# 混音链路上有环节 bypass 了限峰，发布后平台二次压缩会破音。
DEFAULT_LOUDNESS_MAX_DB_CEILING = -1.0

# TTS 参数必须整套继承的字段。换音色/换包时漏一个就会漂移：
# 漏 rate 语速变、漏 volume 响度变、漏 pitch 像换了一个人。
DEFAULT_REQUIRED_TTS_FIELDS = ("provider", "model", "voice", "rate", "volume", "pitch")

# 状态机字面量。与产线发布包 JSON 的字段取值保持一致。
STATUS_READY = "ready_to_publish"
AUDIO_PASSED = "audio_passed"
QA_PASSED = "video_qa_passed"
AUDIO_PENDING = "needs_manual_audio_review"


@dataclass(frozen=True)
class MediaQaConfig:
    """音视频质量闸门的全部阈值。"""

    max_voiceover_speed: float = DEFAULT_MAX_VOICEOVER_SPEED
    speech_tail_reserve_seconds: float = DEFAULT_SPEECH_TAIL_RESERVE_SECONDS
    max_tail_silence_seconds: float = DEFAULT_MAX_TAIL_SILENCE_SECONDS
    max_tail_silence_ratio: float = DEFAULT_MAX_TAIL_SILENCE_RATIO
    bgm_volume_db_range: tuple[float, float] = DEFAULT_BGM_VOLUME_DB_RANGE
    loudness_mean_db_range: tuple[float, float] = DEFAULT_LOUDNESS_MEAN_DB_RANGE
    loudness_max_db_ceiling: float = DEFAULT_LOUDNESS_MAX_DB_CEILING
    required_tts_fields: tuple[str, ...] = DEFAULT_REQUIRED_TTS_FIELDS


DEFAULT_CONFIG = MediaQaConfig()


def config_from_dict(data: Mapping[str, Any]) -> MediaQaConfig:
    """用字典覆盖默认阈值；未给的字段保持默认。"""
    kwargs: dict[str, Any] = {}
    for field_name in (
        "max_voiceover_speed",
        "speech_tail_reserve_seconds",
        "max_tail_silence_seconds",
        "max_tail_silence_ratio",
        "loudness_max_db_ceiling",
    ):
        if field_name in data:
            kwargs[field_name] = float(data[field_name])
    for range_name in ("bgm_volume_db_range", "loudness_mean_db_range"):
        if range_name in data:
            low, high = data[range_name]
            kwargs[range_name] = (float(low), float(high))
    if "required_tts_fields" in data:
        kwargs["required_tts_fields"] = tuple(data["required_tts_fields"])
    return MediaQaConfig(**kwargs)


def config_from_json(path: str | Path) -> MediaQaConfig:
    return config_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
