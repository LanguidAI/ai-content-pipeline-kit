"""规则配置：阈值、必填资产、平台数量上限全部外置。

平台规则一年改好几次。写死在代码里就得改代码，写成配置就只改一行数据，
而且能被非工程角色（内容负责人）直接维护。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

# 全局默认阈值：≥75 可直接发布，70~74 只能改写后发，<70 暂缓。
DEFAULT_PUBLISH_THRESHOLD = 75.0
DEFAULT_ADAPT_THRESHOLD = 70.0

DEFAULT_PLATFORMS: tuple[str, ...] = ("bilibili", "shipinhao", "douyin")

# 不按适配分判定的平台。抖音的分数常年缺失，它的价值取决于
# 是否有独立短版和冲突开场，用分数判会永远误杀，因此豁免分数闸门、
# 改由必填资产闸门判定。
DEFAULT_SCORE_EXEMPT: tuple[str, ...] = ("douyin",)

PLATFORM_LABELS = {"bilibili": "B站", "shipinhao": "视频号", "douyin": "抖音"}


@dataclass(frozen=True)
class PlatformRules:
    """单个平台的发布规则。"""

    label: str = ""
    publish_min_score: float = DEFAULT_PUBLISH_THRESHOLD
    required_publish_assets: tuple[str, ...] = ()
    requires_independent_short_version: bool = False
    action_points_min: int = 2
    action_points_max: int = 3
    boost: tuple[str, ...] = ()
    deprioritize: tuple[str, ...] = ()
    decision_hint: str = ""


@dataclass(frozen=True)
class GlobalRules:
    """跨平台的全局约束。"""

    require_primary_platform: bool = True
    # 一条选题最多发几个平台。产能守恒：真正适配一个平台要重做角度、
    # 结构、标题、时长、封面，摊到三个平台就是三个都不达标。
    max_publish_platforms: int = 2
    default_non_selected_action: str = "skip"
    # 相同内容承诺的查重回溯天数。防的是自动化产线最大的隐性故障：
    # 它会非常稳定地生产同质内容，而流程本身不报任何错。
    duplicate_promise_lookback_days: int = 14
    selection_gate_must_meet_one_of: tuple[str, ...] = ()


@dataclass(frozen=True)
class RouterConfig:
    """路由器完整配置。"""

    selection_policy_version: str = ""
    publish_threshold: float = DEFAULT_PUBLISH_THRESHOLD
    adapt_threshold: float = DEFAULT_ADAPT_THRESHOLD
    platforms: tuple[str, ...] = DEFAULT_PLATFORMS
    score_exempt_platforms: tuple[str, ...] = DEFAULT_SCORE_EXEMPT
    global_rules: GlobalRules = field(default_factory=GlobalRules)
    platform_rules: Mapping[str, PlatformRules] = field(default_factory=dict)

    def rules_for(self, platform: str) -> PlatformRules:
        """取某平台规则；未配置时给出带默认标签的空规则而不是报错。"""
        rules = self.platform_rules.get(platform)
        if rules is not None:
            return rules
        return PlatformRules(label=PLATFORM_LABELS.get(platform, platform))

    def label_for(self, platform: str) -> str:
        return self.rules_for(platform).label or PLATFORM_LABELS.get(platform, platform)

    def with_policy_version(self, version: str) -> "RouterConfig":
        return replace(self, selection_policy_version=version)


def _tuple(value: Any) -> tuple:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


def _platform_rules(platform: str, raw: Mapping[str, Any]) -> PlatformRules:
    return PlatformRules(
        label=str(raw.get("label") or PLATFORM_LABELS.get(platform, platform)),
        publish_min_score=float(raw.get("publish_min_score") or DEFAULT_PUBLISH_THRESHOLD),
        required_publish_assets=tuple(str(x) for x in _tuple(raw.get("required_publish_assets"))),
        requires_independent_short_version=bool(raw.get("requires_independent_short_version", False)),
        action_points_min=int(raw.get("action_points_min", 2)),
        action_points_max=int(raw.get("action_points_max", 3)),
        boost=tuple(str(x) for x in _tuple(raw.get("boost"))),
        deprioritize=tuple(str(x) for x in _tuple(raw.get("deprioritize"))),
        decision_hint=str(raw.get("decision_hint") or ""),
    )


def config_from_dict(raw: Mapping[str, Any]) -> RouterConfig:
    """从 dict 构造配置。未知键忽略，缺失键用默认值，不抛异常。

    不抛异常是刻意的：配置由内容侧维护，一个拼错的键不应该让
    当天整批发布包全部生产失败。
    """
    raw_global = raw.get("global") or {}
    gate = raw_global.get("selection_gate") or {}
    platforms = tuple(str(p) for p in _tuple(raw.get("platforms")) or DEFAULT_PLATFORMS)
    return RouterConfig(
        selection_policy_version=str(raw.get("selection_policy_version") or ""),
        publish_threshold=float(raw.get("publish_threshold") or DEFAULT_PUBLISH_THRESHOLD),
        adapt_threshold=float(raw.get("adapt_threshold") or DEFAULT_ADAPT_THRESHOLD),
        platforms=platforms,
        score_exempt_platforms=tuple(str(p) for p in _tuple(raw.get("score_exempt_platforms")) or DEFAULT_SCORE_EXEMPT),
        global_rules=GlobalRules(
            require_primary_platform=bool(raw_global.get("require_primary_platform", True)),
            max_publish_platforms=int(raw_global.get("max_publish_platforms", 2)),
            default_non_selected_action=str(raw_global.get("default_non_selected_action") or "skip"),
            duplicate_promise_lookback_days=int(raw_global.get("duplicate_promise_lookback_days", 14)),
            selection_gate_must_meet_one_of=tuple(str(x) for x in _tuple(gate.get("must_meet_one_of"))),
        ),
        platform_rules={p: _platform_rules(p, raw.get(p) or {}) for p in platforms},
    )


def config_from_json(path: str | Path) -> RouterConfig:
    return config_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# 开箱即用的默认规则。required_publish_assets 的字段名是「资产语义」而非
# 某个具体表格的列名，接入时按自己的数据结构映射即可。
DEFAULT_CONFIG = config_from_dict(
    {
        "selection_policy_version": "v1",
        "publish_threshold": 75,
        "adapt_threshold": 70,
        "global": {
            "require_primary_platform": True,
            "max_publish_platforms": 2,
            "default_non_selected_action": "skip",
            "duplicate_promise_lookback_days": 14,
            "selection_gate": {
                "must_meet_one_of": [
                    "普通人能直接上手",
                    "有真实事故案例",
                    "官方给出方法",
                ]
            },
        },
        "bilibili": {
            "publish_min_score": 75,
            "required_publish_assets": [
                "search_question",
                "search_keywords",
                "opening_answer",
                "viewer_save_asset",
            ],
            "boost": ["可搜索教程", "明确故障问题", "配置和 CLI", "排查顺序", "判断树"],
            "deprioritize": ["只有新闻事实", "没有教程结构", "开头 3 秒不能给出答案"],
            "decision_hint": "先判断谁会搜、搜什么、首屏给什么答案，以及看完能收藏走什么。",
        },
        "shipinhao": {
            "publish_min_score": 75,
            "required_publish_assets": ["opening_problem", "share_reason", "save_asset"],
            "boost": ["决策表", "排查表", "验收清单", "选择标准", "具体小团队场景"],
            "deprioritize": ["纯技术名词", "只有概念没有普通场景", "泛品牌对比", "抽象办公流程"],
            "decision_hint": "先判断谁会转发、为什么收藏，并明确交付哪张表或清单。",
        },
        "douyin": {
            "requires_independent_short_version": True,
            "required_publish_assets": [
                "opening_conflict",
                "loss_consequence",
                "short_version_plan",
                "action_points",
                "dedicated_cover_plan",
            ],
            "action_points_min": 2,
            "action_points_max": 3,
            "boost": ["强冲突短版", "泄密后果", "成本失控", "权限越界", "自动化误操作"],
            "deprioritize": ["直接复用长版", "术语密集", "开头没有冲突", "一条塞太多动作点"],
            "decision_hint": "只有前 2 秒能说清正在发生的损失、且有独立短版时才建议 publish。",
        },
    }
)
