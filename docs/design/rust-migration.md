# Incremental Rust Migration Guide (xstream)

> **Status:** Active guidance (Phase 0 complete — BeautifulRust skills & lints locked in).
> **Standards:** Guided by [BeautifulRust](https://github.com/morganlinton/BeautifulRust), vendored in `.agents/skills/rust-{best-practices,review,port}/` and `rust/{clippy,lints}.toml`.

---

## 1. Honest Diagnosis: Which Races Does Rust Solve?

Before porting a single line, separate **language/runtime races** (where Rust's ownership, `Send`/`Sync`, and lock-free/async primitives eliminate whole bug classes at compile time) from **architectural/protocol races** (which survive any language rewrite unless the boundary is redesigned).

### Bugs Rust **Will** Eliminate at Compile Time

| Problem in current Python stack | How Rust eliminates it |
|---|---|
| Shared mutable dicts (`TorrentEngine.torrents`, `PieceStateTracker` bitmaps) accessed across FastAPI async loop, `asyncio.to_thread` workers, and libtorrent alert thread under manual `threading.Lock` | Ownership + `Send`/`Sync` + `Arc<Mutex<T>>`/`RwLock<T>` or actor/channel ownership (`tokio::sync::mpsc`) — data races fail to compile |
| Event-loop starvation & GIL contention (requiring `db_write` queue, `asyncio.to_thread`, `test_no_blocking_db_in_handlers.py`) | Multi-threaded `tokio` runtime + async `sqlx` connection pool; no GIL |
| Invalid state-machine transitions & boolean-flag soup | Algebraic enums (`enum PieceState`, `enum MagnetStatus`) + typestate; `clippy` enforces `max-fn-params-bools = 0` |
| Silent `None` / dict-key / `AttributeError` failures at runtime | Exhaustive `match`, `Option<T>`, `Result<T, E>`, `serde` typed structs |

### Bugs Rust **Will Not** Automatically Fix

| Problem | Actual root cause & required fix |
|---|---|
| Concurrent `sync_star` vs full `run()` clobbering DB rows (e.g. `SNOS-524` HD magnet overwritten by stale ijav snapshot) | Cross-task DB read-modify-write race → requires PostgreSQL advisory locks / atomic merge SQL (`ON CONFLICT` merge), regardless of language |
| Frontend click/modal/SSE races (`StarCard.vue` `useApi()` context, `VideoModal.vue` uncancelled `waitForHeadReady`) | Browser / Vue lifecycle & PWA SW caching → fixed in TypeScript/Vue |
| Upstream flakiness (ijavtorrent layout changes, Sukebei 429s, dead BT swarms) | External I/O & rate-limiting contracts |

---

## 2. Migration Strategy: Strangler Fig (Zero Big-Bang Rewrites)

Never rewrite the whole backend in one shot. Use the **strangler-fig** pattern — two proven integration bridges already fit this repo (we already run Rust/axum in `/root/ostore` and Rust CLI in `tools/tg-lint`):

1. **In-process native extension (`PyO3` + `maturin`)** for pure logic & hot state machines — keeps FastAPI routes and existing `pytest` regression suites running unchanged as the behavioral oracle.
2. **Sidecar Rust/axum service behind Caddy** (just like `/ostore/*`) for self-contained I/O subsystems (SSE hub, sync/magnet-check workers, API endpoints) routed path-by-path in `/etc/caddy/Caddyfile`.

### Phased Roadmap

```text
Phase 0 (Done)  : Vendor BeautifulRust skills (.agents/skills/rust-*) + lints (rust/clippy.toml, rust/lints.toml)
Phase 1 (Done)  : xstream_core (PyO3):
                  - [x] PieceStateTracker -> rust/xstream_core/src/piece_tracker.rs
                  - [x] scrapers/v2/filters.py + _score_magnet -> rust/xstream_core/src/{filters,scoring}.rs
                  - [x] scrapers/v2/extractors.py (Sukebei RSS + magnet helpers) -> rust/xstream_core/src/extractors.rs
Phase 2 (WIP)   : Concurrent I/O & PG hardening:
                  - [x] Replace DuckDB-era serial DBWriteQueue with bounded-concurrency pool + PG `pg_advisory_xact_lock` per-star sync
                  - [ ] EventBus /api/events SSE hub + ostore_bridge (Rust/axum `tokio::sync::broadcast`)
                  - [ ] sync/magnet_checker worker (sqlx + PG advisory locks)
Phase 3 (Eval)  : TorrentEngine + video_stream (keep libtorrent via C++ cxx FFI or evaluate librqbit against all 15+ BT tests)
```

- **Build & install `xstream_core` into `.venv`**:
  ```bash
  VIRTUAL_ENV=/root/xstream/.venv uv run maturin develop --release --manifest-path rust/xstream_core/Cargo.toml
  ```

- **Phase 1 — Pure Core (`xstream_core` via PyO3)**:
  - `backend/services/piece_tracker.py` (3x bitmap state machine; locked by `tests/test_piece_tracker*.py`).
  - `scrapers/v2/filters.py`, `scrapers/v2/extractors.py`, `TitleSyncSink._score_magnet` (deterministic parsing/filtering/scoring; locked by `tests/test_diff_sync.py` & `tests/test_search_router.py`).
- **Phase 2 — Concurrent I/O Services (Rust/axum + `tokio` + `sqlx`)**:
  - SSE hub (`/api/events`) + `ostore_bridge` using `tokio::sync::broadcast` (replaces Python `EventBus` + `asyncio.Queue` fan-out).
  - Sync & `MagnetChecker` daemon using PostgreSQL advisory locks (`pg_advisory_lock`) so `sync_star` and scheduled syncs never race on the same `(star_id, code)`.
- **Phase 3 — BitTorrent Engine (Evaluate Before Committing)**:
  - `TorrentEngine` wraps C++ `libtorrent 2.0.x`, whose streaming semantics (`close_redundant_connections=False`, on-demand priorities, bootstrap-first, fast-resume) are battle-tested. Prefer wrapping `libtorrent` via `cxx` or keeping a thin boundary rather than rewriting BT protocol edge cases from scratch unless a Rust BT crate passes every existing regression test in `tests/`.

---

## 3. Mandatory BeautifulRust Workflow

All Rust code in this repository **must** follow the vendored BeautifulRust skills and lints:

1. **Before porting any Python module**: read `.agents/skills/rust-port/SKILL.md` — **port the original tests first** so behavioral parity is proven before replacing callers.
2. **When writing or editing Rust**: read `.agents/skills/rust-best-practices/SKILL.md` (and its `references/` when needed).
3. **Before committing Rust changes**: run `.agents/skills/rust-review/SKILL.md` checklist and enforce the clippy gate:
   ```bash
   cargo test --all-targets
   cargo clippy --all-targets --all-features -- -D warnings
   ```
4. **Workspace lints**: every new crate/workspace under `rust/` must include `rust/clippy.toml` at workspace root and the `[workspace.lints]` block from `rust/lints.toml` (with `[lints] workspace = true` in each member `Cargo.toml`). Local suppressions must use `#[expect(..., reason = "...")]`, never bare `#[allow]`.
