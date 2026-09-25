"""平台分发判定：一条内容该发哪个平台，或者不发。

判定发生在发布包生成之前。判定不是 publish，那个平台的任务就不该存在——
这是整个模块唯一不可让步的设计约束。
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from .actions import (
    ADAPT,
    MODE_LEGACY_NO_SCORES,
    MODE_SCORE_THRESHOLD,
    MODE_STRICT_ASSETS,
    POLICY_CURRENT,
    POLICY_UNKNOWN_FAIL_CLOSED,
    PUBLISH,
    SKIP,
    normalize_action,
)
from .config import DEFAULT_CONFIG, RouterConfig


def _as_dict(value: Any) -> dict:
    """接受 dict、JSON 字符串或 None，统一成 dict。

    解析失败返回空 dict 而不是抛异常：上游经常传进截断的 JSON，
    抛异常会让当天整批发布包全部失败，返回空 dict 最坏只是走兼容分支。
    """
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (str, bytes)):
        text = value.decode("utf-8") if isinstance(value, bytes) else value
        if not text.strip():
            return {}
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


def _text(value: Any) -> str:
    """把任意字段值拍平成字符串；数组用逗号连接，对象取其展示字段。"""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(t for t in (_text(item) for item in value) if t)
    if isinstance(value, Mapping):
        for key in ("text", "name", "link"):
            if value.get(key):
                return str(value[key])
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _has_value(value: Any) -> bool:
    return _text(value).strip() != ""


def _number(value: Any) -> float:
    text = _text(value).replace(",", "").strip()
    try:
        number = float(text)
    except (TypeError, ValueError):
        return 0.0
    return number if number == number else 0.0  # 过滤 NaN


def _array(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _structured_present(value: Any) -> bool:
    """判断一个资产字段是否真的填了内容。

    数组要逐项检查：`["", ""]` 这种「有长度但没内容」的情况必须算缺失，
    否则会用空壳资产骗过闸门。
    """
    if isinstance(value, (list, tuple)):
        return any(_text(item).strip() for item in value)
    return _has_value(value)


def _score_action(score: float, config: RouterConfig) -> str:
    if score >= config.publish_threshold:
        return PUBLISH
    if score >= config.adapt_threshold:
        return ADAPT
    return SKIP


def _score_reason(platform: str, score: float, assessment: Mapping, config: RouterConfig) -> str:
    label = config.label_for(platform)
    reason = _text((assessment.get(platform) or {}).get("reason"))
    if reason:
        return reason
    if score >= config.publish_threshold:
        return f"{label}适配分达到直接发布线。"
    if score >= config.adapt_threshold:
        return f"{label}适配分接近发布线，建议改写后再发。"
    return f"{label}适配分低于发布线，暂缓发布。"


def _resolve_scores(
    storyboard: Mapping,
    assessment: Mapping,
    explicit: Mapping | None,
    platforms: Iterable[str],
) -> dict[str, tuple[bool, float]]:
    """按「显式传入 → 分镜里的 *_fit → 评估里的 score」优先级解析适配分。

    返回 {platform: (是否存在, 数值)}。分开返回「是否存在」是因为
    缺失和 0 分是两件完全不同的事：0 分该 skip，缺失该走兼容分支。
    """
    resolved: dict[str, tuple[bool, float]] = {}
    explicit = explicit or {}
    for platform in platforms:
        if platform in explicit and explicit[platform] is not None and _has_value(explicit[platform]):
            resolved[platform] = (True, _number(explicit[platform]))
            continue
        fit = storyboard.get(f"{platform}_fit")
        if _has_value(fit):
            resolved[platform] = (True, _number(fit))
            continue
        score = (assessment.get(platform) or {}).get("score")
        if _has_value(score):
            resolved[platform] = (True, _number(score))
            continue
        resolved[platform] = (False, 0.0)
    return resolved


def _legacy_decision(config: RouterConfig) -> dict:
    """老选题兼容分支：没有平台适配分时，保留发布任务交人工复核。"""
    scored = [p for p in config.platforms if p not in config.score_exempt_platforms]
    platforms = {
        platform: {
            "platform": platform,
            "label": config.label_for(platform),
            "score": None,
            "action": PUBLISH,
            "reason": f"旧选题未生成平台适配分，保留 {config.label_for(platform)} 发布任务，交给人工复核。",
            "source_suggestion": "",
            "rewrite_angle": "",
        }
        for platform in scored
    }
    return {
        "mode": MODE_LEGACY_NO_SCORES,
        "thresholds": {"publish": config.publish_threshold, "adapt": config.adapt_threshold},
        "recommended_platforms": list(scored),
        "adapt_platforms": [],
        "skipped_platforms": [],
        "scores": {platform: None for platform in scored},
        "platforms": platforms,
    }


def _strict_decision(
    storyboard: Mapping,
    assessment: Mapping,
    resolved: Mapping[str, tuple[bool, float]],
    policy_version: str,
    policy_status: str,
    config: RouterConfig,
) -> dict:
    """严格分支：主平台 + 最多一个次平台，其余一律 skip。"""
    valid = list(config.platforms)
    primary = _text(storyboard.get("primary_platform"))
    if primary not in valid:
        primary = ""

    # 次平台只取一个，且不能与主平台重复——这是产能守恒的硬约束。
    secondary = [
        item
        for item in (_text(x) for x in _array(storyboard.get("secondary_platforms")))
        if item in valid and item != primary
    ][:1]

    max_publish = config.global_rules.max_publish_platforms
    selected = [p for p in [primary, *secondary] if p][:max_publish]
    allowed = set(selected)

    suggestion = _as_dict(storyboard.get("platform_publish_suggestion"))
    versions = {p: _as_dict(storyboard.get(f"{p}_version")) for p in valid}
    platforms: dict[str, dict] = {}
    for platform in valid:
        rules = config.rules_for(platform)
        item = assessment.get(platform) or {}
        version = versions.get(platform) or {}
        present, value = resolved.get(platform, (False, 0.0))
        exempt = platform in config.score_exempt_platforms
        score: float | None = value if present else (None if exempt else 0.0)

        # 动作来源优先级：平台建议 → 版本动作 → 评估建议 → 兜底。
        # 兜底对分数豁免平台是 skip（宁可不发），其余按分数判。
        requested = (
            normalize_action(suggestion.get(platform))
            or normalize_action(version.get("action"))
            or normalize_action(item.get("suggestion"))
            or (SKIP if exempt else _score_action(value, config))
        )

        missing = [name for name in rules.required_publish_assets if not _structured_present(version.get(name))]

        # 动作点数量有上下限：塞太多等于没重点，太少等于没交付。
        if exempt and requested == PUBLISH:
            points = [item for item in _array(version.get("action_points")) if _text(item).strip()]
            if len(points) < rules.action_points_min or len(points) > rules.action_points_max:
                if "action_points" not in missing:
                    missing.append("action_points")

        action = requested if platform in allowed else SKIP

        # 分数闸门：豁免平台不参与（它按资产判，不按分判）。
        if action == PUBLISH and not exempt and value < rules.publish_min_score:
            action = ADAPT if value >= config.adapt_threshold else SKIP
        # 资产闸门：分数够不等于能发，缺必填资产一律降级改写。
        if action == PUBLISH and missing:
            action = ADAPT
        # 策略版本闸门：版本无法识别时 fail-closed，不猜、不放行。
        if action == PUBLISH and policy_status == POLICY_UNKNOWN_FAIL_CLOSED:
            action = ADAPT

        if policy_status == POLICY_UNKNOWN_FAIL_CLOSED and platform in allowed:
            reason = "选题策略版本无法识别，已降为人工改写复核。"
        elif missing and platform in allowed:
            reason = f"{config.label_for(platform)}缺少直接发布资产：{', '.join(missing)}"
        elif platform in allowed:
            reason = _score_reason(platform, value, assessment, config)
        else:
            reason = "不是本选题的主平台或次平台。"

        platforms[platform] = {
            "platform": platform,
            "label": config.label_for(platform),
            "score": score,
            "action": action,
            "reason": reason,
            "source_suggestion": _text(item.get("suggestion")),
            "rewrite_angle": _text(item.get("rewrite_angle") or version.get("angle")),
            "missing_assets": missing,
            "publish_min_score": None if exempt else rules.publish_min_score,
        }

    ordered = [platforms[p] for p in valid if p in platforms]
    return {
        "mode": MODE_STRICT_ASSETS,
        "selection_policy_version": policy_version,
        "policy_version_status": policy_status,
        "primary_platform": primary,
        "secondary_platforms": secondary,
        "thresholds": {"publish": config.publish_threshold, "adapt": config.adapt_threshold},
        "recommended_platforms": [i["platform"] for i in ordered if i["action"] == PUBLISH][:max_publish],
        "adapt_platforms": [i["platform"] for i in ordered if i["action"] == ADAPT],
        "skipped_platforms": [i["platform"] for i in ordered if i["action"] == SKIP],
        "scores": {
            p: (resolved[p][1] if resolved.get(p, (False,))[0] else (None if p in config.score_exempt_platforms else 0.0))
            for p in valid
        },
        "platforms": platforms,
    }


def _score_threshold_decision(
    storyboard: Mapping,
    assessment: Mapping,
    resolved: Mapping[str, tuple[bool, float]],
    config: RouterConfig,
) -> dict:
    """阈值分支：有适配分但没有策略版本，只按分数判。"""
    platforms: dict[str, dict] = {}
    for platform in config.platforms:
        if platform in config.score_exempt_platforms:
            continue
        _, value = resolved.get(platform, (False, 0.0))
        item = assessment.get(platform) or {}
        platforms[platform] = {
            "platform": platform,
            "label": config.label_for(platform),
            "score": value,
            "action": _score_action(value, config),
            "reason": _score_reason(platform, value, assessment, config),
            "source_suggestion": _text(item.get("suggestion")),
            "rewrite_angle": _text(item.get("rewrite_angle")),
        }

    # 分数豁免平台单独处理：它的门槛是「有没有独立短版」，不是分数。
    for platform in config.score_exempt_platforms:
        rules = config.rules_for(platform)
        item = assessment.get(platform) or {}
        version = _as_dict(storyboard.get(f"{platform}_version"))
        suggestion = _as_dict(storyboard.get("platform_publish_suggestion"))
        requires_short = bool(rules.requires_independent_short_version or version.get("requires_independent_short_version"))
        action = (
            normalize_action(item.get("suggestion"))
            or normalize_action(suggestion.get(platform))
            or normalize_action(version.get("action"))
            or SKIP
        )
        missing_short = action == PUBLISH and requires_short and not _text(version.get("short_version_plan"))
        if missing_short:
            action = ADAPT
        _, value = resolved.get(platform, (False, 0.0))
        platforms[platform] = {
            "platform": platform,
            "label": config.label_for(platform),
            "score": value if resolved.get(platform, (False, 0.0))[0] else None,
            "action": action,
            "reason": _text(item.get("reason"))
            or (
                f"{config.label_for(platform)}需要独立 30-40 秒短版；当前缺少短版计划，先改写后再发。"
                if missing_short
                else f"{config.label_for(platform)}按复盘规则只推荐强冲突独立短版。"
            ),
            "source_suggestion": _text(item.get("suggestion")),
            "rewrite_angle": _text(item.get("rewrite_angle") or suggestion.get(f"{platform}_short_angle") or version.get("angle")),
            "requires_independent_short_version": requires_short,
            "short_version_plan": _text(version.get("short_version_plan")),
        }

    ordered = [platforms[p] for p in config.platforms if p in platforms]
    return {
        "mode": MODE_SCORE_THRESHOLD,
        "thresholds": {"publish": config.publish_threshold, "adapt": config.adapt_threshold},
        "recommended_platforms": [i["platform"] for i in ordered if i["action"] == PUBLISH],
        "adapt_platforms": [i["platform"] for i in ordered if i["action"] == ADAPT],
        "skipped_platforms": [i["platform"] for i in ordered if i["action"] == SKIP],
        "scores": {p: platforms[p]["score"] for p in platforms},
        "platforms": platforms,
    }


def build_platform_decision(
    *,
    storyboard: Any = None,
    fit_assessment: Any = None,
    scores: Mapping[str, Any] | None = None,
    config: RouterConfig | None = None,
) -> dict:
    """判定一条选题在各平台的动作。

    参数
    ----
    storyboard:     分镜脚本，dict 或 JSON 字符串。承载策略版本、主/次平台、
                    各平台版本资产、以及 *_fit 适配分。
    fit_assessment: 平台适配建议，dict 或 JSON 字符串。
    scores:         显式适配分 {platform: 分数}，优先级最高；传 None 表示该字段缺失。
    config:         规则配置，默认 DEFAULT_CONFIG。

    返回
    ----
    dict，含 `mode`、`recommended_platforms`、`adapt_platforms`、`skipped_platforms`、
    以及每个平台的 `action` / `reason` / `missing_assets`。
    """
    cfg = config or DEFAULT_CONFIG
    sb = _as_dict(storyboard)
    raw_assessment = _as_dict(fit_assessment)
    sb_assessment = _as_dict(sb.get("platform_fit_assessment"))

    policy_version = _text(sb.get("selection_policy_version"))
    strict = bool(policy_version)
    policy_status = POLICY_CURRENT if policy_version == cfg.selection_policy_version else POLICY_UNKNOWN_FAIL_CLOSED

    # 严格模式下，分镜内的评估覆盖外部评估（分镜是更新的一手数据）。
    if strict:
        assessment: Mapping = {
            p: {**(raw_assessment.get(p) or {}), **(sb_assessment.get(p) or {})} for p in cfg.platforms
        }
    else:
        assessment = raw_assessment if raw_assessment else sb_assessment

    resolved = _resolve_scores(sb, assessment, scores, cfg.platforms)

    has_scored = any(
        resolved.get(p, (False, 0.0))[0] for p in cfg.platforms if p not in cfg.score_exempt_platforms
    )
    if not strict and not has_scored:
        return _legacy_decision(cfg)
    if strict:
        return _strict_decision(sb, assessment, resolved, policy_version, policy_status, cfg)
    return _score_threshold_decision(sb, assessment, resolved, cfg)
