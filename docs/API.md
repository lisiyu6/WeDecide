# API 与扩展约定

同源 JSON HTTP API。成功返回 JSON，错误返回 `{"detail":"说明"}`，字段错误可能带 `fields`。变更请求为 `Content-Type: application/json`，最大 128 KB。成员凭证和管理员凭证通过 HttpOnly Cookie 传递，分别为 `wd_session` 和 `wd_admin`。

## 身份、房间与实时同步

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/bootstrap` | 创建/恢复成员浏览器身份；返回公共容量及供应商名称/模型，不返回密钥和提示词 |
| GET | `/api/rooms` | 当前身份参与的最近房间 |
| POST | `/api/rooms` | 创建房间，`CreateRoom` 模型 |
| POST | `/api/join/{code}` | `{"username":"..."}` 提交加入申请，必须房主批准 |
| GET | `/api/rooms/{id}` | 按身份投影的房间快照 |
| GET | `/api/rooms/{id}/events` | SSE，`change` 事件提示重新获取快照；心跳 20 秒 |
| POST | `/api/rooms/{id}/actions` | 原子业务操作 |
| GET | `/api/rooms/{id}/invite.svg` | 已批准成员可获取的邀请二维码 |
| GET | `/api/rooms/{id}/report` | 去除私密条件、原文、个人明细和秘密配置后的 JSON 报告 |
| GET | `/api/display/{token}` | 只读投屏汇总（持有房主分享的链接可访问） |

通用操作格式：

```json
{
  "revision": 12,
  "action": "select",
  "payload": {"proposal_id":"..."}
}
```

普通房间操作必须匹配当前 `revision`，过期返回 409。个人偏好提交以 `preference_version` 校验；投票以 `session_id` 校验；授权请求检查原偏好版本、输入版本和状态。独立投票、反馈和参与意愿不因其他成员同时提交而被全局 revision 拒绝。

| action | payload | 权限与边界 |
| --- | --- | --- |
| `approve` / `reject_join` | `member_id` | 房主；投票中不得改变名单 |
| `preference` | `preference_version`, `preference` | 本人；未澄清项须解决；投票或结束后锁定 |
| `resources` | `resources` 列表 | 房主；最多 20 项 |
| `settings` | `scenario`, `rules` | 房主；正式投票开始后冻结规则 |
| `analyze` | 空 | 房主；全员已确认且有候选资源 |
| `select` | `proposal_id` | 房主；必须当前输入版本且可行 |
| `start_vote` | 空 | 房主；按选中方案创建不可变快照 |
| `vote` | `session_id`, `choice`, `reason` | 本人；choice 为 accept / revise / reject，单轮仅提交一次 |
| `cancel_vote` | 空 | 房主；保留记录，旧票不继承 |
| `withdraw` | 空 | 普通成员本人；取消正在进行的投票并重新计算 |
| `negotiate` | 空 | 为本人生成确定性的可选条件调整建议 |
| `request_change` | `member_id`, `field`, `value`, `reason` | 仅针对本人；生成待确认请求 |
| `answer_request` | `request_id`, `decision`, 可选 `value` | 仅目标本人；accept / reject；不能覆盖新条件 |
| `feedback` | `text`, `summary`, 可选 `proposal_id` | 原文仅本人；summary 为明确授权公开的文字 |
| `attendance` | `value` | yes / no / undecided，与正式接受独立 |
| `finish` | `outcome`, `explanation` | 房主；不能直接标记 APPROVED |

输入字段、数值范围、默认值集中在 `wedecide/models.py`。时间按一天内分钟表示，`0=00:00`、`1440=24:00`，仅支持同一天，不跨日。地点限制采用明确名称精确匹配。

## AI 与消息

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/rooms/{id}/messages?before={message_id}` | 每页最多 50 条；仅本人私聊与公开消息 |
| POST | `/api/rooms/{id}/messages` | `{"text":"...","kind":"chat"}`，发布公开消息 |
| POST | `/api/rooms/{id}/ai` | `{"text":"...","kind":"chat|preferences|negotiate"}`；202 后通过 SSE 获取结果 |
| POST | `/api/scenario` | 生成创建页面的场景草稿，使用默认全局供应商 |
| GET / PUT | `/api/rooms/{id}/provider` | 仅房主；读取脱敏配置 / 保存全局选择或房间专用接口 |
| POST | `/api/rooms/{id}/provider/models` | 仅房主；`{}` 使用已保存接口，`{provider}` 按未保存的表单拉取，或 `{provider_id}` 查看所选全局接口 |

房间 API 的保存格式为 `{revision, provider_id, provider}`；`provider=null` 表示回到全局配置。Provider 模型集中定义了 endpoint、protocol、model、api_key、auth_header、auth_prefix、headers、extra_body、request_template、response_path、models_endpoint、models_path、model_id_field、timeout、max_tokens、temperature、enabled。

AI 回复只有两类结果：聊天文本，或消息 metadata 中的结构化草稿。草稿永远不直接写入正式条件。异步结果保留生成时的偏好版本；用户提交旧草稿需要先按当前版本重新核对。

## 管理员

管理员入口仅 `/admin`。普通导航不展示该地址。管理员密码只能通过 `python -m wedecide.cli admin-password` 设置，终端隐藏输入。

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| POST | `/api/admin/login` | `{"password":"..."}`，创建独立管理员会话 |
| POST | `/api/admin/logout` | 注销管理员会话 |
| GET / PUT | `/api/admin/settings` | 运行限制、全局供应商、默认值、隐藏系统上下文；保存携带设置 `revision` |
| POST | `/api/admin/providers/{id}/models` | 查询已保存的全局供应商模型列表 |
| POST | `/api/admin/providers/models` | `{provider, saved_provider_id?}` 按当前表单拉取模型；编辑时复用原供应商已保存的密钥/请求头，不保存配置 |
| GET | `/api/admin/rooms` | 最近 200 个房间运行摘要与 AI 队列状态 |
| POST | `/api/admin/rooms/{id}/close` | 关闭活动房间，取消当前投票，保留记录 |

模型发现使用 GET 请求，不发送聊天、个人偏好或管理员提示词。可通过 `models_endpoint` 指定独立完整 URL；留空时推导标准 `/models`。`models_path` 默认 `data`，支持点路径与数组索引，顶层数组也可直接读取；`model_id_field` 默认 `id`，可指定 `name` 或嵌套字段。结果去重、排序并限制为 1,000 个 ID。单次响应上限 1 MB，请求总时间上限为配置超时与 45 秒中的较小值；请求还受到全局 AI 并发和队列限制。

模型发现为只读操作，草稿配置不写入 SQLite。管理员只能复用由 `saved_provider_id` 标识的原供应商凭证，房主只能复用自己房间已有的专用凭证。密钥留空保留，`clear_key=true` 才明确清除。

管理页面不读取成员私聊或个人偏好。全局配置与管理员密码保存在同一数据目录中；正常用户接口不包含管理提示词。

## 实现依据

实时输出、生命周期和第三方 HTTP 调用采用库的标准接口；以下资料用于源码实现时核对 API，本次未据此宣称已经完成运行验证：

- [FastAPI 响应与 StreamingResponse](https://fastapi.tiangolo.com/advanced/custom-response/)
- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
- [HTTPX 异步与流式响应](https://www.python-httpx.org/async/)
- [HTTPX 超时设置](https://www.python-httpx.org/advanced/timeouts/)
- [python-qrcode SVG 生成](https://github.com/lincolnloop/python-qrcode)

模型列表标准结构参考：[OpenAI List models](https://developers.openai.com/api/reference/resources/models/methods/list)。第三方实现可通过列表路径和 ID 字段适配。
