"""多平台分发判定引擎。

解决的核心问题：一条素材做好、三个平台全发，看起来效率很高，
实际是拿同一套表达去撞三个完全不同的推荐机制——
一条内容不可能同时满足「完播+搜索」「社交转发」「前 3 秒冲突」，
于是它在三个平台上都表现平庸。

判定必须发生在发布之前，而且必须能「不发」。
"""

from .actions import (
    ADAPT,
    MODE_LEGACY_NO_SCORES,
    MODE_SCORE_THRESHOLD,
    MODE_STRICT_ASSETS,
    POLICY_CURRENT,
    POLICY_UNKNOWN_FAIL_CLOSED,
    PUBLISH,
    SKIP,
    VALID_ACTIONS,
    normalize_action,
)
from .config import (
    DEFAULT_CONFIG,
    GlobalRules,
    PlatformRules,
    RouterConfig,
    config_from_dict,
    config_from_json,
)
from .decision import build_platform_decision
from .gates import duplicate_promise, topic_selection_blocked

__all__ = [
    "ADAPT",
    "PUBLISH",
    "SKIP",
    "VALID_ACTIONS",
    "MODE_LEGACY_NO_SCORES",
    "MODE_SCORE_THRESHOLD",
    "MODE_STRICT_ASSETS",
    "POLICY_CURRENT",
    "POLICY_UNKNOWN_FAIL_CLOSED",
    "normalize_action",
    "DEFAULT_CONFIG",
    "GlobalRules",
    "PlatformRules",
    "RouterConfig",
    "config_from_dict",
    "config_from_json",
    "build_platform_decision",
    "duplicate_promise",
    "topic_selection_blocked",
]
