# 待办 / Next round

登记下一轮要做的改进。**这些都不在已完成的修复批次内**——单独一轮、单独提交，
不要和"门禁诚实性 / 跨语言契约 / 规格校验硬化"那批混在一起。

---

## 1. subprocess timeout 加固

**问题**：生产代码里 35 处 `subprocess.run` 没有 `timeout=`。ffmpeg、`npx remotion render`、
macOS `say` 一旦挂死，流水线会无限阻塞，没有诊断信息，只有一个永远不返回的进程。

**分布**（`core/` + `stages/` + `pipeline.py`）：

| 文件 | 处数 |
|---|---|
| `stages/02_prepare.py` | 6 |
| `pipeline.py` | 5 |
| `core/audio/metrics.py` | 5 |
| `stages/05_inspect.py` | 3 |
| `core/audio/tts.py` | 3 |
| `stages/04_gate.py` | 2 |
| `core/audio/shot.py` | 2 |
| `core/audio/mastering.py` | 2 |
| `core/assembly/timeline.py` | 2 |
| `core/rendering/video_frames.py` | 1 |
| `core/rendering/remotion.py` | 1 |
| `core/rendering/encoding.py` | 1 |
| `core/media/fingerprints.py` | 1 |
| `core/generation/images.py` | 1 |

**要点**：

- `core/rendering/remotion.py` 的 `npx remotion render` 是最长的一条——渲染一整段视频，
  超时必须给足（按镜头时长估算，不能拍一个固定值）。
- `core/audio/tts.py` 的 `say` 同理：TTS 时长随文本长度变化。
- 超时要作为**独立错误**抛出（区别于"命令失败"），让调用方能区分"超时"和"返回非零"。
- 已有的 `timeout=`（如 `core/assembly/timeline.py` 的 `extract_frame_asset` 用 180）
  不要动。

**验收**：每处补上 timeout；构造一个会挂住的命令，确认抛出的是超时错误而非挂死。

---

## 2. ease 不对称：Python 抛错 / TS 静默回退

**问题**：同一套缓动契约，两端对"名单外的 ease"处理不同。

- `core/rig/kinematics.py` 的 `apply_ease`：`raise ValueError(f"unknown ease {ease!r}; ...")`
- `remotion/kinematics.ts` 的 `applyEase`：`default: return t` —— 静默当作 linear

**当前不可达**：`core/spec/channels.py` 的 `validate_anim` 拒绝一切不在 `ANIM_EASES` 里的
ease，所以正常管线两边都不会碰到名单外的值。

**但会咬人**：`remotion/index.tsx:6` 的注释写着 spec "already validated"——而
**Remotion Studio 预览恰恰绕过这条路径**。`npm run studio`（`remotion studio
remotion/index.tsx`）直接读 props 文件，不经过 `load_spec` / `validate`。用 Studio 预览
一份旧 props、或手工编辑过的 props 时，Python 侧会报错、TS 侧会静默按 linear 渲染，
两端表现不一致，且 TS 侧不会有任何提示。

**修法**：让 TS 的 `default` 分支与 Python 一致——抛错并指明合法的 ease 名单。
`remotion/spec.ts` 已有 `Ease` 联合类型，可在 TS 侧复用同一份名单。

**注意**：改 TS 的 `applyEase` 会影响 `evalBaseAnim` / `channelValue` 的所有调用方，
必须确认 Studio 预览路径下抛错能给出可读信息，而不是一个白屏。

---

## 两条的关系

同属"跨语言契约 + 失败要响亮"这一类，建议同一轮做完、同一提交。
和已完成的批次保持独立——那批已经推送并验证过，不要回改。
