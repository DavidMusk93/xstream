# Magnet 可用性校验（Magnet Liveness Check）

> **注（2026-09-19）**：存储已从 DuckDB 迁移到 PostgreSQL 18。文中的
> `db_write` 串行写队列仍然保留（API 未变），但 DuckDB 单写者锁的限制
> 已不存在 —— PG 原生支持并发写入。机制与流程不变。

## 问题

Diff-Sync 选"最佳 magnet"（`scrapers/v2/sinks.py:_score_magnet`）纯按元数据打分
（分辨率 + hhd800 + 种子数），从不验证 swarm 是否活着。死 magnet 会在
TorrentEngine 中永远停在 `downloading_metadata`，前端 180s 后才报笼统的加载超时。

## 机制

```
POST /api/magnets/check ──→ MagnetChecker (backend/services/magnet_checker.py)
                                 │  独立 lt.session（与 TorrentEngine 完全隔离）
                                 │  并发 32，每个 magnet：
                                 │  加种(paused + default_dont_download，不写盘)
                                 │  → resume → 轮询 has_metadata
                                 │  ├─ 60s 内拿到 metadata → alive
                                 │  ├─ 超时但 peers>0 → 宽限一次 90s
                                 │  └─ 仍无 → dead → 逐个校验 all_magnets 候选
                                 │        ├─ 第一个活的 → 换主 magnet (swap)
                                 │        └─ 全死 → magnet_status='dead'
                                 ▼
                         db_write 串行写队列 → titles 新列
                                 │
                         SSE: magnets.check_started /
                              magnets.check_progress /
                              magnets.check_completed / magnets.check_error
                                 │
                    play_timeout (/api/track) ──→ schedule_title_magnet_recheck
                                 (one title, swap/dead invalidates /api/stars only)
```

批量校验时 **只有 swap / dead 才 `invalidate_stars_cache()`**；纯 `ok` 刷新不改变
`/api/stars` 可见字段，避免一轮 changed 校验把 ~2.8MB home JSON 重建上千次。

判定标准：**metadata 到达 = alive**。peers>0 但 metadata 迟迟不到给一次宽限
（活 swarm 但 metadata 慢；注意同主机其他 libtorrent session 的共享 DHT 可能
给随机 hash 返回零星 peer，因此 peers 数只是宽限依据，不作为 alive 依据）。

磁盘即真相优化：`cache/torrent/{hash}/{hash}.torrent` 已存在的 title 直接判
alive，不消耗网络校验。

## DB 列（titles）

| 列 | 含义 |
|---|---|
| `magnet_status` | `NULL` 未校验 / `'ok'` / `'dead'` |
| `magnet_checked_at` | 上次校验时间 |
| `magnet_checked_hash` | 上次校验时的主 hash，用于检测 sync 换主 |
| `dead_since` | 首次判定 dead 的时间（重复校验不重置），驱动 TTL 回收 |

## 触发方式

| 入口 | scope | 说明 |
|---|---|---|
| `POST /api/magnets/check` | all/dead/unchecked/changed | 手动，需 auth cookie |
| sync 成功后自动 | changed | `sync.py::_run_check_bg` 尾部触发；运行中自动跳过 |
| `scripts/check_magnets.py` | 默认 changed，`--scope all` 全量 | 薄 HTTP 触发器，自动算每日密码 |

scope 语义（`crud.load_titles_for_magnet_check`）：

- `unchecked`：从未校验，或 sync 换了主 hash（`magnet_hash IS DISTINCT FROM magnet_checked_hash`）
- `dead`：重试已标记 dead 的（不受退避影响，用于手动强制重试）
- `changed`：unchecked OR 距上次校验超过 `DEAD_RECHECK_INTERVAL`（3 天）的 dead OR
  距上次校验超过 `OK_RECHECK_INTERVAL`（30 天）的 ok（sync 后默认 + 后端启动时也会
  触发一次）。退避原因：sync 每 6h 触发一次，无退避时同一批永久 dead 每轮重探
  （~30 个里仅 2–6 个复活，每轮 150–570s）；主 hash 变化仍由 unchecked 分支立即重查。
  **ok 也要周期性复检**：2026-09 全量 sweep 后大量行永久停在 `magnet_status='ok'`，
  swarm 后来死掉仍会在 shelf 上可点，直到 metadata 超时 —— 30 天 ok 退避 + 过期 ok
  不走磁盘 `.torrent` 短路（必须重新拉 metadata）才能收敛。
- `all`：所有有 magnet 的 title（历史全量，约 2265 个，最坏 1-2 小时）

## 已知限制

- sync 的 ON CONFLICT 会用抓取侧新鲜数据覆盖 `magnet`/`all_magnets`，可能
  复活死链 —— 由 sync 后的 `changed` 校验兜底纠正。注意它同时会覆盖
  `magnet_status`（sync 不写该列，所以状态保留；但 `magnet_checked_hash`
  对不上就会进入下一轮 unchecked 复检）。
- `all_magnets` 内逐候选的死标记不落库（每次 sync 全量覆盖，落库也会丢）；
  只依赖换链后的主 magnet。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `MAGNET_CHECK_TIMEOUT` | 60 | 单个 magnet metadata 等待秒数 |
| `MAGNET_CHECK_GRACE_TIMEOUT` | 90 | peers>0 时的宽限秒数 |
| `MAGNET_CHECK_CONCURRENCY` | 32 | 并发校验数 |

## 前端

`/api/stars` **不返回**不可播放的作品：`magnet_status='dead'`（所有候选都没活）
或根本没有 magnet 的行直接不出现在 payload 里，因此 shelf / rail / 计数里
都看不到它们。唯一例外是 `user_liked=1`：liked 的作品仍然显示（置灰 +
「Unavailable」角标）以便取消 like，且永远不会被 TTL 回收。

## 清理（purge + TTL）

自动（每次校验结束后）：`_run_check_bg` 收尾调用 `_purge_unplayable(ttl_days=7)`
——首次判定 dead 已满 7 天（`dead_since`）或从未有 magnet 已满 7 天
（`created_at`）的行被删除，并写黑名单。7 天里 `changed` 校验仍会每 3 天
复检 dead 行，swarm 复活就立刻回到 UI；所以 UI 隐藏是立即的，行回收是延后的。

```
titles.magnet_status -> 'dead'  (dead_since = now())
   |
   +--> /api/stars 立即隐藏（liked 除外）
   |
   +--> 每 3 天 changed 复检 -> 活则 ok（dead_since NULL）/ 仍死则不动时钟
   |
   +--> dead_since + 7 天 -> 自动 purge: 写 title_blacklist(dead_magnet) + 删行 + 删封面 + GC
```

`POST /api/magnets/purge-dead`（或 `scripts/check_magnets.py --purge`）是手动
开关，等价于 `ttl_days=None`（立即清掉所有不可播放的行）。
`user_liked=1` 的永删不掉（单独报告）。删除前先把 (star_id, code) 以
`reason='dead_magnet'` 封入 `title_blacklist`，否则下一轮同步会把这些 code
当新作品重新下载封面、重新入库；黑名单对 `dead_magnet` 的重试窗口是 30 天
（其它 reason 仍是 7 天）—— swarm 真回来时作品仍会自然回归。
删除同时清理封面目录（`images/titles/{code}`）并对孤儿 cache 跑
`gc_orphaned_torrents`。与进行中的校验互斥（409）。

sink 侧预防：`scrapers/v2/sinks.py:write_batch` 跳过无 magnet 的 item
（`skipped_no_magnet` 计数），源站将来补上 magnet 时该 code 会作为新作品
正常录入。

## 首次全量结果（2026-09-14）

2265 个有 magnet 的历史作品：alive 1885 / swapped 132（死主链自动换活候选）
/ dead 379（全部候选无救）。另有 274 个从未有 magnet 的作品，purge 时一并
删除。
