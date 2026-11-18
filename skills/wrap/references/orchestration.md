# Authoring orchestration (distinct from engine S1–S5)

The engine compiles media; the agent protocol develops a film. The production
steps below are NOT additional CLI stages. Technical success does not imply
editorial or aesthetic success. Do not label a self-review independent.

### Runtime topology: probe capabilities, not host names

No host-specific documents are required. At the start of a production run,
inspect the current tool schemas and actual responses. Keep a run record in
`reports/runtime-probe.md`, not a permanent host capability catalogue.

| Tier | Selection rule | Execution |
|---|---|---|
| T1 · peer | Delegation works AND peers have a verified direct messaging path, with safe completion/wakeup and write-ownership handling | Director coordinates; authorized peers exchange bounded evidence directly |
| T2 · subagent pipeline | Delegation works; peer delivery absent, or present without verified completion/wakeup/write-ownership handling | Director dispatches roles and relays findings verbatim; preserve evidence and dissent; never claim peer delivery |
| T3 · serial | Delegation absent, unavailable, or user requests single-agent execution | Main agent executes roles sequentially; review is self-review, not independent approval |

Decision procedure (also applies without any environment documentation):

1. Inspect delegation, peer messaging, resume/wakeup, completion, cancellation,
   workspace sharing and image-viewing capabilities. Unknown is not supported.
   A parent-to-child follow-up tool alone does not prove peer messaging.
2. No delegation: T3. Delegation with no verified peer path: T2. Use the first
   real, small task to verify dispatch; no mandatory synthetic dispatch for T2.
   Missing resume does not force T3: re-dispatch with a self-contained handoff.
3. Only test T1 if schemas plausibly permit peer delivery. Use one bounded
   handshake, at most two probe instances and one send/reply round. The sender
   creates a nonce after dispatch and sends it via the peer channel; the
   receiver reports the nonce, sender and transport without a Director relay.
   Obtain real receipts from both sides when the host provides them; otherwise require a default-ON written acknowledgement from both instances and downgrade to T2 without it. Never block indefinitely;
   if the host cannot safely complete this test, stay T2. Count all probe
   instances/calls honestly; this is not a one-dispatch test.
4. Record observed/unknown capabilities, chosen tier and evidence. Cache for
   this run; recheck on tool changes or failures, not before every task.

**Switching hosts for T1 buys fidelity first; the speed effect is unmeasured.**
T1 removes the Director's relay step, so it can cut main-thread turns, and
resumable instances may allow more overlap — but the size of that gain is not
known: the earlier split (serial chain / dispatch latency / relay / render)
was an estimate, not a timed measurement. Do not quote percentages for T1
savings without recording dispatch, wait, relay and render times first. For
throughput, start with the levers that do not depend on the host: scale the
roster (see Production sequence), run research and script speculatively,
resume instances instead of re-dispatching, and batch relay rounds.

Failure downgrades apply to the affected exchange/task, not automatically to
all roles. Direct delivery failure → T2; unavailable delegation → T3. Record
which review lost independence. A timeout does NOT prove a writer stopped:
confirm termination before assigning the same write domain to another agent
or editing it in the main thread; otherwise stop that write domain and report.
Do not blindly repeat a known-failing operation. Respect tool/model budgets.

### Production sequence and dispatch

> The phase names in this table are orchestration steps, not engine stages.
> The engine's fixed pipeline is S0–S5 + judge (see the stage table); here
> "Script / Design / … / Delivery" label who-does-what in a production run.

Director orchestrates; subagents produce. The main thread does not author the
film itself — that is the difference between this pipeline and "just asking the
model to make a video", and also where the cost sits.

Default rule: **every task that can be executed is dispatched**. Director keeps
only this exclusively: scope, budgets, final design selection, integration,
gate execution, final visual verdict, delivery. Everything else is outsourced.

The one question per candidate dispatch:

> Does this spawn change **who does the work**, or **how we know it's good**?

- **WHO** — always dispatch; the dispatch itself is the work. Screenwriter
  writes the script; Art Director(s) visualise; Builders implement per disjoint
  files; Researcher gathers facts; the Film Director (one subagent) writes the
  creative treatment. Director does not sub-contract its judgement,
  but judgement ≠ writing.
- **HOW we know** — dispatch is conditional. A second checker is spent only
  when the evidence it produces changes the decision: a fresh eye that could
  catch what the author can't, or a parallel arm that produces options the
  main thread would not.
- **Film Director** — the subagent that writes the *creative treatment*
  (`reports/treatment.md`): how the film moves, cuts and breathes. It owns
  motion grammar per section, the pacing curve across the film, per-beat
  viewer intent (what the viewer should feel or notice at each beat
  boundary), transition logic, and the audio/silence policy. It **proposes,
  never decides**: Director approves, or returns it with tradeoff notes —
  one round. Skip for a single-shot brief (record the skip in one line, as
  with shot plan). It writes docs only; Builder and Director implement. In T3
  the main thread writes the treatment explicitly — skipping it removes the
  film's creative intent, not its production value.

**Subject-literalism guard — every treatment and every design must answer
one question in writing: *what is the single most iconic image of this
subject in the public imagination, and will this film let the viewer see it
at least once?*** Then verify the finished film against that answer in the
rendered review.

This is the failure mode the relay does not catch by itself. A chain of
specialists who each receive only the upstream document will each execute
correctly and still produce a film that misses the subject's signature image
— nobody in the chain is asked what the subject *looks like* to an outside
viewer, so the omission is invisible to every role. Measured: a shadow-puppet
film built by a full multi-role relay was praised for craft, then judged by a
blind reviewer as "never once an actual shadow on the lit screen" — the
defining image of the entire art form, absent while every documented beat was
implemented faithfully.

The guard is one line, not a style mandate: it names the image and checks it
is on screen. It does not forbid flat, monochrome, minimal or deliberately
unusual treatments — those remain valid answers as long as the signature
image is present. When the answer is "this subject has no single iconic
image" (some abstract or procedural subjects), the Director records that
judgement explicitly rather than inventing one.

Apply the rule to each segment; do not pre-fill a roster, do not dispatch for
show:

| Segment | Default | Escalate when |
|---|---|---|
| Script | Dispatch 1 Screenwriter (+ 1 fact reviewer **only if** the `kind` requires it) | Reviewer finds causal error → 1 resize/rewrite |
| Design | Dispatch 1 Art Director per candidate direction **only** if the design space is open; otherwise 1 | Ambiguous brief or two genuinely viable styles → +1 arm for comparison |
| Treatment | 1 Film Director — writes `reports/treatment.md`; Director accepts or returns with tradeoffs, one round; the treatment must name the subject's signature image and how it appears | Brief is a single shot → skip, record in one line |
| Shot plan | Director writes; skip if the brief is a single shot (state skip in one line) | — |
| Build | Dispatch builders per disjoint file domain; parallel when profitable | Any file-domain task that is non-trivial and has no owner |
| Render | Director runs render | — |
| Gates | Director runs gates; no subagent; fix loop only if failure — then dispatch the fix | Gate tells you *which file*; dispatch only that owner |
| Rendered review | 0 or 1 fresh Visual Reviewer, only if the render is novel / error-prone / adjudication-blocking | Authoring blind spot likely: unusual camera, POV, typography, or a prior near-miss on the same brief |
| Final review | 1 fresh reviewer (T1/T2); T3 = self-review, labelled | verdict == fail → rewire; needs-work → owner re-renders |
| Delivery | Director alone | — |

**SMALL-WORK FAST PATH.** One-line copy, one color/position/timing tweak, a
single-layer edit — Director handles these alone (run the gate, look at the
affected frame, ship), *because spawning a subagent costs more than the edit*.
This is the only place the default reverses. The line between "small" and
"not": does this edit change what the viewer takes away? If yes, it's work —
dispatch it.

**DECISION LOG.** Every skipped dispatch writes one line in `reports/` saying
why it was skipped. No silent omissions. Growing and shrinking the roster both
need a reason; free-riding needs none.

| Step | What dispatches itself | Advance condition |
|---|---|---|
| Brief | Director records audience, purpose, constraints and resource budget in `CONCEPT.md`; does not commission content yet | Objective and constraints are explicit; no compulsory reference artists/styles |
| Capability choice | Director self-probes (~5 min): records live media capabilities in `reports/tool-probe.md`, decides modality, does not generate; a separate scout role is not worth a dispatch — the person choosing the modality must make the call | Separate available, permitted, verified and chosen modalities; choose for the story, not a hardcoded tool priority |
| Research and script | Dispatch Screenwriter (+ Researcher **only when `kind` is scientific/educational and facts are load-bearing**; otherwise no Researcher); Director does not write the script in the main thread; may dispatch in parallel with Design exploration | `SCRIPT.md` exists; claims are sourced or explicitly labelled model-knowledge-unverified when `kind` requires auditing; progression and reading time work for the audience |
| Design exploration | Dispatch 1–2 Art Directors when design space is genuinely open; otherwise 1; may dispatch in parallel with Research and script | Subject-led visual intent articulated; differences concern visual storytelling, not only palette |
| Treatment | 1 Film Director writes `reports/treatment.md` — motion/pacing/transition grammar, per-beat viewer intent, audio policy, and the subject's signature image with where it lands; Director approves or returns with tradeoffs (one round) | Director cites accepted tradeoffs; Art Director work and the shot plan sequence against it; single-shot briefs skip |
| Proof and selection | **Styleframe gate**: render ONE frame of the most visually complex element (a character, a hand, any organic form) BEFORE building the animation. If it doesn't read correctly, fix the visual or redesign the approach — do not animate an unreadable shape for 525 frames. Director selects after this gate. | The styleframe reads as its intended object at delivery size; only then does Build begin |
| Shot planning | Director writes `reports/shotlist.md`; skip if brief is a single shot (record skip in one line) | Covers the script without inventing fixed shots/components/layouts |
| Build and compile | Dispatch Builders per disjoint file domain (parallel when profitable); Director integrates and runs S1–S5 | All in scope implement; real exit codes captured |
| Rendered review | 1 fresh Visual Reviewer when the render is novel / risky / adjudication-blocking; Director may self-check if a skip is logged | Reviewed artifacts passed; every defect has an owner |
| Quality refinement | Director identifies the weakest passage; dispatch one bounded refinement for that passage only; record pass/fail | Before/after compared; improvement may REMOVE text/texture/motion/objects |
| Final review and delivery | 1 fresh reviewer (T1/T2); T3 = self-review, labelled | All unresolved blockers are noted as such in `DELIVERY.md`; no silent pass |

**Parallel dispatch where dependencies allow.** Research and script and
Design exploration are both downstream of Capability choice and produce
complementary artifacts — what happens vs how it looks — with no cross-
dependency between them. Dispatch them in the same batch (Screenwriter +
1–2 Art Directors) instead of sequentially; this halves the pre-Treatment
timeline. Treatment is the merge point: the Film Director must evaluate
both and the Director must reconcile any conflict between narrative and
visual direction before accepting. If the design exploration requires
scripts that only exist after Treatment, that is a different analysis,
not a reason to serialize.

**Medium-suitability check — before choosing procedural components.**
Programmatic SVG/CSS excels at geometric subjects (grids, diagrams,
isometric structures, flat design) and fails at organic forms (hands,
faces, articulated bodies, flowing fabric). When the subject involves
organic forms and no image-generation backend is available, this is a
**medium mismatch**: either find an authorized image source, simplify the
subject's visual language to work with geometry, or accept that the
organic element will read as a symbol rather than a depiction. Do not
discover this after rendering 525 frames — check it at the styleframe
gate above.

### Zero-template quality contract

`DESIGN.md` defines THIS project's visual intention and observable criteria:
what the viewer should notice, understand and feel; visual hierarchy; temporal
rhythm; why this treatment suits the subject; and which failure would undermine
it. References can clarify a decision but are optional, not a quota.

There are no universal requirements for textures, gradients, shadows, depth
layers, font-weight ratios, subject coverage, palettes, component counts or
ornament. Flat, monochrome, typographic, photoreal and deliberately static
approaches are all valid. More detail is not necessarily better. Review the
render at delivery size and inspect motion as well as isolated frames.

Require a project-specific overall-quality item in `spec.checklist`, alongside
comprehension and technical checks — and `factual accuracy` **only when `kind`
is scientific or educational** (for narrative/mood films, storytelling and
calibration replace the fact check; don't bolt on a science audit the brief
never asked for). Evaluate it with visible evidence, not by counting
decorative techniques. A metric is a diagnostic, not an aesthetic objective.
Do not add particles, camera drift
or breathing solely to satisfy freeze detection. For intentional holds,
document the intent before opting out via `frame_freeze`; record the skip,
check duration/readability, and never describe that test as passed.

### Bounded communication and independent decisions

- Script reviewer ↔ writer, factual reviewer ↔ researcher/writer, design
  reviewer ↔ design authors, Film Director ↔ Director: ask for evidence and
  allow accept/object replies; the treatment exchange is one round.
- The factual-reviewer exchange runs **only for `kind ∈ {scientific, educational}`**;
  the narrative-reviewer runs for all kinds.
- A design comparison allows each author one response round. Other local
  review/fix exchanges allow at most two rounds; factual clarification one.
- **Fix verification re-renders the whole element, not the fix point.**
  Verifying only the changed property invites silent regressions elsewhere in
  the same element (measured: a typography fix that swapped an SVG-invalid
  HTML tag destroyed every CJK heading in the frame while the fixed property
  itself rendered perfectly — both author and reviewer missed it checking
  only the fix). After any fix, the verifier re-checks the full element
  (text present and intact, layering, positioning) on the re-rendered frame.
- Rendered reviewer routes findings to the original owner within the existing
  write domain. T1 sends directly; T2 relays through Director; T3 records self-review.
- First reviews use brief, criteria and artifacts, not the author's defensive
  account or previous verdict. AFTER the independent report, discussion may
  resolve questions. Final review receives current artifacts and required
  intent/constraints, not lobbying or a preselected verdict.
- Never invent an author's answer, impersonate another agent or call a quoted
  proposal an actual exchange. Reuse an instance only through the real session
  parameter; placing an ID in message text does not resume it.
- Reviewer reports pass / needs-work / blocked with evidence; Director selects
  direction and records accept/reject reasons. Neither can erase unresolved
  evidence by vote. Reviewers read project files but write only their report
  when authorized (otherwise return text for Director to save).

### T1/T2/T3 timing and cost reporting

This experiment did not record wall-clock timings, and the timing/savings
claims in ## Runtime topology remain unmeasured. When running a multi-agent
production below on this engine, record the following in `reports/PROCESS.md`
so claims can be evaluated later:

- **T1 peer path** (when delegation works AND peers have a verified direct
  messaging path): record `dispatch_ms`, `wait_ms`, `relay_ms`, `render_ms`
  per stage. Use the measured numbers to compare T1 vs T2 on the same brief
  and budget. Claim savings only after recording these values.
- **T2 subagent pipeline** (delegation works, no peer path): record how many
  dispatches happened and actual wait time per stage. The reported split
  (dispatch latency / relay / render) is an estimate, not a measurement. If
  you measured it, say so; if not, say so.
- **T3 serial**: record dispatch_ms=0, wait_ms=0, relay_ms=0. Do not infer
  savings without measuring.
- **Compare fairly**: same brief, same budget, same model and tools; freeze
  script/design/assets if comparing rework paths. A single pair supports
  observations, not claims with numbers. Goal: verify or delete the claim
“T1 cuts main-thread turns” with real measurements.

### Budgets, provenance and truthful reporting

- Default local rework budget: two rounds per issue; at most three build/render
  attempts for a production milestone unless the user sets another budget.
  These are shared counters, not fresh allowances per role. Exhaustion means
  stop and report; renaming a task or adding a reviewer does not reset them.
- Preserve project assets and user edits. Production does not edit the engine.
  Compare source snapshots or scoped diffs before/after, excluding generated
  outputs, caches and dependencies; report differences rather than reverting
  unrelated user work. This rule does not prohibit explicitly requested engine maintenance.
- Tool availability is not permission to spend. Respect explicit cost/privacy
  constraints; otherwise establish a budget before paid calls. Do not erase
  capability declarations to simulate absent tools or claim code is generated media.
- Keep raw findings, actual replies, dispatch IDs, artifact versions and gate
  results in `reports/`. Reports are evidence, not a tamper-proof script ledger.
- Check gate exit codes directly (or a wrapper preserving the exact return code),
  never a pipe/filter's exit code. A stale render invalidates its visual review.
- Delivery states actual tier(s), sources, costs/calls, evidence inspected,
  self-review/independent-review status, skips, unresolved issues and limitations.
  Never claim full playback when only sampling stills, or model use without calls.
- For comparisons, distinguish an end-to-end workflow comparison (same brief,
  tools/model/budget; designs may differ) from a transport-only experiment
  (freeze script/design/assets too). Use fresh sessions and blind review.
  Revisions informed by a previous failure are NOT independent A/B trials;
  a single pair supports observations, not a causal or statistical claim.

Part of the wrap skill — see skills/wrap/SKILL.md. The engine stages it references (S0–S5 + judge) are documented there; treat step names here as orchestration phases, not CLI stages.
