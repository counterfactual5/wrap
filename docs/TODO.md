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
