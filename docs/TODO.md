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

## 9. 经复核：`24fps` 视频 `trim` 并非 1.25× 错位（`S2` 已按镜头帧率重编码）—— 已核实关闭

**原登记假设**（`37d54eb`）：认为 `Shot.tsx` 用镜头帧率（30）乘 `trim` 秒数会让 `24fps` 视频落到 1.25× 处（如 `1.55 → 1.94 s`），建议改用源帧率 `24fps` 换算 `trimBefore`。

**像素级复核结果**：经逐像素绝对差实测 `wrap-exp-03` 的 `build/frames/scramble/00001.png`（`trim: [1.55, 6.583]`）：
- `stages/02_prepare.py` 在 S2 **已经用 `-r {FPS}` 把 24fps 源视频重编码成了 30fps 的 `build/prepared/{shot}/{asset}.mp4`**；
- Remotion 消费的是该 `30fps` prepared 文件，实测 `00001.png` 精准对齐 prepared 第 47 帧（`47/30 = 1.567 s`，MAD=1.64），对应原始 24fps 视频第 37 帧（`37/24 = 1.542 s`，MAD=9.90）——**没有 `1.94 s` 的 1.25× 偏差**。

因此**不可**把 `trimBefore` 改成按源帧率 `24` 换算（在 S2 输出 `30fps` prepared 剪辑的前提下那样反而会切到 `37/30 = 1.233 s` 造成真错位）。若未来要免重编码直通原始 24fps 素材，届时再与 S2 帧率契约一并改造。

---

### `clip_audio` 截断丢末帧 + 底层合成无视 `canvas.bg` —— 完成于 `<本次提交>`

1. **`encode_mp4` 丢帧**：`core/rendering/encoding.py` 原先传给两轮 `loudnorm` 的时长被 `round(shot_seconds, 4)` 向下截断（例如 `151 / 30 = 5.033333 s` → `5.0333 s`），经 AAC 1024 采样量化后音频轨比视频少数十微秒，再叠加终端 `-shortest` 导致 ffmpeg 直接砍掉最后一帧视频（151 帧变成 150 帧），而 S4 未检 `nb_frames == durationInFrames`。
   现已在混流阶段通过 `[2:a]apad[a]` 补齐音频尾零再配合 `-shortest`，确保严格由 `[v]`（精确 `durationInFrames` 帧）定界；`core/audio/mastering.py` 在 pass 2 输出前确保父目录存在（修复全新目录无 `.tmp/` 时失败）；`core/audio/metrics.py` 一并探测 `nb_frames`，`stages/04_gate.py` 新增 `video_frame_count` 门禁。
2. **`canvas.bg` 穿透**：底层不透明底板不再写死 `color=c=black`，改读 `spec["canvas"].get("bg")`（有效 `#rrggbb` 转 `0xrrggbb`，缺省回落 `black`）。
3. **接缝音频空洞与单位**：`core/assembly/timeline.py` 的 `_seam_audio_hole_detail` 改用单次 PCM 解码 + `250ms` 滑动窗同时扫描切点前/中/后（`[cut-0.45s, cut+0.45s]`），抓出此前漏检的“镜头 1 尾端空洞”并避免长窗平均稀释；修正 `black_with_sound` 将短窗 RMS 错标成 `LUFS` 的文本问题（改回 `dBFS`）。
测试：`tests/stages/test_encode_opacity.py`、`tests/stages/test_compose_video_sync.py`、`tests/core/test_seam_audio_hole.py`、`tests/core/test_black_gate_sensitivity.py`、`tests/core/test_audio_gate_honesty.py`。

### 帧序列像素格式混排 → 编码随机丢帧，成片与帧母版失去绑定 —— 完成于 `<本次提交>`

**问题**（wrap-exp-02 终版独立评审 M1 实测）：Remotion 只给**带透明度**的帧写 alpha 通道，
其余帧写 RGB —— 于是一个镜头的帧序列会**混排两种颜色类型**。PNG 解码器在流中间换格式，
ffmpeg 因此**重配置整个滤镜图**（日志原文：`Reconfiguring filter graph because video parameters
changed to rgba(pc, gbr)` → `rgb24(pc, gbr)`），overlay 的帧同步被重置，编码器在切换点吐出
**纯底板黑帧**，而且**每次运行吐出的位置和数量都不一样**。

同一批 360 帧、同一条 ffmpeg 命令，5 次编码测得的纯黑帧（合成帧号）：

| 运行 | 纯黑帧 |
|---|---|
| 交付成片 | 278, 279, 280 |
| 重跑 1 | 139, 140, 141, 147, 148 |
| 重跑 2 | 1, 2, 140, 141, 146, 147, 148, 150, 151, 279, 280 |
| 重跑 3 | **278, 279, 280**（与交付成片逐帧一致） |
| 重跑 4 | 140, 141, 146, 147, 148, 279, 280 |

帧母版本身只有 4 帧全透明（合成帧 140/141 与 279/280，正是 spec 的 opacity=0 关键帧）。
于是**交付的 mp4 不再是它自称的那批帧的编码结果**。评审据此判第 ④ 条不满足，
而"成片与帧母版出自不同渲染批次"的怀疑**机制上是错的**（重跑 3 与交付成片完全一致）。

**修法**：S3 在渲染后、编码前把帧序列**归一为单一像素格式**（RGBA）。像素不变
（RGB 逐字节照抄，alpha 有则保留、无则补不透明）；实测全片 360 帧逐帧均值亮度差异 **0**
（差异 > 0.05 的帧数 = 0），耗时 33.5 s（360 帧 1080×1920）。归一后连跑 3 次，
纯黑帧集合恒为 `{140, 141, 279, 280}` —— 与 spec 的 opacity=0 关键帧完全一致。

**同时补上评审点名的盲区**：manifest 只把"帧目录 ↔ 登记"绑在一起，**从不比较 mp4 的像素与帧**，
所以这种"丢帧的成片"能通过全部质量门禁。现在 S4 增加 `master_match` 门禁：把帧母版按
编码器同样的方式合成到画布底色上，与成片逐帧做差，取最大 mean|ΔY|。正确渲染实测 ≤ 1.5
（编码器自身的量化），出问题的帧是 35–61，阈值取 6.0；没有帧母版时如实记
`pass: null / status: not_measured`，不冒充通过。
测试：`tests/core/test_frame_format_normalization.py`。

## 10. 接缝音频洞门禁看不见"短而深"的下陷（原登记的前提已被实测推翻 · 已修）

**原登记的前提被推翻**：本条原先登记的是「画面与音轨的 trim 落在不同的时间点」。
实测（10 ms RMS 包络互相关，corr = 0.9884）：镜头 2 的音轨起点落在 prepared 文件的
**1.570 s**，正是画面那一侧（prepared 第 47 帧 = 47/30 = 1.567 s）。
**画面与声音本来就在同一个窗口上裁剪** —— 反复调 trim 躲不开的那个坑不是这个原因。

**真正的原因有两条**：

1. **素材自身的淡入低谷正好落在剪切点上**（素材与切点的选择问题，不是引擎缺陷）：
   prepared 音轨在 1.10–1.65 s 处于 −27…−33 dBFS，1.70 s 才回到 −21 dBFS；
   剪切点取在 1.567 s，接缝处于是出现 16 dB / 90 ms 的下探—回升。
2. **引擎的门禁看不见这种洞**（真实缺陷）：`seam_audio_hole` 用 250 ms 滑动窗取最小值，
   90 ms 的洞被平均掉了 —— 实测该窗的 RMS 只比切前低 **1.9 dB**，门禁因此写下
   `value: 0, pass: true`，而独立评审实测到 16 dB / 90 ms 的下探—回升。**门禁报了假 PASS**。

**修法**：`_seam_audio_hole_detail` 改用 **20 ms 短窗 / 10 ms 步进**，并加三条判据：
洞必须比切前深 ≥ 6 dB、必须回升到切后 3 dB 以内（不回升的是淡出不是洞）、
必须持续 ≥ 40 ms（单个噪声窗口不算洞）；**跨切点两侧都低且 ≤ 200 ms 的下探**判为正常的
交叉淡化，放行。实测：90 ms / 16 dB 的洞（切后、切前各一例）现在都会被抓出来并给出区间，
80 ms 的正常交叉淡化仍放行，0.45 s 的长洞与"一直低下去"的淡出判定不变。
测试：`tests/core/test_seam_audio_hole.py`（新增两条短洞用例）。

**素材侧怎么躲**：接缝的下探来自素材自身的淡入，切点必须落在它**之后**；
或者在时间轴上给该镜头一个短交叉淡化（引擎目前不提供，需要时另行登记）。

---

### 渲染器漏帧 → 成片出现黑洞 —— 完成于 `<本次提交>`

Remotion 用 `<video>` 元素画视频层。元素偶尔会**交不出它被要求的那一帧**：元素空着，
图层留下一块透明缺口，编码器把缺口合成到画布底色上 —— 成片里就是一个**黑洞**，
而配乐还在下面照响。

实测（真实 H3 素材，180 帧，视频层铺满画布）：第一次渲染在第 89、90 帧留下缺口，
**同一份规格重渲后一处都没有**。缺陷是渲染器的竞态，不是规格的性质 ——
所以"再跑一遍流水线"不是修复，只有守卫才是。

现在 S3 有了一道空洞守卫：

| 步骤 | 做什么 |
|---|---|
| 量 | 逐帧读帧母版的 alpha（画布上的平均 alpha），一次 ffmpeg 扫描 |
| 判 | 与规格在该帧的承诺比：视频层给出的最强下界（不透明度 × 矩形面积） |
| 退 | 低于承诺 5 % 以上 = 空洞；重渲（竞态不可复现，第二次通常干净） |
| 拒 | 连续 3 次仍有空洞 → **S3 硬报错，这一镜不会被编码**；门槛绝不为了放行而下调 |

规格有意淡出的帧不算空洞：承诺随不透明度一起降；`fit: "contain"` 的片在矩形里留黑边，
矩形不是它覆盖的面积，同样不参与承诺。

新文件 `core/rendering/holes.py`（守卫）与 `core/rendering/compose.py`（流程）；
渲染器是参数，测试不需要浏览器也不产生计费调用。
测试：`tests/core/test_render_holes.py`。

---

## 待办

新发现的问题记在这里，每条单独一轮、单独提交。

### `accent_color_ratio` 量的是整幅画面，分不清"图形"与"素材"

**问题**：该指标在**整幅画面**上数匹配色的像素占比，取逐帧**中位数**。当片子的图形元素
（面板、锈色条）只占画面一小块时，这个数字**测的是素材本身的暖调**，不是图形的存在：

- 旧结构（一块全幅面板 + 粗条）：实测 0.0368，门槛 0.025 —— 图形主导，指标有意义。
- 新结构（一台小仪器 936×440，锈色只在 4px 顶线 / 14px 条 / 字距标题上）：
  实测 0.015035 / 0.016550 —— **素材暖调占了绝大部分**，门槛 0.025 不可达；
  把门槛降到 0.012 之后，这道门禁就挡不住"锈色图形整体消失"了（素材的暖调还在）。

**为什么现在没修**：这要改引擎的指标语义（给 `accent_color_ratio` 加一个
`region` 参数，像 `subject_motion_ratio` 那样只测指定区域），属于规格层的契约变更，
不是一轮能顺手带上的事。项目侧本轮的做法是**按实测校准门槛并在规格里写明理由**
（`wrap-exp-02/spec/factory-run.poster.json` 的 `gates[].calibration` 字段），
**没有把这个数字当作"已通过"来引用**。

**待做**：给 `accent_color_ratio` 加 `region`（像素矩形）支持，并让门禁在
"图形层未覆盖到测量区域"时如实记 `pass: null / status: not_measurable`，
而不是拿整幅画面的中位数充数。

---

## 3. 接续检查只验声明、不验画面（独立视觉评审发现 · **部分完成**）

**问题**：`verify-continuity` 的 PASS **不读任何渲染帧**。
`core/rig/verification/continuity.py` 与 `stagecraft.py` 只读 spec 的**声明字段**——
backdrop 身份字符串、由 `anim` 通道求值出的角色 x/y/opacity。

**已做**（本次）：新增两条**读像素/读音频**的接缝检查，挂在整片门禁上
（`core/assembly/timeline.py`）：

- `seam_audio_hole`：**剪切点处声音下探后回升** = 洞（观众看到画面缺口而配乐还在响）→ 判失败。
  实测来源：一次 17 dB 阶跃 + 0.45 s 下陷 + 1.5 s 回升，分段平均的响度数字看不出来。
  短窗 integrated loudness 不可靠（需要门限块），故用短窗 RMS。
- `black` / `black_with_sound`：见第 8 条（整片黑场的检测下限降到 0.05 s）。

同时把 **S4 逐镜的 freeze 门槛从 0.5 s 降到 0.2 s**——原来的门槛下，
一段 0.29 s 的尾段死帧（9 帧）压根不会被报出来，而门禁仍写「0 frozen segment(s)」。
实测来源：wrap-exp-03 的尾段死帧。

**仍待做**：接缝两侧的**主体尺度**检查（用物体自身的物理尺量，如纽扣行距，
或模板匹配 + 归一化自检）。这一条没有现成的通用算法，且它要判的是"画面跳变是否成立"
而不是"跳变是否存在"——刻意换景别是合法的，所以判据必须是**相对镜头自身变化量的离群度**，
而不是绝对阈值。

