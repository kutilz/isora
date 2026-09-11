# Plan — Nav UX + Offline Maturation (post blind-user assessment)

_Date: 2026-06-23. Driven by direct assessment with 3 blind users. Reviewed via /plan-ceo-review (HOLD SCOPE)._

## What the users actually told us (ground truth)
1. **Pain #1 = latency.** It feels slow. Everything else is secondary.
2. **TTS is the right channel** — but they're used to **fast, accessibility-speed TTS** (screen-reader cadence).
3. **Core navigation must be 100% offline.** Online is for extras only.
4. **Announce cadence** = blend: speak **on change**, **always** on danger/near, plus **on-demand** full readout.
5. Object scope: **mature a small set first** (person + static obstacles), **standard COCO only**, test, then expand.
6. Utterance phrasing: no strong opinion → our call.

## Measured reality (device logs, 2026-06-15) — this re-aimed the plan
```
describe latency = button → [ gemini ~7,160ms ] → [ speech 5,500–10,600ms ] → done  ≈ 13–17s
```
- gemini round-trip is a steady **~7s** (can't atempo that — it's the cloud think).
- speech itself is **5.5–10.6s** because describe runs verbose `scene_verbosity="detail"`.
- word-cache hit-rate ≈ 0 (detail sentences too varied to repeat).
- **Nav chimes are already instant + offline** — they were never the main "lambat". The pain is **describe**.

## North star
**Fast, calm, fully-offline core navigation that talks like a fast screen reader; describe stays an online rich feature, just faster.**

## Device constraints
- riscv64, 1 core, 128 MB RAM (~56 MB free), no package manager → neural TTS out.
- gTTS is online-only → offline nav == pre-rendered WAVs. Any non-pre-rendered phrase offline = network = breaks #3.
- ffmpeg `atempo` present → speed up audio offline, zero new deps.

---

## Agreed decisions (from CEO review)
| # | Decision | Choice |
|---|----------|--------|
| D1 | Offline speech architecture | **Hybrid**: pre-render + atempo now; espeak-ng riscv64 as a time-boxed parallel spike |
| D2 | Review posture | **HOLD SCOPE** (harden, don't expand) |
| 1 | Announce gate | **One gate** — refactor `detection_gate` INTO `AnnouncePolicy` (single nav-speech decision-maker) |
| 2 | "Change" + danger | "Change" = new object OR grid-cell change OR **distance-tier change**; danger/near **re-announces on a timer** even when unchanged |
| 3 | Describe verbosity | **Keep `detail` default**; atempo carries the speed (~10s→~6s). Describe = online rich feature; word-cache focus stays on nav |
| 4 | Offline fallback | **Generic phrase + earcon** — missing WAV while offline never = silence |
| 5 | Distance signal | **Per-class coarse tiers (near/far) + ground-contact hint**, not raw global area |

Adopted recommendations (engineering-correct, tunable, veto anytime):
- atempo runs at **generation time** (pre-rendered WAVs), never in the 1-core playback path.
- **Single source of truth** for the object set (kill the `RELEVANT_LABELS` / `OBJECTS` / `_LABEL_ID` 3-way drift).
- atempo failure → fall back to normal-speed PCM, not silence.
- `AnnouncePolicy` logs each announce/suppress decision (field-tuning).
- Danger fast-path: `detection_min_streak_danger` (≈2) vs normal (3), so hazards warn sooner without regressing phantom-orang.

---

## Workstreams (HOLD SCOPE — re-aimed by the evidence)

### A. Describe latency (the measured Pain #1)
- **A1.** atempo pre-render for describe speech; tune rate 1.8–2.0x with an on-device intelligibility check (Indonesian gTTS).
- **A2.** Immediate "thinking" earcon on capture so the 7s gemini wait isn't dead air (cheap perceived-latency win). [TODO: downscale upload JPEG to shave gemini time.]

### B. Event-driven nav announce (calm + safe)
- **B1. `AnnouncePolicy`** (pure, TDD-first) — the single gate (Decision 1). Refactor `detection_gate.decide_announce` in. Emits on change (Decision 2); danger re-announces on timer; suppresses unchanged calm scenes; on-demand = full readout.
- **B2. Per-class distance tiers** (Decision 5) — near/far thresholds per class + bottom-of-box ground hint. Feeds B1's danger timer and "dekat" phrasing.

### C. 100% offline nav guarantee
- **C1. Phrase-coverage invariant test** — enumerate every `AnnouncePolicy` output (N objects × positions × tiers), assert a pre-rendered WAV exists. Build-time gate.
- **C2. Runtime offline fallback** (Decision 4) — generic "ada objek di [arah]" + obstacle earcon when a specific WAV is missing offline.

### D. Scope narrowing (mature small, then expand)
- **D1.** One canonical object-set map; narrow the announced set to the matured N (person + static obstacles, standard COCO). Tune conf/de-flicker for that set, test with users, then expand.

### E. espeak-ng riscv64 spike — parallel, time-boxed, **kill criteria explicit**
- Go/no-go on cross-compiling espeak-ng. **Abort if:** no working riscv64 binary in 1 focused day, OR RSS > 30 MB, OR cold-synth latency > 300 ms for a short phrase. Green → unbounded offline speech upgrade later. Not a dependency for A–D.

## Method
- **TDD (`/tdd`)**: `AnnouncePolicy.decide()`, `distance_band()`, `atempo_chain(rate)`, terse/phrase builders, and the phrase-coverage invariant are pure → test off-device first.
- **Before TDD:** get the existing suite green on the current (dirty, +1682-line) tree so a red test means *your* change, not pre-existing breakage.
- Deploy → live-tune via `POST /config` (atempo rate, announce timers, streak knobs) with the user in the loop.

## Sequencing
1. Stabilize tree (existing tests green) → A1 + B1 + C1/C2 (the latency+offline core).
2. B2 + D1 (distance tiers + scope narrowing) → user test round.
3. A2 polish; E spike in parallel throughout.

---

## Required CEO-review outputs

### NOT in scope (deferred, with rationale)
- Spatial/binaural earcons as the primary channel — assessment said TTS is most effective; revisit post-maturation.
- Offline scene *description* (vision) — gemini is online by nature; out of this phase.
- Reducing the 7s gemini round-trip beyond the JPEG-downscale TODO — separate online-perf track.
- Custom non-COCO classes (doors/stairs/path) — explicitly "after it's mature".
- Battery HAT / I2C telemetry — unrelated.

### What already exists (reused, not rebuilt)
- `detection_gate.py` (back-off) → folded into `AnnouncePolicy` (Decision 1).
- `area_ratio` + `is_danger` in `ai_engine.py` → extended into per-class tiers (Decision 5).
- `generate_audio.py` `build_audio_list()` (objects × positions) → reused for atempo + coverage test.
- `_ensure_pcm` ffmpeg shell-out → atempo filter drops in here (and the duplicated `_ensure_pcm_standalone`).
- `scene_verbosity` "sedang"/"detail" prompts → already built (we keep detail per Decision 3).
- pytest suite (`test_detection_gate`, `test_word_cache`, etc.) → TDD harness.

### Dream-state delta
Plan reaches: instant+offline nav, calm event-driven cadence, safe approaching-hazard re-announce, faster describe. Stops short of: <200ms world-to-ear (de-flicker + NPU bound), offline vision, spatial audio. Trajectory intact.

### Error & Rescue registry (key new paths)
```
CODEPATH                         | FAILURE MODE              | RESCUED? | RESCUE ACTION                 | USER SEES
---------------------------------|---------------------------|----------|-------------------------------|---------------------------
AudioManager play (nav phrase)   | WAV missing + offline     | Y (new)  | generic phrase → earcon       | "ada objek di depan" / tone
_ensure_pcm + atempo             | ffmpeg/atempo fails       | Y (new)  | fall back to normal-speed PCM | normal-speed audio (not silent)
AnnouncePolicy.decide            | bad/empty detection list  | Y        | treat as empty scene → silent | silence (correct)
distance_band                    | degenerate bbox (0 area)  | Y        | clamp → "far" tier            | far-tier phrasing
espeak spike binary              | crash / OOM               | Y        | spike aborts per kill-criteria| no behavior change (A–D ship)
```

### Failure modes registry
```
CODEPATH                  | FAILURE MODE          | RESCUED? | TEST? | USER SEES?        | LOGGED?
--------------------------|-----------------------|----------|-------|-------------------|--------
nav phrase offline-miss   | silence               | Y (4A)   | Y     | generic/earcon    | Y
atempo render fail        | silence               | Y        | Y     | normal-speed      | Y
approaching hazard        | goes quiet (2B bug)   | Y (2A)   | Y     | timed re-announce | Y
distance from area        | misclassify near/far  | partial  | Y     | wrong tier (rare) | Y (5A calibrated)
describe (gemini down)    | already handled       | Y        | Y     | "tidak ada koneksi"| Y
```
No CRITICAL GAPS remaining (all silent-failure rows now rescued + tested + logged).

## Implementation Tasks
Synthesized from this review. Run with /tdd; checkbox as you ship.

**Build status (2026-06-23):** DONE — T0 (baseline 40✓), T1/T2/T10/T12 (AnnouncePolicy, 10 tests), T4 (offline fallback + earcon, 3 tests), T3/T11 (distance tiers + hysteresis, 11 tests), T5/T6 (atempo + coverage + SSOT, 12 tests). **76 tests passing.** REMAINING — T7 "thinking" earcon (atempo done), T8 espeak spike, T9 JPEG downscale; plus deploy (regen audio WAVs on PC incl. new `_near`/`objek_`/`chime_obstacle`, scp to device), on-demand force-readout gesture wiring, on-device calibration of distance thresholds + atempo rate.

- [ ] **T0 (P1, human ~1h / CC ~10min)** — repo — get existing pytest suite green on current tree before TDD.
  - Surfaced by: Outside voice #4 — dirty +1682-line tree.
  - Verify: `pytest device/tests/ -q`
- [ ] **T1 (P1, human ~1d / CC ~25min)** — `AnnouncePolicy` — single nav-speech gate; fold in `detection_gate`.
  - Surfaced by: Issue 1 (1A). Files: `device/utils/detection_gate.py` → new `device/utils/announce_policy.py`, `device/modes/explorer_mode.py`, `device/core/audio_manager.py`.
  - Verify: `pytest device/tests/test_announce_policy.py` (new) + ported `test_detection_gate`.
- [ ] **T2 (P1, human ~0.5d / CC ~15min)** — `AnnouncePolicy` — change = new/cell/tier; danger re-announce timer.
  - Surfaced by: Issue 2 (2A). Verify: unit tests for approaching-hazard re-announce.
- [ ] **T3 (P1, human ~0.5d / CC ~20min)** — `distance_band` — per-class near/far + ground hint.
  - Surfaced by: Issue 5 (5A). Files: `device/core/ai_engine.py`, new `device/utils/distance.py`.
  - Verify: unit tests with synthetic bboxes per class.
- [ ] **T4 (P1, human ~3h / CC ~15min)** — audio — offline generic-phrase + earcon fallback; never silence.
  - Surfaced by: Issue 4 (4A). Files: `device/core/audio_manager.py`, `tools/generate_audio.py`.
  - Verify: test that offline + missing WAV → fallback task queued.
- [ ] **T5 (P1, human ~0.5d / CC ~20min)** — pre-render — atempo at generation; coverage invariant test.
  - Surfaced by: Decision D1 + C1 + Perf S7. Files: `tools/generate_audio.py`, new `device/tests/test_phrase_coverage.py`.
  - Verify: `pytest device/tests/test_phrase_coverage.py` (every policy output has a WAV).
- [ ] **T6 (P2, human ~2h / CC ~10min)** — config — single source of truth for object set.
  - Surfaced by: Issue 4/DRY S5. Files: `device/config.py`, `tools/generate_audio.py`, `device/core/audio_manager.py`.
- [ ] **T7 (P2, human ~2h / CC ~10min)** — describe — "thinking" earcon on capture; tune atempo 1.8–2.0x w/ on-device listen.
  - Surfaced by: A1/A2 + Outside voice #1/#5.
- [ ] **T8 (P2, human ~1d / CC — toolchain-bound)** — espeak — riscv64 spike with explicit kill criteria.
  - Surfaced by: D1/E. Deliverable: go/no-go note.
- [ ] **T9 (P3, follow-up)** — perf — downscale upload JPEG to shave gemini round-trip.
  - Surfaced by: Outside voice #1.

### Eng-review additions (from /plan-eng-review)
- **Decision E1A:** `AnnouncePolicy` = pure `decide(state, dets, now, cfg) -> (announcements, new_state)` in `utils/announce_policy.py`; `AudioManager` holds the state dict (extends `detection_gate.decide_announce` pattern; single AI-loop thread, no new lock).
- [ ] **T10 (P1, human ~2h / CC ~12min)** — `announce_policy` — state pruning when an object disappears (no stale danger-timer).
  - Surfaced by: Test review — `decide()` "object disappears" path. Mirror `detection_gate.prune`.
  - Verify: unit test — object gone → its state evicted, timer stops.
- [ ] **T11 (P1, human ~2h / CC ~12min)** — `distance` — tier hysteresis (separate up/down thresholds) to stop far↔near flap-spam.
  - Surfaced by: Test review — `band()` "tier-boundary hover" path.
  - Verify: unit test — oscillating area near a boundary yields one announce, not many.
- [ ] **T12 (P1, human ~1h / CC ~8min)** — `announce_policy` — on-demand readout bypasses suppression (emits ALL current detections).
  - Surfaced by: Test review — force-readout path; assessment "on-demand" cadence.
  - Verify: unit test — force=True emits every detection regardless of change/timer state.

### Test coverage backlog (the /tdd checklist — all 16 paths target ★★★)
`announce_policy.decide`: new-object / unchanged-suppressed / cell-change / tier-change / danger-timer-reannounce / on-demand-force / object-disappears-prune / empty-silence.
`distance.band`: per-class threshold / boundary-hysteresis / degenerate-bbox.
`generate_audio atempo`: rate≤2x & >2x chain / ffmpeg-failure-fallback.
`audio_manager` offline fallback: missing+offline→generic / generic-missing→earcon.
`test_phrase_coverage`: every policy output has a pre-rendered WAV (offline guarantee).

### Worktree parallelization
| Lane | Workstream | Modules | Depends on |
|------|-----------|---------|------------|
| A | AnnouncePolicy + offline fallback | `utils/announce_policy.py`, `core/audio_manager.py`, `modes/explorer_mode.py` | T0 |
| B | Distance tiers | `utils/distance.py`, `core/ai_engine.py` | T0 |
| C | atempo + coverage + SSOT | `tools/generate_audio.py`, `config.py` | T0 |
- Lanes A and B both feed the policy but touch different modules → parallelize, integrate at `explorer_tick`. Lane C is independent (pre-render tooling). **Launch A + B + C in parallel after T0; integrate A←B (policy consumes tiers) last.**

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | issues_resolved | HOLD SCOPE; 5 findings raised + decided, 0 critical gaps remaining |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | not_installed | fell back to adversarial self-pass (6 gaps; #2 distance-signal escalated to Issue 5) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | clean | E1A locked; 16-path test backlog; +3 tasks (T10–T12); 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | skipped | no visual-UI scope (auditory UX covered in S1/S4) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | n/a |

- **CODEX:** not installed; outside voice ran as adversarial self-pass both rounds (surfaced state-prune + tier-hysteresis, now T10/T11). Install `@openai/codex` for true cross-model.
- **CROSS-MODEL:** n/a (single model); no tension.
- **VERDICT:** CEO + ENG CLEARED — ready to implement. HOLD SCOPE, evidence-re-aimed; 7 decisions locked; 16-path TDD backlog defined; failure modes all rescued+tested+logged.

NO UNRESOLVED DECISIONS
