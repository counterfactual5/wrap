# 待办 / Next round

登记下一轮要做的改进。**这些都不在已完成的修复批次内**——单独一轮、单独提交，
不要和"门禁诚实性 / 跨语言契约 / 规格校验硬化"那批混在一起。

---

## 已完成（仅供追溯，勿重复做）

### subprocess timeout 加固 —— 完成于 `82a35b6`

生产代码里 38 处 `subprocess` 调用原本没有 `timeout=`。ffmpeg、`npx remotion render`、
macOS `say` 一旦挂死，流水线会无限阻塞，没有诊断信息，只有一个永远不返回的进程。

现在预算集中在 `core/runtime/timeouts.py`，分两层：

| 常量 | 值 | 用途 |
|---|---|---|
| `PROBE_TIMEOUT` | 60 s | ffprobe 读元数据 |
| `EXTRACT_FRAME_TIMEOUT` | 180 s | 抽一帧成素材 |
| `LOCAL_TOOL_TIMEOUT` | 300 s | 本地 ffmpeg 转码/测量 |
| `RENDER_BASE_TIMEOUT` | 900 s | 渲染基准（`render_timeout_seconds` 按镜头长度放大） |
| `SAY_BASE_TIMEOUT` | 120 s | macOS `say` 基准（`say_timeout` 按文本长度放大） |
| `NETWORK_FETCH_TIMEOUT` | 120 s | edge-tts 网络下载 |
| `VOICE_LIST_TIMEOUT` | 20 s | `say -v '?'` 查可用声音 |
| `STAGE_TIMEOUT` | 3600 s | `run_stage` 派生的阶段子进程 |

两个特例：`core/quality/pixels.py` 的帧读取是**流式**的（逐帧读 ffmpeg 的 stdout），
`timeout=` 对它无效，改用 watchdog 杀进程，再据 returncode 判定为超时；
渲染驱动的超时单独捕获——渲染器卡死既不是"工具缺失"也不是"缺帧"。

### ease 两端对称 —— 完成于 `82a35b6`

`core/rig/kinematics.py` 的 `apply_ease` 对名单外 ease 抛 ValueError，
`remotion/kinematics.ts` 的 `applyEase` 曾静默回 linear。现已对齐：TS 侧同样抛错，
并导出 `EASES`（与 `core/spec/constants.py:ANIM_EASES` 同源），词表漂移可被检测。

---

## 待办

（本轮暂无新登记项。）

新发现的问题记在这里，每条单独一轮、单独提交。

---

## 3. 接续检查只验声明、不验画面（独立视觉评审发现 · 待做）

**问题**：`verify-continuity` 的 PASS **不读任何渲染帧**。
`core/rig/verification/continuity.py` 与 `stagecraft.py` 只读 spec 的**声明字段**——
backdrop 身份字符串、由 `anim` 通道求值出的角色 x/y/opacity。
它验的是「**声明的一致性**」，不是「**画面的连续性**」。

**后果（实测于 wrap-exp-03）**：该片真正该被拦下的三件事，一条都没测到：
1. 接缝的**主体尺度跳变 1.29×**（用"门襟纽扣行距"这一衣物固有物理长度量得 55.9 px → 43.25 px）——
   观众读作"跳到别处"；
2. 接缝的**瞬时电平空洞 0.30 s**（RMS 从 −16 dBFS 掉到 −34 dBFS）——`silencedetect` 的
   −45 dB 阈值看不见它；
3. **尾段 0.53 s 死帧**——`freezedetect` 的 `n=0.001` 阈值测不到（用 `n=-60dB` 立刻报出）。

**修法方向**：另加一个**读像素**的接续检查，与 `verify-continuity` 并列，至少覆盖：
- 接缝两侧的**主体尺度**（可用物体自身的物理尺量，如纽扣行距；或模板匹配 + 归一化自检）
- 接缝的**瞬时电平**（逐窗口 RMS，不只靠 silencedetect 的绝对阈值）
- **尾段死帧**（用比 `n=0.001` 灵敏得多的阈值，或直接比较帧间 PSNR）

**注意**：别把这三项塞进现有 `verify-continuity`——它现在的语义（验声明）是自洽的，
塞进去会让"声明不一致"与"画面不一致"两种失败混在一起，无法区分。

## 4. gates 文件把「跳过的检查」记成「通过」

`stages/04_gate.py` 在 `spec.frame_freeze is True` 时**完全跳过** freezedetect，
却仍把 `{"id": "freeze", "metric": "freezedetect", "value": 0, "pass": true}` 写进
gates 文件 —— **与真实通过不可区分**（没有 `skipped` 标记）。

修复方向：跳过时写 `"pass": null, "status": "skipped"`（或加 `skipped: true`），
让下游能区分"测过且通过"与"没测"。判定逻辑本身（`frozen = []` → 不 FAIL）是对的，
只是**报告**丢了信息。

## 5. `purity` 门禁对 `blend:normal` 的层是常数

`stages/02_prepare.py` 对 `blend == "normal"` 且无 cutout 的层**硬编码 `purity = 1.0`** 并
跳过测量。于是"过 purity 门"对满幅不透明背景**恒真**（wrap-exp-02 实测：引擎自带 ring 定义
在备图外圈量得 0.0000，门禁却报 1.0）。

修复方向：要么在报告里显式标注该门禁**未测量**（与 `frame_freeze` 同类问题），
要么把"满幅不透明背景"这一事实作为**另一条**可验证的门（例如"源资产边缘是否已被裁净"），
而不是让 purity 恒真。

## 6. 背板（最底层）图层的 opacity 压暗在交付成片里不生效（wrap-exp-02 实测 · 待做）

**问题**：图层级的 `anim.opacity` 走的是 CSS `opacity`（`remotion/Shot.tsx:55`），
它降低的是元素的 **alpha**。而交付链是 PNG → `yuv420p`，**alpha 被编码丢弃**。

- **上层**图层不受影响：面板盖在厂房上时，`opacity` 会与下方不透明画面合成，
  实测帧 272→276 面板暗部 R 值 50.6 → 63.7，淡出是实的。
- **最底层**图层（背板）下面没有不透明画面可合成：实测帧 340 的 PNG
  **alpha 均值 120.26（≈0.47）、RGB 与未压暗时几乎相同**（103.16/66.85/30.37
  vs 104.85/67.03/29.29），而交付 mp4 的 `YAVG` 从头到尾 78.1 → 77.8 ——
  **压暗没有发生**。opacity=0 时元素被整体跳过，RGB 归零，所以只有「全黑」这一档
  在成片里看得见（这正是换版暗场能用的原因）。

**修法方向**：引擎应当把「背板层的 opacity < 1」**显式拒绝**（no implicit defaults），
而不是静默交付一个没有压暗的成片；或者在 S3 合成时把 PNG 统一合成到不透明底色
（当前是直接丢 alpha）。项目侧的正确写法是：压暗必须是自己的一层，把暗度烘焙进
填充色 `rgba()`（wrap-exp-02 的 `veil` 组件即此写法）。
