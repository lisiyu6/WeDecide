# 部署与运维

## 本地、局域网

从仓库根目录按 README 安装 Python 依赖，然后运行：

```bash
.venv/bin/python -m wedecide.cli admin-password
./start.sh
```

默认 `0.0.0.0:8000`。访问管理页需手动输入 `/admin`；普通用户无管理入口。局域网访问需要操作系统/路由器允许相应端口，这份代码不会改写防火墙。

若需要自定义数据目录，设置密码和启动服务时都必须使用同一个环境变量：

```bash
export WEDECIDE_DATA_DIR=/path/to/wedecide-data
.venv/bin/python -m wedecide.cli admin-password
./start.sh
```

用户名只是显示名。成员凭证保存在 HttpOnly Cookie 中；不同设备或不同浏览器视为不同身份，均须房主批准。不要清除 Cookie 后期望仅凭相同用户名恢复房主权限。管理员登录凭证与成员身份分开。

## 停止与重启

通过 `./start.sh` 或 `wedecide serve` 启动时，收到 Ctrl+C / SIGTERM 会先唤醒并结束所有房间 SSE 长连接，再由 Uvicorn 排空请求；等待上限为 5 秒，超时取消剩余请求，随后清理维护任务与 AI 队列。这个关闭通知必须发生在服务器排空请求前，仅在 FastAPI lifespan 清理时关闭 SSE 会因生命周期顺序而卡住。停止后重新执行原启动命令即可，已持久化的房间和消息保留，未完成的 AI 请求不会跨进程恢复。

## Docker

```bash
docker compose up -d --build
docker compose exec wedecide python -m wedecide.cli admin-password
```

Compose 默认开放所有网卡的 8000 端口，数据保存在命名卷 `wedecide-data`。容器以 UID/GID 10001 运行，根文件系统只读，SQLite 数据卷可写，内存上限为 500,000,000 字节。以上命令属于交付说明，本次没有运行。

## 公网 HTTPS

1. 将域名解析到服务器。
2. 在服务器项目目录建立 `.env`，填写：

```dotenv
WEDECIDE_BIND_ADDRESS=127.0.0.1
WEDECIDE_PUBLIC_URL=https://decide.example.com
WEDECIDE_ALLOWED_ORIGINS=https://decide.example.com
WEDECIDE_SECURE_COOKIE=true
```

3. 用 Docker Compose 运行应用，或将相同变量配置给 systemd（本机进程可另设 `WEDECIDE_HOST=127.0.0.1`）。
4. 安装并配置 Caddy，把 `deploy/Caddyfile` 中的域名改为实际域名。Caddy 转发到 `127.0.0.1:8000` 并申请 HTTPS 证书。
5. 服务器只对外开放 HTTP/HTTPS，应用端口留在本机。不要给反向代理启用 SSE 缓冲；示例已配置实时 flush。

应用本身不信任未经配置的转发头；外部链接由 `WEDECIDE_PUBLIC_URL` 决定，允许来源由 `WEDECIDE_ALLOWED_ORIGINS` 决定，因此没有依赖 `X-Forwarded-Proto` 自动推断 HTTPS。多个允许来源用逗号分隔；这是同源部署用的来源检查，不是跨域 API 开放配置。前端与 API 由同一个域名提供。

本实现面向单实例部署。不要设置 `--workers 2` 或横向运行多个共享数据库实例，否则各实例的在线状态与任务队列无法互相同步。

## systemd

`deploy/wedecide.service` 是可调整模板，不会自动安装。约定：

- 项目目录 `/opt/wedecide`，其中已建 `.venv` 并安装依赖。
- 系统运行用户/组 `wedecide`。
- 数据目录 `/var/lib/wedecide`，由 `StateDirectory` 管理。
- 可选环境文件 `/etc/wedecide.env`，语法为 `KEY=value`。

设置密码时使用服务账户以及同一数据目录，例如：

```bash
sudo -u wedecide env WEDECIDE_DATA_DIR=/var/lib/wedecide /opt/wedecide/.venv/bin/python -m wedecide.cli admin-password
```

在 NixOS 上可将模板表达为系统模块，也可使用项目自己的启动脚本；本项目不修改个人 NixOS/Home Manager 配置。

## 保存、备份和保留期

- SQLite 位于 `WEDECIDE_DATA_DIR/wedecide.sqlite3`。应用会创建 0700 数据目录和 0600 主数据库文件；生产环境还需为该目录设置合适所有者。
- 数据包括房间状态、会话哈希、个人条件、私密聊天、API 密钥和管理员密码哈希。API 密钥在数据库中并未额外加密，备份需要按私密配置保护。
- 备份时优先停止进程后复制整个数据目录，或使用 SQLite 自带 backup 接口；不要在写入中仅复制主数据库而遗漏 WAL 状态。
- 默认结束 7 天后自动清理，管理员可以调整。建议在清理前从结果页下载需要长期保存的报告。
- 管理员修改保留期会作用于已有记录。关闭房间不等于立即删除，仍按保留期清理。
- 当前持久化消息采用每房最近 2,000 条上限，超出后删除最早消息。事件和分析历史也有明确上限，以保持单房间数据规模有限。
- 浏览器本地草稿可在确认条件、发送消息后清除；未提交的草稿仅存在当前浏览器。共用设备应分别使用浏览器配置文件。

## 运维入口

管理员控制台提供：房间并发上限、人数上限、AI 并发/队列限制、无操作过期时间、保留期、全局供应商、默认模型、隐藏提示词、房间运行摘要和关闭房间。

没有默认管理员密码，也没有忘记密码邮件流程。忘记密码时在后端重新运行 `admin-password`；已登录管理员会话会同时失效。

用户聊天、模型请求正文和密钥不会被主动写入终端访问日志。AI 原始上游错误正文不会回显，前端显示状态码或通用配置错误。管理员可先检查端点协议、完整 URL、模型 ID、鉴权头、前缀和响应路径。

## 本次交付没有执行的事项

依赖安装、启动应用、Docker 镜像构建、HTTPS 证书签发、功能测试、安全测试、多人负载测试、内存测量和真实 AI 请求均未执行。部署文件与源码经过只读审阅；实际运行状态需后续另行验证。
