"""平台判定引擎测试。

前 6 个用例从原始实现逐条移植（原实现是埋在工作流 JSON 里的 JavaScript，
测试靠字符串切片 + subprocess 调 node 执行），用于证明重构后的语义一致。
移植时做了两处修正：

1. 策略版本改为从 `DEFAULT_CONFIG` 同源读取。原实现把版本硬编码在测试
   fixture 里，线上配置一改就触发 fail-closed，原仓库因此有 2 条用例长期
   处于失败状态。
2. 抖音的适配分只来自平台评估、且线上常年缺失，所以涉及抖音豁免分数闸门
   的用例，fixture 里不能给它塞分数，否则测的是另一个分支。
"""

import json

import pytest

from acpk.platform_router import (
    ADAPT,
    DEFAULT_CONFIG,
    MODE_LEGACY_NO_SCORES,
    MODE_SCORE_THRESHOLD,
    MODE_STRICT_ASSETS,
    POLICY_CURRENT,
    POLICY_UNKNOWN_FAIL_CLOSED,
    PUBLISH,
    SKIP,
    build_platform_decision,
    config_from_dict,
    duplicate_promise,
    normalize_action,
    topic_selection_blocked,
)

# 与配置同源，避免 fixture 里的策略版本和 DEFAULT_CONFIG 漂移。
POLICY = DEFAULT_CONFIG.selection_policy_version

BILIBILI_ASSETS = {
    "action": "publish",
    "search_question": "工作流调用模型失败怎么办",
    "search_keywords": ["工作流", "Tool Calling"],
    "opening_answer": "参数错误不能靠重试解决",
    "viewer_save_asset": "重试降级熔断判断树",
}
SHIPINHAO_ASSETS = {
    "action": "publish",
    "opening_problem": "AI 总忘事怎么办",
    "share_reason": "给同事做工作流自查",
    "save_asset": "三步排查表",
}
DOUYIN_ASSETS = {
    "action": "publish",
    "opening_conflict": "AI 正在重复扣费",
    "loss_consequence": "账单失控",
    "short_version_plan": "30 秒独立短版",
    "action_points": ["分错误", "设上限"],
    "dedicated_cover_plan": "独立 3:4 封面",
    "requires_independent_short_version": True,
}

SCORES = {"bilibili": 82, "shipinhao": 80}

# 抖音评估里刻意不带 score：它豁免分数闸门，带分数会走到另一条分支上。
DOUYIN_PUBLISH_ASSESSMENT = {"douyin": {"suggestion": "publish"}}


def storyboard(**overrides):
    """构造一条分镜脚本。默认形态：B站主平台、只有 B站 建议发布。"""
    data = {
        "selection_policy_version": POLICY,
        "primary_platform": "bilibili",
        "secondary_platforms": [],
        "platform_publish_suggestion": {"bilibili": "publish", "shipinhao": "skip", "douyin": "skip"},
        "bilibili_fit": 82,
        "shipinhao_fit": 80,
        "bilibili_version": {},
        "shipinhao_version": {},
        "douyin_version": {},
        "platform_fit_assessment": {
            "bilibili": {"score": 82, "suggestion": "publish"},
            "shipinhao": {"score": 80, "suggestion": "skip"},
            "douyin": {"score": 80, "suggestion": "skip"},
        },
    }
    data.update(overrides)
    return data


def douyin_priority_storyboard(**overrides):
    """抖音为主平台、且评估里不带适配分的分镜。"""
    data = {
        "primary_platform": "douyin",
        "platform_publish_suggestion": {"douyin": "publish", "bilibili": "skip", "shipinhao": "skip"},
        "platform_fit_assessment": dict(DOUYIN_PUBLISH_ASSESSMENT),
        "douyin_version": DOUYIN_ASSETS,
    }
    data.update(overrides)
    return storyboard(**data)


# --------------------------------------------------------------------------
# 移植用例：语义必须与原始实现一致
# --------------------------------------------------------------------------


def test_legacy_topic_without_platform_scores_keeps_legacy_publish_behavior():
    """老选题没有适配分：保留发布任务交人工复核，绝不当 0 分 skip。"""
    decision = build_platform_decision(storyboard={})

    assert decision["mode"] == MODE_LEGACY_NO_SCORES
    assert decision["recommended_platforms"] == ["bilibili", "shipinhao"]
    assert decision["scores"]["bilibili"] is None
    assert decision["platforms"]["bilibili"]["action"] == PUBLISH


def test_new_shipinhao_topic_missing_save_asset_is_downgraded_to_adapt():
    decision = build_platform_decision(
        storyboard=storyboard(
            primary_platform="shipinhao",
            platform_publish_suggestion={"bilibili": "skip", "shipinhao": "publish", "douyin": "skip"},
            shipinhao_version=dict(SHIPINHAO_ASSETS, save_asset=""),
        ),
        scores=SCORES,
    )

    assert decision["mode"] == MODE_STRICT_ASSETS
    assert decision["platforms"]["shipinhao"]["action"] == ADAPT
    assert "save_asset" in decision["platforms"]["shipinhao"]["missing_assets"]


def test_new_bilibili_topic_with_required_assets_can_publish():
    decision = build_platform_decision(
        storyboard=storyboard(bilibili_version=BILIBILI_ASSETS), scores=SCORES
    )

    assert decision["platforms"]["bilibili"]["action"] == PUBLISH
    assert decision["recommended_platforms"] == ["bilibili"]


def test_new_policy_caps_publish_platforms_to_primary_and_one_secondary():
    decision = build_platform_decision(
        storyboard=storyboard(
            secondary_platforms=["shipinhao"],
            platform_publish_suggestion={"bilibili": "publish", "shipinhao": "publish", "douyin": "publish"},
            bilibili_version=BILIBILI_ASSETS,
            shipinhao_version=SHIPINHAO_ASSETS,
            douyin_version=DOUYIN_ASSETS,
        ),
        scores=SCORES,
    )

    assert decision["recommended_platforms"] == ["bilibili", "shipinhao"]
    assert decision["platforms"]["douyin"]["action"] == SKIP


def test_unknown_nonempty_policy_version_fails_closed_in_strict_mode():
    """策略版本认不出来时不猜、不放行，降级为人工改写复核。"""
    decision = build_platform_decision(
        storyboard=storyboard(selection_policy_version="2099-01-01", bilibili_version=BILIBILI_ASSETS),
        scores=SCORES,
    )

    assert decision["mode"] == MODE_STRICT_ASSETS
    assert decision["policy_version_status"] == POLICY_UNKNOWN_FAIL_CLOSED
    assert decision["platforms"]["bilibili"]["action"] == ADAPT


def test_required_assets_and_publish_threshold_are_driven_by_config():
    """阈值和必填资产全在配置里，改规则不需要改代码。"""
    config = config_from_dict(
        {
            "selection_policy_version": POLICY,
            "global": {"max_publish_platforms": 2},
            "bilibili": {"publish_min_score": 90, "required_publish_assets": ["custom_asset"]},
            "shipinhao": {"required_publish_assets": ["opening_problem", "share_reason", "save_asset"]},
            "douyin": {"requires_independent_short_version": True},
        }
    )

    decision = build_platform_decision(
        storyboard=storyboard(bilibili_version={"action": "publish", "custom_asset": ""}),
        scores=SCORES,
        config=config,
    )

    assert decision["platforms"]["bilibili"]["action"] == ADAPT
    assert decision["platforms"]["bilibili"]["publish_min_score"] == 90
    assert decision["platforms"]["bilibili"]["missing_assets"] == ["custom_asset"]


def test_fixture_policy_version_is_recognized_as_current():
    """防回归：fixture 的策略版本必须和 DEFAULT_CONFIG 同源。

    原实现把版本硬编码在测试里，线上配置一漂移就全线 fail-closed。
    """
    decision = build_platform_decision(storyboard=storyboard(), scores=SCORES)

    assert POLICY
    assert decision["policy_version_status"] == POLICY_CURRENT


# --------------------------------------------------------------------------
# 分数闸门
# --------------------------------------------------------------------------


def test_score_below_adapt_threshold_is_skipped_not_adapted():
    decision = build_platform_decision(
        storyboard=storyboard(bilibili_version=BILIBILI_ASSETS),
        scores={"bilibili": 55, "shipinhao": 80},
    )

    assert decision["platforms"]["bilibili"]["action"] == SKIP


def test_score_between_adapt_and_publish_threshold_is_adapted():
    decision = build_platform_decision(
        storyboard=storyboard(bilibili_version=BILIBILI_ASSETS),
        scores={"bilibili": 72, "shipinhao": 80},
    )

    assert decision["platforms"]["bilibili"]["action"] == ADAPT


def test_scores_resolved_from_storyboard_fit_when_not_passed_explicitly():
    """适配分优先级：显式传入 → 分镜 *_fit → 评估 score。"""
    decision = build_platform_decision(storyboard=storyboard(bilibili_version=BILIBILI_ASSETS))

    assert decision["mode"] == MODE_STRICT_ASSETS
    assert decision["scores"]["bilibili"] == 82


def test_whitespace_only_asset_counts_as_missing():
    """`["", "  "]` 这种有长度没内容的空壳资产必须算缺失。"""
    decision = build_platform_decision(
        storyboard=storyboard(bilibili_version=dict(BILIBILI_ASSETS, search_keywords=["", "  "])),
        scores=SCORES,
    )

    assert decision["platforms"]["bilibili"]["action"] == ADAPT
    assert "search_keywords" in decision["platforms"]["bilibili"]["missing_assets"]


# --------------------------------------------------------------------------
# 抖音：豁免分数闸门，改由资产闸门判定
# --------------------------------------------------------------------------


def test_douyin_is_exempt_from_score_gate():
    """抖音没有适配分，照样能靠齐全的资产直接发布。"""
    decision = build_platform_decision(storyboard=douyin_priority_storyboard(), scores=SCORES)

    assert decision["mode"] == MODE_STRICT_ASSETS
    assert decision["platforms"]["douyin"]["action"] == PUBLISH
    assert decision["platforms"]["douyin"]["score"] is None
    assert decision["platforms"]["douyin"]["publish_min_score"] is None


def test_douyin_low_score_does_not_block_publish_when_assets_complete():
    """分数豁免的真实意义：30 分也不会误杀资产齐全的抖音选题。"""
    decision = build_platform_decision(
        storyboard=douyin_priority_storyboard(
            platform_fit_assessment={"douyin": {"score": 30, "suggestion": "publish"}}
        )
    )

    assert decision["platforms"]["douyin"]["action"] == PUBLISH
    assert decision["platforms"]["douyin"]["score"] == 30


def test_douyin_action_points_out_of_range_downgrades_to_adapt():
    """动作点太少等于没交付。"""
    decision = build_platform_decision(
        storyboard=douyin_priority_storyboard(
            douyin_version=dict(DOUYIN_ASSETS, action_points=["只有一个动作点"])
        ),
        scores=SCORES,
    )

    assert decision["platforms"]["douyin"]["action"] == ADAPT
    assert "action_points" in decision["platforms"]["douyin"]["missing_assets"]


def test_douyin_too_many_action_points_also_downgrades():
    """动作点太多等于没重点。"""
    decision = build_platform_decision(
        storyboard=douyin_priority_storyboard(
            douyin_version=dict(DOUYIN_ASSETS, action_points=["a", "b", "c", "d"])
        ),
        scores=SCORES,
    )

    assert decision["platforms"]["douyin"]["action"] == ADAPT


# --------------------------------------------------------------------------
# 主/次平台与产能守恒
# --------------------------------------------------------------------------


def test_secondary_platform_capped_at_one():
    """真正适配一个平台要重做角度、结构、标题、时长、封面，摊不开。"""
    decision = build_platform_decision(
        storyboard=storyboard(
            secondary_platforms=["shipinhao", "douyin"],
            bilibili_version=BILIBILI_ASSETS,
            shipinhao_version=SHIPINHAO_ASSETS,
            douyin_version=DOUYIN_ASSETS,
            platform_publish_suggestion={"bilibili": "publish", "shipinhao": "publish", "douyin": "publish"},
        ),
        scores=SCORES,
    )

    assert decision["secondary_platforms"] == ["shipinhao"]
    assert decision["platforms"]["douyin"]["action"] == SKIP


def test_secondary_equal_to_primary_is_dropped():
    decision = build_platform_decision(
        storyboard=storyboard(secondary_platforms=["bilibili"], bilibili_version=BILIBILI_ASSETS),
        scores=SCORES,
    )

    assert decision["secondary_platforms"] == []


def test_invalid_primary_platform_is_ignored():
    """没有合法主平台时全部 skip，而不是兜底发一个。"""
    decision = build_platform_decision(
        storyboard=storyboard(primary_platform="kuaishou", bilibili_version=BILIBILI_ASSETS),
        scores=SCORES,
    )

    assert decision["primary_platform"] == ""
    assert decision["platforms"]["bilibili"]["action"] == SKIP


# --------------------------------------------------------------------------
# 阈值模式（有适配分、无策略版本）
# --------------------------------------------------------------------------


def test_score_threshold_mode_when_scores_present_without_policy_version():
    sb = storyboard(bilibili_version=BILIBILI_ASSETS)
    sb.pop("selection_policy_version")

    decision = build_platform_decision(storyboard=sb, scores=SCORES)

    assert decision["mode"] == MODE_SCORE_THRESHOLD
    assert decision["platforms"]["bilibili"]["action"] == PUBLISH
    assert decision["platforms"]["shipinhao"]["action"] == PUBLISH


def test_score_threshold_mode_requires_independent_short_version_for_douyin():
    """阈值模式下抖音的门槛是「有没有独立短版」，不是分数。"""
    sb = storyboard(
        platform_publish_suggestion={"bilibili": "skip", "shipinhao": "skip", "douyin": "publish"},
        platform_fit_assessment=dict(DOUYIN_PUBLISH_ASSESSMENT),
        douyin_version={"action": "publish"},
    )
    sb.pop("selection_policy_version")

    decision = build_platform_decision(storyboard=sb, scores=SCORES)

    assert decision["mode"] == MODE_SCORE_THRESHOLD
    assert decision["platforms"]["douyin"]["action"] == ADAPT
    assert decision["platforms"]["douyin"]["requires_independent_short_version"] is True


# --------------------------------------------------------------------------
# 输入健壮性
# --------------------------------------------------------------------------


def test_malformed_json_storyboard_does_not_raise():
    """上游经常传进截断的 JSON；抛异常会让当天整批发布包全失败。"""
    decision = build_platform_decision(storyboard='{"selection_policy_version": ')

    assert decision["mode"] == MODE_LEGACY_NO_SCORES


def test_storyboard_accepts_json_string():
    decision = build_platform_decision(
        storyboard=json.dumps(storyboard(bilibili_version=BILIBILI_ASSETS), ensure_ascii=False),
        scores=SCORES,
    )

    assert decision["platforms"]["bilibili"]["action"] == PUBLISH


def test_normalize_action():
    assert normalize_action("PUBLISH") == PUBLISH
    assert normalize_action(" Adapt ") == ADAPT
    assert normalize_action("skip") == SKIP
    assert normalize_action("") == ""
    assert normalize_action(None) == ""
    # 认不出来返回空串而不是默认 skip，调用方才能继续尝试下一个来源。
    assert normalize_action("delete") == ""


# --------------------------------------------------------------------------
# 选题闸门
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "topic,expected",
    [
        ({"selected": False}, True),
        ({"selected": True, "duplicate_check": {"status": "duplicate"}}, True),
        ({"selected": True, "duplicate_check": {"status": "clear"}}, False),
        # 非法输入一律阻断：fail-closed。
        (None, True),
        ({}, True),
        ("not-a-dict", True),
    ],
)
def test_topic_selection_blocked(topic, expected):
    assert topic_selection_blocked(topic) is expected


def test_duplicate_promise_within_lookback_is_blocked():
    result = duplicate_promise(
        "三步排查表", ["三步排查表", "判断树"], lookback_days=14, used_days_ago={"三步排查表": 5}
    )

    assert result["status"] == "duplicate"


def test_duplicate_promise_outside_lookback_is_clear():
    result = duplicate_promise(
        "三步排查表", ["三步排查表"], lookback_days=14, used_days_ago={"三步排查表": 30}
    )

    assert result["status"] == "clear"


def test_duplicate_promise_defaults_to_whole_window_when_age_unknown():
    """没记录使用日期时，按「还在窗口内」处理。"""
    assert duplicate_promise("三步排查表", ["三步排查表"])["status"] == "duplicate"


def test_empty_promise_does_not_participate_in_dedup():
    assert duplicate_promise("", ["x"])["status"] == "clear"
