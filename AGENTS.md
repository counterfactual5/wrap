# Agent 约定（本仓库）

本仓库是代码驱动的海报镜头视频渲染流水线（Code-driven Poster Shot Pipeline）。

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
  spec/          规格契约：词汇、字段校验、时间线、关节解析、状态继承
  generation/    S1 传输层：connector、图像/视频生成与轮询、上传、fixture
  rendering/     S3 实现：时间轴对齐、抽帧、Remotion 驱动、Quartz 兜底、编码
  assembly/      时间线装配领域逻辑（无 argparse / sys.exit）
  media/         PNG、程序化绘图、指纹、几何计算
  quality/       像素质量测量
  audio/         TTS、BGM、母带、字幕计时、镜头混音、同步、音频测量
  rig/           精灵处理、套件、姿态、运动学、编舞、各项校验
  runtime/       引擎根、项目根和冻结资产账本
renderers/quartz/ 原生 Swift 兜底渲染器
```

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
| 模型能力目录 | `core.generation.models` |
| 规格公共 API | `core.spec` |
| `DRAWS` 等词汇 | `core.spec.constants` |
| 镜头 / 图层校验 | `core.spec.shot` / `core.spec.layers` |
| 时间线校验 / `VALID_BEATS` | `core.spec.timeline` |
| 加载规格 / 状态继承 | `core.spec.loader` / `core.spec.state` |
| 命名 / 关节解析 | `core.spec.naming` / `core.spec.resolution` |
| 绘图 / PNG / 像素质量 | `core.media.draw` / `core.media.png` / `core.quality.pixels` |
| 渲染 | `core.rendering` |

可变状态赋值、mock 和 reload 均指向定义模块，不通过根目录门面。

## 改代码时的硬约束

- **使用子包入口**：不在 `core/` 根目录新增实现文件或兼容门面；保留
  `core.audio` / `core.rig` 包级 API，内部引用使用上述模块位置。
- **mock 要指向定义模块**：实现下沉后，`patch("core.audio.X")` 这类目标要改成真正
  定义该函数的子模块，否则 patch 静默失效。
- **契约检查扫源码**：跨层契约测试从 `remotion/` 源码里扫 draw 分支，渲染器文件
  增删后不需要改测试，但**不要**把分支搬出 `remotion/` 目录。
- **不要覆盖用户账本**：测试应使用隔离的 manifest 或 `tests.helpers.preserve_manifest()`；
  不要用 `git checkout` 覆盖测试前已有的未提交账本改动。
- **不触发真实计费调用**：所有验证走 mock 或 `--fixture`。
