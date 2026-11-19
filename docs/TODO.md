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

### gates：跳过的 / 不适用的检查不再记成通过 —— 完成于 `<本次提交>`

两条门禁行曾经对**没有发生过的测量**说"通过"：

- `stages/04_gate.py` 的 freeze 行：`spec.frame_freeze = true` 时跳过 freezedetect，
  却写下 `{"id": "freeze", "value": 0, "pass": true}` —— 与"测过且干净"不可区分。
- `stages/02_prepare.py` 的 purity 行：满幅不透明背景（`blend: normal` 且无 cutout）
  **根本没有键可测**，S2 却硬写 `purity = 1.0`，S4 再拿它跟 0.98 比 → 恒真。

现在两者都写 `pass: null`，并用 status 区分「没测」（`skipped`）与「不适用」
（`not_applicable`）；S2 的 prepared 行同时记 `purity_status`，S4 把不可测的层列进
`not_measured_layers`，不再让它们冒充被测过的数字。
测试：`tests/stages/test_gate_not_measured.py`。

### 背板图层的 opacity 压暗终于进了成片 —— 完成于 `<本次提交>`

Remotion 写出的 PNG 带 alpha 通道，而 S3 把它直接编成 `yuv420p` 时**丢弃了 alpha**：
背板层淡到 45% 的画面，在成片里是满强度的；只有 opacity 0（元素被整体丢弃）才读作黑。
现在 S3 先把帧合成到一张不透明黑底上再编码 —— 对没有 alpha 通道的视频来说，
半透明区域本来就该这么解释 —— 于是"屏幕上是暗的、成片里也是暗的"。
测试：`tests/stages/test_encode_opacity.py`（在修复前会失败）。

### 资产下载：超时 + 长度校验 —— 完成于 `<本次提交>`

`core/generation/images.py` 的 `download_file()` 用 `urllib.request.urlretrieve`：
**没有超时**（半死的连接可以把整个阶段挂死，且没有任何诊断信息），
而且它的"成功"不是成功——实测拿回 2567341 字节里的 192017 字节后，
落盘文件**非空**，旧的"非空即成功"检查放行，真正的爆点在很远的地方才炸。

现在改为：`urlopen(timeout=…)` + 分块流式读取 + **与 `Content-Length` 比对**，
不完整就报错重试，文件先写 `.part`、完整了才 `os.replace` 到目标路径。
超时常量进 `core/runtime/timeouts.py`（`DOWNLOAD_TIMEOUT` / `DOWNLOAD_CHUNK_BYTES`）。
测试：`tests/core/test_download_integrity.py`。

### 整片黑场门禁不再漏掉短落黑 —— 完成于 `<本次提交>`

`core/assembly/timeline.py` 的整片黑场检查用 `blackdetect=d=0.2`：**三帧落黑（30fps 下 0.1 s）
低于这个门槛，压根不会被报出来**，于是 gates 文件写下 `blackdetect: 0, pass`，
而画面上正是一个 100 ms 的洞 —— 实测接缝处 `black_start 5.933 / black_end 6.033`，
而门禁说"没有黑场"。同时那 100 ms 里**声音还在响**（−16…−30 dBFS），构成声画错位。

现在：`d=0.05`（两帧落黑就能看见 ✓）、解析出每段黑场的**起止与时长**并打印出来 ✓，
并新增一行 `black_with_sound`：**画面黑着而配乐还在响**的一律判失败 ✓
（这正是验收第 ⑦ 条"接缝处不得有静音洞"要查的东西）。
短窗的 integrated loudness 不可靠（需要门限块），所以用短窗 RMS 量洞里的电平 ✓。
测试：`tests/core/test_black_gate_sensitivity.py`。

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

