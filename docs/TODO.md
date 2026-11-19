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

## 7. 资产下载没有超时（wrap-exp-03 实测 · 待做）

`core/generation/images.py` 的 `download_file()` 用 `urllib.request.urlretrieve(url, target_path)`，
**没有 timeout**。本轮实测：H3 视频下载第一次只拿到 192017/2567341 字节就断在连接上
（`retrieval incomplete`），靠函数的 3 次重试机制救回；同一轮里还有多次
`ECONNRESET` / `UND_ERR_CONNECT_TIMEOUT` 的 API 调用失败（引擎的 connector 重试扛住了）。

问题不只是"下载慢"：`urlretrieve` 在连接半死不活时**可以无限期挂着**，
而整条 S1 阶段是卡在这个调用上的——流程会停在那里，没有诊断信息。
（`core/runtime/timeouts.py` 的超时预算覆盖的是 subprocess 调用，这里是进程内的 urllib 调用，没被覆盖。）

**修法方向**：给 `urlretrieve` 换成带 `timeout=` 的分块读取（`urlopen` + `read(chunk)`），
并把"下载不完整"当成**可重试的错误**而不是成功的文件——现在第 252 行的检查只验证
"文件存在且非空"，一个截断的 184 KB 文件会被当成有效资产通过（随后在 prepare/合成阶段
以别的形式炸掉，错误信息离根因很远）。至少要核对 `Content-Length`。

## 8. 整片 blackdetect 门禁看不见短黑场（假 PASS · wrap-exp-03 实测 · 待做）

`core/assembly/timeline.py:282` 的整片黑场检查用
`blackdetect=d=0.2:picture_black_ratio_th=0.98:pixel_black_th=0.02`。
**`d=0.2` 是最小黑场时长**：30 fps 下不足 6 帧的落黑**根本不会被报出来**。

实测（wrap-exp-03 收官评审）：接缝处连续 3 帧纯黑（全局帧 178/179/180，灰度均值 0.00，
`blackdetect` 实测 `black_start 5.933333 / black_end 6.033333 / black_duration 0.1`），
而 `build/gates_full_commodity-journey.json` 记的是
`{"id":"black","metric":"blackdetect","value":0,"bound":"0 intervals","pass":true}`——
**一次假 PASS**：门禁报"没有黑场"，实际有 100 ms 全黑，且这 100 ms 里声音仍在响
（−16…−30 dB），构成声画错位。这与本文件第 4 条（跳过的检查被记成通过）同类，
但更糟：它不是"没测"，而是"测了，门槛太高，把要抓的东西放过去了"。

**修法方向（三选一，或并行）**：
1. 把最小时长降到 2–3 帧（`d=0.06`）——代价是更多**刻意**的短落黑也会被判 FAIL，
   所以必须同时给"允许落黑"的表达方式（现在只有整片级的 `allow_black=true` 逃生口，
   无法只允许某一处）；
2. 增加一条**声画一致性**检查：画面黑而声音非静音的区间一律算失败——
   这才是"接缝黑场"真正该被禁止的理由（不是黑场本身，而是黑的时候还有声）；
3. 在门禁产物里区分"未发现黑场"与"黑场短于检测下限"（例如同时报告最短落黑时长），
   让"0 intervals"不再等于"画面没有黑过"。
