"""音视频质量闸门测试。

用例数字全部取自真实产线事故或实测样本：1.39 倍速、3.7s 尾部静音、
21% 死空气占比、哈希相同的「混音」、照抄 -23dB 默认值——
每一个都曾经以「程序成功」的形态流过产线。
"""

import json

import pytest

from acpk.media_qa import (
    AUDIO_PASSED,
    AUDIO_PENDING,
    DEFAULT_CONFIG,
    QA_PASSED,
    STATUS_READY,
    MediaQaConfig,
    audio_mix_proven,
    bgm_volume_report,
    config_from_dict,
    config_from_json,
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


def line(index, target, raw):
    return {"index": index, "duration_seconds": target, "raw_duration_seconds": raw}


TTS_BASE = {"provider": "dashscope", "model": "sambert-a", "voice": "v1", "rate": 1.0, "volume": 72, "pitch": 1.0}


# ---- 倍速 ----

def test_speed_is_one_when_raw_fits():
    assert voiceover_speed(line(1, 9.0, 7.0), DEFAULT_CONFIG) == 1.0


def test_speed_uses_tail_reserve_in_denominator():
    # 允许占用 = 8 - 0.18 = 7.82；10.872 / 7.82 = 1.39（真实事故值）
    assert voiceover_speed(line(4, 8.0, 10.872), DEFAULT_CONFIG) == 1.39


def test_speed_violations_flag_over_compressed_cards():
    lines = [line(1, 8.0, 10.872), line(2, 9.0, 7.0)]
    assert speed_violations(lines, DEFAULT_CONFIG) == [{"index": 1, "speed": 1.39}]


def test_speed_boundary_is_inclusive_at_limit():
    allowed = speech_target_seconds(8.0, DEFAULT_CONFIG)
    at_limit = line(1, 8.0, round(allowed * 1.35, 3))
    over = line(2, 8.0, round(allowed * 1.36, 3))
    assert speed_violations([at_limit], DEFAULT_CONFIG) == []
    assert len(speed_violations([over], DEFAULT_CONFIG)) == 1


def test_speed_limit_is_configurable():
    cfg = config_from_dict({"max_voiceover_speed": 1.4})
    assert speed_violations([line(1, 8.0, 10.872)], cfg) == []


# ---- 尾部静音 ----

def test_tail_silence_counts_gap_only_when_raw_shorter():
    report = tail_silence_report([line(1, 8.0, 4.272)], DEFAULT_CONFIG)
    assert report["per_card_violations"] == [{"index": 1, "silence_seconds": 3.73}]
    assert report["total_silence_seconds"] == 3.73


def test_tail_silence_zero_when_raw_overruns():
    report = tail_silence_report([line(1, 8.0, 9.6)], DEFAULT_CONFIG)
    assert report["per_card_violations"] == []
    assert report["total_silence_seconds"] == 0.0


def test_tail_silence_ratio_catches_short_pack():
    # 30s 短包塞 6.4s 死空气 = 21.3%，单卡都不超标但全片发散
    lines = [line(1, 4.0, 3.98), line(2, 9.0, 7.87), line(3, 9.0, 7.44), line(4, 8.0, 4.27)]
    report = tail_silence_report(lines, DEFAULT_CONFIG)
    assert report["ratio_violation"] is True
    assert report["silence_ratio"] == pytest.approx(0.213, abs=0.005)


def test_tail_silence_ratio_ok_for_tight_pack():
    lines = [line(1, 9.0, 8.9), line(2, 10.0, 9.6)]
    report = tail_silence_report(lines, DEFAULT_CONFIG)
    assert report["ratio_violation"] is False


# ---- 混音证明 ----

def test_pcm_hash_is_stable_and_sensitive():
    assert pcm_sha256(b"abc") == pcm_sha256(b"abc")
    assert pcm_sha256(b"abc") != pcm_sha256(b"abd")


def test_mix_proven_when_hashes_differ():
    assert audio_mix_proven(pcm_sha256(b"voice"), pcm_sha256(b"voice+bgm")) is True


def test_mix_not_proven_when_identical():
    same = pcm_sha256(b"voice")
    assert audio_mix_proven(same, same) is False


def test_mix_not_proven_when_voiceover_hash_missing():
    assert audio_mix_proven("", pcm_sha256(b"x")) is False


# ---- 响度 ----

def test_loudness_ok_for_measured_final():
    assert loudness_report(-20.8, -3.8, DEFAULT_CONFIG)["ok"] is True


def test_loudness_mean_out_of_band():
    report = loudness_report(-15.0, -3.8, DEFAULT_CONFIG)
    assert report["ok"] is False and len(report["reasons"]) == 1


def test_loudness_peak_over_ceiling():
    report = loudness_report(-20.8, -0.5, DEFAULT_CONFIG)
    assert report["ok"] is False and "限峰" in report["reasons"][0]


def test_loudness_reports_both_reasons():
    report = loudness_report(-10.0, 0.0, DEFAULT_CONFIG)
    assert len(report["reasons"]) == 2


# ---- BGM 音量 ----

@pytest.mark.parametrize("db", [-18.0, -22.0])
def test_bgm_volume_in_safe_band(db):
    assert bgm_volume_report(db, DEFAULT_CONFIG)["ok"] is True


def test_bgm_volume_rejects_library_default():
    # -23 是混音库默认值：照抄默认 = 没做判断，必须拦
    report = bgm_volume_report(-23.0, DEFAULT_CONFIG)
    assert report["ok"] is False and "-23.0" in report["reason"]


def test_bgm_volume_rejects_zero_db():
    assert bgm_volume_report(0.0, DEFAULT_CONFIG)["ok"] is False


# ---- TTS 参数继承 ----

def test_tts_no_drift_when_identical():
    assert tts_param_drift(TTS_BASE, dict(TTS_BASE), DEFAULT_CONFIG) == []


def test_tts_missing_field_reported():
    candidate = {k: v for k, v in TTS_BASE.items() if k != "pitch"}
    drift = tts_param_drift(TTS_BASE, candidate, DEFAULT_CONFIG)
    assert drift == [{"field": "pitch", "kind": "missing", "base": 1.0, "candidate": None}]


def test_tts_changed_value_reported():
    candidate = dict(TTS_BASE, rate=1.2)
    drift = tts_param_drift(TTS_BASE, candidate, DEFAULT_CONFIG)
    assert drift == [{"field": "rate", "kind": "changed", "base": 1.0, "candidate": 1.2}]


def test_tts_extra_fields_ignored():
    assert tts_param_drift(TTS_BASE, dict(TTS_BASE, bgm="x.mp4"), DEFAULT_CONFIG) == []


def test_tts_required_fields_configurable():
    cfg = config_from_dict({"required_tts_fields": ["model"]})
    assert tts_param_drift(TTS_BASE, {"model": TTS_BASE["model"]}, cfg) == []


# ---- 发布总闸与状态机 ----

def test_publish_gate_allows_fully_reviewed_package():
    gate = publish_gate(STATUS_READY, AUDIO_PASSED, QA_PASSED)
    assert gate == {"allowed": True, "reasons": []}


@pytest.mark.parametrize(
    "status,audio,qa",
    [
        (AUDIO_PENDING, AUDIO_PENDING, AUDIO_PENDING),
        (STATUS_READY, AUDIO_PENDING, AUDIO_PENDING),
        (STATUS_READY, AUDIO_PASSED, "needs_manual_audio_review"),
    ],
)
def test_publish_gate_blocks_unreviewed_packages(status, audio, qa):
    gate = publish_gate(status, audio, qa)
    assert gate["allowed"] is False and len(gate["reasons"]) >= 1


def test_finalize_states_without_review_never_ready():
    states = finalize_states(False)
    assert STATUS_READY not in states.values()
    assert publish_gate(**states)["allowed"] is False


def test_finalize_states_with_review_passes_gate():
    states = finalize_states(True)
    assert states == {"status": STATUS_READY, "audio_review_status": AUDIO_PASSED, "qa_status": QA_PASSED}
    assert publish_gate(**states)["allowed"] is True


# ---- 配置 ----

def test_config_from_dict_overrides_scalars_ranges_and_tuples():
    cfg = config_from_dict({
        "max_voiceover_speed": 1.2,
        "bgm_volume_db_range": [-20, -10],
        "required_tts_fields": ["voice"],
    })
    assert cfg.max_voiceover_speed == 1.2
    assert cfg.bgm_volume_db_range == (-20.0, -10.0)
    assert cfg.required_tts_fields == ("voice",)
    assert cfg.max_tail_silence_seconds == DEFAULT_CONFIG.max_tail_silence_seconds


def test_config_from_json_roundtrip(tmp_path):
    path = tmp_path / "media_qa.json"
    path.write_text(json.dumps({"loudness_max_db_ceiling": -2.0}), encoding="utf-8")
    assert config_from_json(path).loudness_max_db_ceiling == -2.0


def test_media_qa_config_is_frozen():
    with pytest.raises(Exception):
        DEFAULT_CONFIG.max_voiceover_speed = 2.0
