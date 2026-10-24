# ostore 集成设计 — 任意 magnet 播放 + 网盘视频管理

> 状态：2026-10-23 上线。ostore 仓库：https://github.com/DavidMusk93/ostore

本文档记录两个功能的设计：(1) 任意 magnet 链接即点即播（不入库）；
(2) 基于独立 Rust 服务 **ostore** 的网盘式视频管理（列表/上传/重命名/删除/播放）。

## 1. 总体架构

```
浏览器                    Caddy (443, TLS)
  |  /api/*,/stream/*,/torrent/* -----> xstream backend (FastAPI :8765)
  |  /ostore/*  (strip prefix) -------> ostore (Rust axum 127.0.0.1:8781)
  |  /* -----------------------------> Nuxt frontend (:3000)

ostore 绑定目录: /root/xstream/data/videos (OSTORE_ROOT)
鉴权: OSTORE_TOKEN bearer (/etc/ostore.env, chmod 600, 不进仓库)
```

浏览器获取 ostore 凭据的路径：

```
浏览器 --(cookie xstream_auth)--> GET /api/files/config (xstream backend)
                                  -> {base_url: "/ostore", token}
浏览器 --(Bearer / ?token=)-----> /ostore/api/* (直连, 不经过 FastAPI)

事件不直连（2026-10-24 起）:
ostore /api/events --(httpx, ?since=<last id>)--> OstoreBridge (backend)
    --> EventBus --> /api/events (cookie) --> useEventSource --> /files
```

选择"浏览器直连 ostore"而非"FastAPI 代理"的原因：视频 Range 流与 multipart
上传经过 Python 代理是纯粹的带宽与延迟损耗；ostore 自身已做鉴权与 CORS。
`<video src>` 无法设置请求头，故 ostore 同时接受 `?token=` query 参数
（个人站点，接受 access log 记录 query 的代价）。事件流不再走 `?token=`：
见 §3「实时更新」。

## 2. 功能 1：任意 magnet 播放（play-direct）

### 关键探查结论

播放链路（`/stream/{hash}`、`/api/check/{hash}`、`/torrent/*`）全程只认
40-hex info-hash，**不依赖 DB**；`video_stream.py` 对未知 hash 甚至会自动按
裸 magnet 加种。因此后端只缺两件事：

1. **防孤儿 GC 误删**：`gc_orphaned_torrents()`
   （`backend/services/torrent_engine.py`）会删除所有不在
   `titles.magnet_hash` 的磁盘缓存，且在**后端启动时**、`/api/cache/gc-orphans`、
   magnets purge-dead 后都会运行。
2. 一个语义化入口端点。

### 设计：`.adhoc` 磁盘标记

- ad-hoc 种子缓存目录（`cache/torrent/<hash>/`）内放空文件 `.adhoc`。
- 纯磁盘标记 → 重启后 GC 与 `_preload_cached_torrents` 都能识别，无状态丢失。
- `gc_orphaned_torrents()` 跳过含 `.adhoc` 的目录；preload 时恢复
  `info["adhoc"]=True`。
- adhoc **不享受** keep_cache 保护：pause 即清缓存（临时播放语义），
  只防孤儿 GC 这一种"误删"。

### API（`backend/routers/play.py`，`Depends(require_auth)`）

| 端点 | 语义 |
|---|---|
| `POST /api/play/direct` `{magnet}` | 校验 btih → `add_torrent` → 落 `.adhoc` → `resume_download(0,0)`；返回 `{hash,name,status,ready,peers,progress}`；同 hash 幂等 |
| `GET /api/play/recent` | 扫描 `cache/torrent/*/.adhoc`，返回 `{hash,name,size_on_disk,mtime}` 按 mtime 倒序 |
| `DELETE /api/play/{hash}` | 删除该 adhoc 缓存 |
| `GET /api/files/config` | 返回 `{base_url, token}`（ostore 凭据下发）；未配置 503 |

前端 `/play` 页拿到 hash 后复用现有 `VideoModal`（`/torrent/resume` + SSE
`torrent.head_ready`），播放器零改动。

## 3. 功能 2：ostore 对象存储 + 网盘 UI

### ostore 设计要点（Rust / axum）

- 单二进制，env 配置：`OSTORE_ROOT / OSTORE_TOKEN / OSTORE_HOST / OSTORE_PORT`。
- 路径安全：拒绝绝对路径、`..`、NUL；join 后规范化并校验仍在 root 内。
- 上传原子性：先写唯一的 `<name>.ostore-tmp-<pid>-<seq>`（1 MiB 缓冲写），
  fsync 后 rename；启动时清扫崩溃残留的 tmp 文件。
- multipart 上传**关闭** axum 默认 2 MB body 上限（之前浏览器上传 >2 MB
  的视频一律 400 BAD_MULTIPART）。
- 下载带弱 ETag（size+mtime），`If-None-Match` → 304。
- `GET /api/metrics`：Prometheus 文本（按路由的请求数/延迟直方图、上传/下载
  字节、进行中上传、事件计数、SSE 订阅数/reset 数、webhook 结果、根目录磁盘
  空间），同样需要 bearer。
- `GET /api/files/{*path}` 支持 `Range`（206/416）——浏览器拖动进度条依赖。
- 事件：`tokio::sync::broadcast` 总线 + 1024 条 ring；每条事件带单调
  `id`（以启动时刻微秒为种子，跨重启仍递增）与 `type`（file/dir）。
  `GET /api/events` 游标语义：`?since=<id>` / `Last-Event-ID` 精确续传；
  无游标时 replay 最近 `?replay=N`（默认 100，0=只看实时）；游标落出 ring
  或来自上一进程 / 订阅者滞后 → 发一条 `stream.reset`，客户端须重新 list。
  SIGTERM 时 SSE 流主动结束（否则 graceful shutdown 永远等不完）。
  webhook 注册持久化到 `<root>/.ostore/webhooks.json`，并发投递（信号量 32），
  失败 1s/5s/15s 退避重试 3 次。
- 备份语义：`GET /api/list?recursive=1&checksums=1`（sha256）+ 指定路径
  `PUT` + `DELETE` 即可实现任意机器 → ostore 的镜像备份；agent 自发现入口
  `GET /api/help` 返回机器可读端点清单。

事件类型：`object.created / object.updated / object.deleted /
object.moved / object.mkdir`。

### 前端 `/files` 页

- `composables/useOstore.ts`：先取 `/api/files/config`，封装
  list/upload(XHR 进度)/mkdir/move/remove/fileUrl(?token=)；list 把 ostore
  的 RFC 3339 `mtime` 归一成 epoch 秒（之前直接当数字用，日期全是
  Invalid Date）。
- 当前目录在 URL `?path=`（浏览器后退 = 上一级目录）；eyebrow 即面包屑；
  目录在前文件在后；视频行整行点击播放。
- 上传用 **XMLHttpRequest**（fetch 无法上报上传进度），进度驱动
  `SyncToast`（fraction + progressText）。
- 预览走 `FilePreviewModal`（2026-10-24 起覆盖所有文件类型，取代只能放
  视频的 `FilePlayerModal`；**不复用** torrent 专用的 `VideoModal`）：
  图片 / 视频 / 音频 / PDF / Markdown / JSON / CSV / 文本代码，未知类型先
  嗅探 1 MB 是否为文本，否则信息卡 + 下载；文本类只 Range 取前 512 KB。
  列表图片缩略图走 ostore `GET /api/thumb/{path}?w=128`（服务端等比缩放 +
  磁盘缓存，不下载原图）。设计细节见 ui-design.md「Files」。
- **实时更新（2026-10-24 重做）**：旧实现页面自开
  `/ostore/api/events?token=` EventSource，每个 object.* 事件节流 1s 整页
  重新 list；而 ostore 每次（重）连都 replay 最近 100 条 → 每次重连都触发
  刷新、spinner 闪烁，拖拽时 dragleave 穿过子元素又让高亮闪烁 —— 即"频繁
  抖动"。现在：
  - 后端 `backend/services/ostore_bridge.py` 在 lifespan 中常驻消费 ostore
    SSE（首连 `replay=0` + 发 `files.resync`；之后 `since=<last id>` 续传），
    转发为总线事件 `files.changed {kind,path,type,size?,from?,mtime}`；
    `stream.reset` → `files.resync`。
  - `/files` 只用全局 `useEventSource`（cookie 鉴权，token 不再进 access
    log），按事件**就地增删行**（keyed by path，保持 dirs-first + 名称序），
    不重新请求；当前目录或其祖先被删/移动时跳到父目录/新位置。
  - `files.resync` / `sync.resync_required` / `sse.reconnected`（
    `useEventSource` 在断线重连后本地派发）→ 静默 reload（不出 skeleton）。
  - 拖拽覆盖层用 dragenter/dragleave 深度计数，不再随子元素闪烁。
- Workbox：`/^\/ostore\/.*/` 必须 `NetworkOnly`（SSE 与视频字节范围绝不能
  进 SW 缓存——与 `/api/events` NetworkOnly 同一教训，见
  docs/design/sse-push-architecture.md）。

## 4. 部署

```bash
# ostore
install -m600 /etc/ostore.env          # OSTORE_TOKEN/ROOT/HOST/PORT
cp deploy/ostore.service /etc/systemd/system/
systemctl enable --now ostore

# Caddy: handle /ostore/* { uri strip_prefix /ostore; reverse_proxy localhost:8781 }
# /ostore 块不加 encode（SSE 不能被缓冲）
systemctl reload caddy

# xstream backend: /etc/xstream.env 增加 OSTORE_TOKEN / OSTORE_PUBLIC_BASE=/ostore
# (可选 OSTORE_INTERNAL_URL，默认 http://127.0.0.1:8781 —— 事件桥用)
systemctl restart xstream-backend xstream-frontend
```

## 5. 红线符合性

- 新路由 `/api/play/*`、`/api/files/config` 均 `Depends(require_auth)`。
- 所有阻塞 I/O（add_torrent、磁盘扫描）走 `asyncio.to_thread`，
  `tests/test_no_blocking_db_in_handlers.py` 适用。
- 按需下载纪律不变：play-direct 同样 paused+零优先级加种，
  `resume_download` 只抬窗口内优先级。
- token 只存 `/etc/ostore.env` 与 `/etc/xstream.env`，不进仓库。
