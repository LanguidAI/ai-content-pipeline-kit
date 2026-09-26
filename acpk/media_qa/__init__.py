"""音视频质量闸门：口播倍速、尾部静音、混音证明、响度、TTS 参数继承、发布总闸。

解决的核心问题：自动产线的音视频步骤「永远成功」——渲染退出码 0、
文件存在、时长正确，但口播可能失真、BGM 可能没混进去、没人听过的片子
可能被直接发布。这里的每道闸门都要求给出「能发现静默失败」的证据。
"""

from .checks import (
    audio_mix_proven,
    bgm_volume_report,
    finalize_states,
    loudness_report,
    pcm_sha256,
    publish_gate,
    speed_violations,
    speech_target_seconds,
    tail_silence_report,
    tts_param_drift,
    voiceover_speed,
)
from .config import (
    AUDIO_PASSED,
    AUDIO_PENDING,
    DEFAULT_CONFIG,
    QA_PASSED,
    STATUS_READY,
    MediaQaConfig,
    config_from_dict,
    config_from_json,
)

__all__ = [
    "audio_mix_proven",
    "bgm_volume_report",
    "finalize_states",
    "loudness_report",
    "pcm_sha256",
    "publish_gate",
    "speed_violations",
    "speech_target_seconds",
    "tail_silence_report",
    "tts_param_drift",
    "voiceover_speed",
    "AUDIO_PASSED",
    "AUDIO_PENDING",
    "DEFAULT_CONFIG",
    "QA_PASSED",
    "STATUS_READY",
    "MediaQaConfig",
    "config_from_dict",
    "config_from_json",
]
