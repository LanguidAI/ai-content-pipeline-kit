"""五道音视频质量闸门。

共同前提：自动化产线里「程序永远能给你成品」。渲染退出码 0、文件存在、
时长正确，都不代表内容正确。所以每道闸门都要回答一个问题：
「如果这一步静默失败，我能用什么证据发现它？」
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from .config import (
    AUDIO_PASSED,
    QA_PASSED,
    STATUS_READY,
    AUDIO_PENDING,
    MediaQaConfig,
)


def speech_target_seconds(target: float, config: MediaQaConfig) -> float:
    """口播允许占用的时长：卡片时长减去尾部呼吸位。"""
    return max(0.8, target - config.speech_tail_reserve_seconds)


def voiceover_speed(line: Mapping[str, Any], config: MediaQaConfig) -> float:
    """单卡口播倍速：原始合成时长 / 允许占用时长。

    只有超长才压缩（<1 时记 1.0），因为产线从不慢放凑时长——
    慢放出来的停顿比加速更劝退。
    """
    target = float(line["duration_seconds"])
    raw = float(line.get("raw_duration_seconds") or 0.0)
    allowed = speech_target_seconds(target, config)
    return round(raw / allowed, 3) if raw > allowed else 1.0


def speed_violations(lines: Sequence[Mapping[str, Any]], config: MediaQaConfig) -> list[dict[str, Any]]:
    """倍速超过上限的卡片。超了就该加卡片时长或删文案，而不是让听众忍。"""
    out = []
    for line in lines:
        speed = voiceover_speed(line, config)
        if speed > config.max_voiceover_speed:
            out.append({"index": line.get("index"), "speed": speed})
    return out


def tail_silence_report(lines: Sequence[Mapping[str, Any]], config: MediaQaConfig) -> dict[str, Any]:
    """尾部静音（死空气）统计：单卡超标列表 + 全片占比。

    口播比卡片短的部分会被静音补位，观众听到的是念完还在停。
    短包对占比更敏感，所以单卡秒数和全片比例都要看。
    """
    per_card = []
    dead_total = 0.0
    target_total = 0.0
    for line in lines:
        target = float(line["duration_seconds"])
        raw = float(line.get("raw_duration_seconds") or 0.0)
        dead = max(0.0, target - raw)
        dead_total += dead
        target_total += target
        if dead > config.max_tail_silence_seconds:
            per_card.append({"index": line.get("index"), "silence_seconds": round(dead, 2)})
    ratio = dead_total / target_total if target_total else 0.0
    return {
        "per_card_violations": per_card,
        "total_silence_seconds": round(dead_total, 2),
        "silence_ratio": round(ratio, 3),
        "ratio_violation": ratio > config.max_tail_silence_ratio,
    }


def pcm_sha256(payload: bytes) -> str:
    """PCM 字节哈希：用于证明「混音后的成片」和「纯口播轨」不是同一个音频。"""
    return hashlib.sha256(payload).hexdigest()


def audio_mix_proven(voiceover_pcm_hash: str, final_pcm_hash: str) -> bool:
    """BGM 真的混进去了吗。

    混音命令退出码 0 不代表混进去了（映射错流、静音 BGM 都会「成功」）。
    两个哈希相同 = 成片音频与口播轨逐字节一致 = BGM 链路静默失败。
    """
    return bool(voiceover_pcm_hash) and voiceover_pcm_hash != final_pcm_hash


def loudness_report(mean_db: float, max_db: float, config: MediaQaConfig) -> dict[str, Any]:
    """成片响度闸门：均值落在带内、峰值不顶限峰目标。"""
    low, high = config.loudness_mean_db_range
    reasons = []
    if not low <= mean_db <= high:
        reasons.append(f"mean {mean_db}dB 超出 [{low}, {high}]")
    if max_db > config.loudness_max_db_ceiling:
        reasons.append(f"max {max_db}dB 高于限峰上限 {config.loudness_max_db_ceiling}dB")
    return {"ok": not reasons, "reasons": reasons}


def bgm_volume_report(volume_db: float, config: MediaQaConfig) -> dict[str, Any]:
    """BGM 音量闸门：拦住「用默认值」和「用 0dB」两种事故。"""
    low, high = config.bgm_volume_db_range
    ok = low <= volume_db <= high
    return {
        "ok": ok,
        "reason": "" if ok else f"bgm {volume_db}dB 超出安全带 [{low}, {high}]",
    }


def tts_param_drift(
    base: Mapping[str, Any],
    candidate: Mapping[str, Any],
    config: MediaQaConfig,
) -> list[dict[str, Any]]:
    """TTS 参数整套继承检查：缺字段或值漂移都报。

    换音色/复用旧包时漏一个参数就会漂移：漏 rate 语速变、
    漏 volume 响度变、漏 pitch 像换了一个人，而且都不会报错。
    """
    drift = []
    for field_name in config.required_tts_fields:
        if field_name not in candidate:
            drift.append({"field": field_name, "kind": "missing", "base": base.get(field_name), "candidate": None})
        elif candidate[field_name] != base.get(field_name):
            drift.append({
                "field": field_name,
                "kind": "changed",
                "base": base.get(field_name),
                "candidate": candidate[field_name],
            })
    return drift


def publish_gate(status: str, audio_review_status: str, qa_status: str) -> dict[str, Any]:
    """发布前总闸：三个状态字段必须同时到位。

    任何一个字段停在 needs_manual_audio_review 都说明没人听过这条片子；
    无人听审就放行，等于把质检责任交给运气。
    """
    reasons = []
    if status != STATUS_READY:
        reasons.append(f"status={status} 不是 {STATUS_READY}")
    if audio_review_status != AUDIO_PASSED:
        reasons.append(f"audio_review_status={audio_review_status} 不是 {AUDIO_PASSED}")
    if qa_status != QA_PASSED:
        reasons.append(f"qa_status={qa_status} 不是 {QA_PASSED}")
    return {"allowed": not reasons, "reasons": reasons}


def finalize_states(manually_reviewed: bool) -> dict[str, str]:
    """混音完成后应写入的状态三件套。

    没人听过就绝不给 ready：这是「程序永远能给你成品」的唯一防线。
    """
    if manually_reviewed:
        return {"status": STATUS_READY, "audio_review_status": AUDIO_PASSED, "qa_status": QA_PASSED}
    return {"status": AUDIO_PENDING, "audio_review_status": AUDIO_PENDING, "qa_status": AUDIO_PENDING}
