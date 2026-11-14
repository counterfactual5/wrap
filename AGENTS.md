# Agent 约定（本仓库）

本仓库是零模板的代码驱动视频流水线（zero-template Code-driven Video Pipeline）：
引擎**不包含任何视觉设计**——没有内置配色、组件、场景、音频预设或占位素材。
它只提供三件事：环境能力驱动的素材生产、通用媒体合成（ai/video/component 三层 +
几何编排）、广播音频与确定性质检。画面一律由视频项目自己创作
（`<project>/remotion-custom.tsx` 的组件与生成素材）。
旧词汇（code/text/hud/card 图层、palette、vibe/plate/punches、gait/depth、
BGM 预设、`--fixture`、内置模型目录、Quartz 设计后端）校验时报
`migration required`，绝不明式渲染。详见 `skills/wrap/SKILL.md` 与 `README.md`。

## Full Verify

Full Verify: make verify

`make` 会自动挑选 ≥ 3.10 的解释器（`python3.13` → `python3.12` → `python3.11` →
`python3.10` → `python3`）。引擎使用 `int.bit_count()`，低于 3.10 会在启动时
直接报错退出，不会带着旧解释器跑完整套测试。需要指定解释器时：`make PY=python3.12 verify`。

## 局部验证

测试按被测对象分包，**必须用 `discover` 形式**（`unittest` 不会自动递归子包，
`python -m unittest tests.core` 会跑 0 个用例）：

```bash
python3.12 -m unittest discover -s tests/contract -t .   # 契约一致性
python3.12 -m unittest discover -s tests/core -t .       # core/ 运行时
python3.12 -m unittest discover -s tests/stages -t .     # S1-S5
python3.12 -m unittest discover -s tests/pipeline -t .   # 端到端
python3.12 -m unittest tests.core.test_rig_ik           # 单个模块可直接指定
```

## 目录约定

```
pipeline.py      CLI：argparse、阶段子进程编排、退出码
stages/          S1–S5 阶段入口；S1/S3 的实现主要位于 core/
core/
  spec/          规格契约：词汇、字段校验（含旧词汇拒绝）、时间线、关节解析、状态继承
  generation/    S1 传输层：connector（仅传输适配）、图像/视频生成与轮询、上传；
                 模型能力仅由环境变量声明（models.py 默认空目录）
  rendering/     S3 实现：时间轴对齐、抽帧、Remotion 驱动（唯一渲染引擎）、编码
  assembly/      时间线装配领域逻辑（无 argparse / sys.exit）
  media/         PNG、指纹、几何计算
  quality/       像素质量测量
  audio/         TTS、母带、字幕计时、镜头混音、同步、音频测量（BGM 仅显式文件）
  rig/           精灵处理、套件、姿态、运动学、几何校验（无动作预设）
  runtime/       引擎根、项目根和冻结资产账本
remotion/        TS 渲染引擎：裸画布 + ai/video/component 三层 + 项目组件注册表
```

注：测试用的占位图生成（`write_fixture`/`fake_city`）位于 `tests/helpers.py`，
不属于生产路径；`core/media/draw.py` 与 `renderers/quartz/` 已删除。

依赖边界：阶段入口调用 core 实现，core 不反向导入 stages；共享几何逻辑位于 media。
`core/spec/resolution.py` 与 `core/rig` 之间的几何函数都放在 `core/media/geometry.py`，
以避免包级循环依赖。

## 模块位置

`core/` 根目录只保留 `__init__.py` 和子包，不留实现文件或兼容入口。
所有代码、测试及子进程代码直接使用以下模块：

| 职责 | 模块 |
|---|---|
| `ROOT` / `ENGINE_ROOT` | `core.runtime.config` |
| 冻结资产账本 | `core.runtime.manifest` |
| 模型能力（环境变量声明，默认空） | `core.generation.models` |
| 规格公共 API | `core.spec` |
| `LAYER_TYPES`（ai/video/component）等词汇 | `core.spec.constants` |
| 镜头 / 图层校验 | `core.spec.shot` / `core.spec.layers` |
| 时间线校验 / `VALID_BEATS` | `core.spec.timeline` |
| 加载规格 / 状态继承 | `core.spec.loader` / `core.spec.state` |
| 命名 / 关节解析 | `core.spec.naming` / `core.spec.resolution` |
| PNG / 像素质量 | `core.media.png` / `core.quality.pixels` |
| 渲染 | `core.rendering` |

可变状态赋值、mock 和 reload 均指向定义模块，不通过根目录门面。

## 改代码时的硬约束

- **使用子包入口**：不在 `core/` 根目录新增实现文件或兼容门面；保留
  `core.audio` / `core.rig` 包级 API，内部引用使用上述模块位置。
- **mock 要指向定义模块**：实现下沉后，`patch("core.audio.X")` 这类目标要改成真正
  定义该函数的子模块，否则 patch 静默失效。
- **契约检查扫源码**：跨层契约测试从 `remotion/` 源码里扫图层 type 分派，渲染器文件
  增删后不需要改测试，但**不要**把分派搬出 `remotion/` 目录。
- **不要覆盖用户账本**：测试应使用隔离的 manifest 或 `tests.helpers.preserve_manifest()`；
  不要用 `git checkout` 覆盖测试前已有的未提交账本改动。
- **不触发真实计费调用**：所有验证走 mock 或 `tests.helpers` 注册好的测试资产
  （`env_with_models` 注入 `TEST_VIDEO_MODELS`/`TEST_IMAGE_MODELS`，`make_test_clip`/
  `register_test_asset` 造媒体）。生产路径没有 `--fixture`。
- **零模板契约**：不得向引擎添加任何视觉设计（颜色、字体、组件、场景、音频预设、
  占位素材）；模型能力不得内置目录，只能来自环境变量声明。测试需要占位图时用
  `tests/helpers.py`，不得放进 `core/`。
