---
name: formal-verification
description: >-
  Apply formal verification (explicit state machines, Safety/Liveness invariants,
  exhaustive model checking, property-based model testing, and bounded verification)
  to eliminate recurring bugs in stateful, concurrent, or protocol-heavy modules
  (BitTorrent scheduling, cache eviction, playback state machines, SSE sync, DB
  concurrency). Use whenever a subsystem suffers recurring race/state bugs, when
  designing a new state machine or scheduler, or when the user asks for formal
  proofs, invariants, or model checking.
---

# Formal Verification Engineering Guide

Why bugs keep coming back ("修不完"):
1. **Boolean-flag soup**: `isPlaying`, `loading`, `buffering`, `seeking`, `retrying`, `paused` create $2^6 = 64$ states where most combinations are illegal, yet nothing forbids them.
2. **Event interleaving blindness**: Unit tests check 2-3 happy paths; production hits out-of-order events (`stalled` during playback, `NotAllowedError` after 40s async wait, `seek` during `loadedmetadata`, SSE drop during `head_ready`).
3. **Model-code drift**: Prose docs describe invariants, but no executable verifier checks the actual code against all reachable states.

Formal verification turns "hope we thought of every edge case" into **machine-checked invariants over all reachable states or thousands of adversarial event interleavings**.

---

## 1. When Formal Verification Is Mandatory

Apply this skill whenever a module has **any** of the following:
- **Interactive media / UI state machines** (e.g. `VideoModal` playback lifecycle: idle / waiting-head / loading / playing / buffering / paused / seeking / error / muted-fallback).
- **Resource schedulers & budgets** (e.g. `xstream_bt` on-demand piece windowing, foreground QoS yield, disk cache LRU eviction, concurrency caps).
- **Async network / sync protocols** (e.g. SSE reconnect + `head_ready` handoff, cold-magnet `pending_adds` lifecycle, HTTP Range disconnect cancellation).
- **Concurrent data integrity** (e.g. multi-writer DB upserts, advisory locks, bitmaps).

Do **not** waste formal methods on: static CSS/layout styling, one-off CLI scripts, or third-party HTML scraping selectors.

---

## 2. Verification Requirements (What Must Be Proven)

Every verified subsystem must define **three artifacts** before writing or fixing logic:

### A. Explicit State & Event Algebra (No Boolean-Flag Soup)
Replace ad-hoc boolean combinations with a **pure, side-effect-free reducer / state machine** whose illegal states are unrepresentable:
- `State`: explicit tagged union / enum (Rust `enum`, TypeScript discriminated union).
- `Event`: every external stimulus (user actions, media DOM events, network/SSE events, timers, peer/piece completions).
- `Effect` (optional): declarative side effects (`Play`, `Pause`, `Seek(t)`, `Prewarm(range)`, `Evict(hash)`), executed by a thin imperative shell.

### B. Safety Invariants ("Bad Things Never Happen")
Predicates `P(state) -> bool` that must hold in **every reachable state** after **every transition**:
- Example (Player): `state == Playing => button == Pause && !loading`.
- Example (Player): `event == Stalled && !video.paused => isPlaying stays true`.
- Example (On-demand BT): `active_bytes_outside_window == 0` (never bulk-download unrequested ranges).
- Example (Cache Eviction): `active_streams(h) > 0 || pinned(h) => h not in evict_set`.

### C. Liveness & Progress Properties ("Good Things Eventually Happen")
Properties checked under fairness (assuming network/peers eventually respond):
- Example (Player): `user_intent == Play && head_ready && canplay => eventually Playing (unmuted or muted-fallback), never stuck in Paused`.
- Example (BT Cold Magnet): `add_magnet(Active) => eventually (metadata_resolved && head_prewarm_attached) || cancelled`, never deadlocked at 0%.
- Example (QoS): `foreground_idle_for > grace => yielded_background_eventually_resumes`.

---

## 3. Tooling Stack (Matched to This Repo)

Choose the lightest tool that **exhaustively** covers the bug class and runs inside normal CI (`cargo test` / `vitest` / `pytest`):

| Layer | Purpose | Rust (`rust/xstream_*`) | TypeScript / Vue (`frontend/`) | Python (`backend/`) |
|---|---|---|---|---|
| **L1: Pure State Machine** | Make invalid states unrepresentable | Algebraic `enum` + pure `fn step(State, Event)` | Discriminated union in `frontend/utils/*Machine.ts` | `@dataclass` + `Enum` reducer |
| **L2: Exhaustive Model Checking** | BFS/DFS over **100%** of reachable states & interleavings; outputs minimal counterexample trace | **`stateright`** (Rust-native, zero JVM, runs in `cargo test`) | **`Quint`** (or Rust `stateright` mirror of TS spec) | `stateright` / `TLA+` (spec) |
| **L3: Property / Model-Based Testing** | Drive real implementation with 1,000+ randomized adversarial sequences + automatic shrinking | **`proptest`** | **`fast-check`** (+ `vitest`) | **`hypothesis`** (+ `pytest`) |
| **L4: Bounded Symbolic / Concurrency** | Prove zero panics, zero integer overflow, zero lock/atomic races | **`kani`** (CBMC symbolic) / **`loom`** (concurrency) | TypeScript `strict` exhaustive `never` checks | — |

### Tool Selection Rule
1. **Default for state machines & schedulers (Rust)**: `stateright` (L2 exhaustive BFS) + `proptest` (L3 implementation conformance). Both are pure Rust crates with zero external runtime dependencies and run in `cargo test`.
2. **Default for frontend player / SSE state machines (TS)**: extract pure state machine into `frontend/utils/<name>Machine.ts` + verify with **`fast-check`** (`vitest`) over random event interleavings (`stalled`, `waiting`, `seeking`, `seeked`, `canplay`, `NotAllowedError`, `sse.reconnected`, `close`).
3. **Default for arithmetic / bitmaps / parsers / eviction (Rust)**: `proptest` + (when installing `cargo-kani` is justified) `kani` proof harnesses.

---

## 4. Workflow: Formalize -> Prove -> Implement -> Lock

```text
Bug / New Stateful Feature
        |
        v
1. Extract pure State + Event + transition()
        |
        v
2. Write Safety & Liveness invariants (formal spec)
        |
        v
3. Run L2 (Stateright BFS) / L3 (proptest / fast-check)
        |
        +-- counterexample found --> Fix spec/code, re-run until 0 counterexamples
        |
        v
4. Wire thin imperative shell (DOM / librqbit / HTTP) to pure transition()
        |
        v
5. Add regression trace from any real incident as a permanent unit test
```

### Critical Rule: Proof Must Target Production Logic, Not a Toy Copy
- Never write a formal model in a separate document that drifts from production code.
- **Extract the state machine into a pure module** (e.g., `rust/xstream_bt/src/scheduler.rs`, `frontend/utils/playerMachine.ts`) that is **directly imported and executed by production code**, and run `stateright` / `proptest` / `fast-check` directly against that exact module.

---

## 5. Acceptance Criteria (Definition of Done)

A formal-verification task is **NOT** accepted until ALL of the following pass:

1. **Zero Illegal States by Construction**: Core control state uses an explicit enum/union, not overlapping booleans.
2. **Documented Invariant Table**: Every Safety (`S1..Sn`) and Liveness (`L1..Ln`) invariant is listed in the module header doc and mapped 1-to-1 to an automated assertion.
3. **Machine-Checked Proof Passes in CI**:
   - Rust: `cargo test --workspace` runs the `stateright` exhaustive checker (reporting total distinct states explored and `0` violations) and/or `proptest` (>= 1,000 cases) + `cargo clippy --all-targets --all-features -- -D warnings`.
   - Frontend: `vitest` runs `fast-check` property suites (>= 500 shrunk event sequences per invariant) with `0` failures.
   - Python: `pytest` runs `hypothesis` suites with `0` failures.
4. **Incident Trace Replay**: Every bug that triggered the verification effort is encoded as a deterministic replay test proving the old failure sequence now satisfies all invariants.
5. **Thin Shell Audit**: The imperative wrapper (`VideoModal.vue`, `engine.rs`, `http.rs`) contains no shadow state booleans that bypass the verified state machine.

---

## 6. Anti-Patterns to Reject

- **Source-grep tests as a substitute for behavioral proofs**: Static assertions (`assert "syncPlayingState()" in VIDEO_MODAL`) catch accidental deletions, but do **not** prove state-machine correctness across event interleavings. Pair them with L2/L3 executable proofs.
- **Happy-path-only tests**: Testing `open -> head_ready -> canplay -> playing` misses `open -> sse.drop -> head_ready -> sse.reconnect -> canplay(NotAllowedError) -> stalled -> seek -> pause`.
- **Unbounded state explosion without abstraction**: When using `stateright`, bound abstract domains (e.g. `2-3` torrents, `3-4` pieces/segments, `2` concurrent streams) using symmetry reduction so exhaustive BFS finishes in `< 2 seconds` in `cargo test`.
