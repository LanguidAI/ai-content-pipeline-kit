# ai-content-pipeline-kit

给 AI 驱动的短视频内容产线用的**质检与判定组件**。

这些模块解决的是一类特定问题：**自动化产线永远能给你一个成品，但成品不等于合格品。** 渲染脚本不会因为版式错了、语速超了、平台不适配就停下，它只会老实产出一个文件等着你发出去。所以判定必须发生在生成发布包之前，而且必须能输出「不发」。

来自一条连续运行 94 天、产出约 418 个发布包的真实产线。踩过的坑写在这里：[94 天 418 条视频、涨 176 粉、收入 0 元的复盘](https://github.com/LanguidAI/ai-video-pipeline-postmortem)。

## 设计原则

**1. 三态返回，不用布尔值**

所有质检函数返回 `pass` / `failed` / `needs_review`，而不是 `True` / `False`。

因为规则能确定的和不能确定的必须分开：把「规则判不了」静默当成 `pass` 会放过问题，当成 `failed` 会误杀正常内容。`needs_review` 是唯一诚实的第三种答案，它把决定权交回人工。

**2. 缺数据不等于不合格**

上游字段缺失时返回安全默认值（如 `aspect()` 在尺寸缺失时返回 `0.0`），而不是抛异常。抛异常会让当天整批发布包全部生产失败；返回默认值最坏只是少拦一条。

**3. 判定是生成的前置条件，不是后置筛选**

判定不通过就不生成那个平台的发布包——而不是生成完再人工挑。只要文件躺在那里，人就会心软发出去。

## 已发布模块

### `acpk.layout_qa` — 竖版视频版式质检

竖版（9:16）视频里横向图片并排摆放，每张会被压到手机上不可读。这个错误渲染阶段不报错，只有人工看片才发现，所以必须提前拦。

```python
from acpk.layout_qa import assess_shot_layout

shot = {
    "assets": [
        {"asset_id": "a", "width": 1664, "height": 928},
        {"asset_id": "b", "width": 1664, "height": 928},
    ],
    "layout": "side_by_side",
}

assess_shot_layout(shot)
# {'status': 'failed',
#  'reason': 'horizontal images must not be side-by-side in vertical video; ...'}
```

| 输入 | 返回 |
| --- | --- |
| ≥2 张横向图 + `side_by_side` | `failed` |
| ≥2 张横向图 + `stacked` / `split_shots` | `pass` |
| ≥2 张横向图 + 其他版式 | `needs_review` |
| 1 张横向图 + `horizontal_focus` / `full_width` / `single` | `pass` |
| 全是竖向图 | `pass` |

可调参数：`HORIZONTAL_ASPECT_THRESHOLD`（默认 `1.4`，取 1.4 而非 16/9≈1.78 是因为实拍截图和图表常落在 1.4~1.7，用 16/9 会漏判）、`FOCUS_LAYOUTS`、`MULTI_HORIZONTAL_LAYOUTS`。

## 路线图

| 模块 | 状态 | 内容 |
| --- | --- | --- |
| `layout_qa` | ✅ 已发布 | 竖版版式质检 |
| `platform_router` | 🚧 进行中 | 多平台分发判定：`publish` / `adapt` / `skip` 三态、适配分门槛、各平台必填字段闸门、N 天内容承诺查重 |
| `media_qa` | 🚧 进行中 | 音视频质量闸门：口播语速上限、音频失真阈值、尾部静音时长、BGM 响度区间、TTS 音色参数整套继承 |

## 安装与测试

```bash
pip install -e ".[test]"
pytest
```

要求 Python ≥ 3.10。

## 许可

MIT。见 [LICENSE](LICENSE)。
