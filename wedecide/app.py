import asyncio
from contextlib import asynccontextmanager, suppress
import json
import secrets
import time
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from . import ai, domain, engine, store
from .cli import verify_password
from .config import WEB_DIR, PUBLIC_URL, SECURE_COOKIE, ALLOWED_ORIGINS
from .models import AIInput, CreateRoom, JoinRoom, Login, ModelDiscovery, Mutation
from .realtime import Hub

hub = Hub()
coordinator = ai.Coordinator()
login_attempts = {}
password_slots = asyncio.Semaphore(2)


def authenticated(request, admin=False):
    value = store.session(request.cookies.get("wd_admin" if admin else "wd_session"))
    domain.require(value is not None and bool(value["admin"]) == admin, "请先登录管理页" if admin else "请先创建或申请加入房间", 401)
    return value["user_id"]


def ensure_guest(request, response):
    existing = store.session(request.cookies.get("wd_session"))
    if existing and not existing["admin"]:
        return existing["user_id"]
    token = store.make_session()
    response.set_cookie("wd_session", token, max_age=2592000, httponly=True, secure=SECURE_COOKIE, samesite="lax", path="/")
    return store.session(token)["user_id"]


def get_room(db, key):
    room = store.load_room(db, key)
    domain.require(room is not None, "房间不存在或已过保留期限", 404)
    return room


def current_room(key):
    with store.transaction() as db:
        room = get_room(db, key)
        if domain.tick(room):
            store.save_room(db, room)
            hub.publish(room["id"])
        return room


def safe_config(config):
    result = {**config, "providers": [ai.redact_provider(p) for p in config["providers"]]}
    return result


async def maintenance():
    while True:
        await asyncio.sleep(5)
        config = store.settings()
        with store.connect() as db:
            keys = [r[0] for r in db.execute("SELECT id FROM rooms WHERE state NOT IN ('APPROVED','NO_CONSENSUS','NO_FEASIBLE_PROPOSAL','INSUFFICIENT_DATA','CANCELLED')")]
        for key in keys:
            with store.transaction() as db:
                room = store.load_room(db, key)
                if not room:
                    continue
                changed = domain.tick(room)
                if not changed and room["state"] not in domain.TERMINAL | {"VOTING"} and time.time() - room["updated"] > config["room_idle_hours"] * 3600:
                    if room["vote"] and room["vote"]["status"] == "OPEN":
                        room["vote"].update(status="CANCELLED", finished=time.time())
                    room["state"] = "CANCELLED"
                    room["result"] = {"outcome": "CANCELLED", "at": time.time(), "explanation": "超过配置的房间空闲期限"}
                    domain.event(room, "expired", "房间因长时间无操作而关闭")
                    changed = True
                if changed:
                    store.save_room(db, room)
                    hub.publish(key)
            await asyncio.sleep(0)
        with store.transaction() as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.execute("DELETE FROM rooms WHERE state IN ('APPROVED','NO_CONSENSUS','NO_FEASIBLE_PROPOSAL','INSUFFICIENT_DATA','CANCELLED') AND updated<?", (time.time() - config["retention_days"] * 86400,))
        for key in list(login_attempts):
            if login_attempts[key][1] < time.time() - 900:
                login_attempts.pop(key, None)


@asynccontextmanager
async def lifespan(app):
    store.init()
    task = asyncio.create_task(maintenance())
    try:
        yield
    finally:
        hub.close()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await coordinator.close()


app = FastAPI(title="WeDecide", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def boundaries(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        allowed = ALLOWED_ORIGINS or {str(request.base_url).rstrip("/")}
        if origin and origin.rstrip("/") not in allowed:
            return JSONResponse({"detail": "请求来源未获允许"}, status_code=403)
        if request.method != "DELETE" and not request.headers.get("content-type", "").startswith("application/json"):
            return JSONResponse({"detail": "请使用 JSON 请求"}, status_code=415)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 131072:
                return JSONResponse({"detail": "请求超过 128 KB 限制"}, status_code=413)
        request._body = bytes(raw)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'self'; frame-ancestors 'none'"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Never echo input values: provider errors may contain secrets.
    return JSONResponse({"detail": "输入格式不正确", "fields": [".".join(map(str, e["loc"])) for e in exc.errors()]}, status_code=422)


@app.exception_handler(ValidationError)
async def model_error(request, exc):
    return JSONResponse({"detail": "字段校验失败，请检查数值范围、时间窗口和接口配置", "fields": [".".join(map(str, e["loc"])) for e in exc.errors()]}, status_code=422)


@app.exception_handler(ai.AIError)
async def ai_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.get("/api/bootstrap")
async def bootstrap(request: Request, response: Response):
    uid = ensure_guest(request, response)
    config = store.settings()
    return {"user_id": uid, "limits": {k: config[k] for k in ("max_rooms", "max_members")}, "providers": [{"id": p["id"], "name": p["name"], "model": p["model"]} for p in config["providers"] if p["enabled"]], "default_provider": config["default_provider"], "public_url": PUBLIC_URL}


@app.get("/api/rooms")
async def my_rooms(request: Request):
    uid = authenticated(request)
    result = []
    with store.connect() as db:
        for row in db.execute("SELECT data FROM rooms ORDER BY updated DESC"):
            room = json.loads(row[0])
            me = next((m for m in room["members"] if m["id"] == uid), None)
            if me:
                result.append({"id": room["id"], "code": room["code"], "title": room["scenario"]["title"], "state": room["state"], "membership": me["status"], "host": room["host_id"] == uid, "updated": room["updated"]})
            if len(result) >= 100:
                break
    return result


@app.post("/api/rooms")
async def create_room(data: CreateRoom, request: Request, response: Response):
    uid = ensure_guest(request, response)
    with store.transaction() as db:
        config = store.settings(db)
        count = db.execute("SELECT count(*) FROM rooms WHERE state NOT IN ('APPROVED','NO_CONSENSUS','NO_FEASIBLE_PROPOSAL','INSUFFICIENT_DATA','CANCELLED')").fetchone()[0]
        domain.require(count < config["max_rooms"], "当前同时开放的房间已达上限，请稍后再创建", 429)
        room = domain.new_room(uid, data, config["max_members"])
        while True:
            room["code"] = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
            if not db.execute("SELECT 1 FROM rooms WHERE code=?", (room["code"],)).fetchone():
                break
        db.execute("INSERT INTO rooms VALUES(?,?,?,?,?,?)", (room["id"], room["code"], room["state"], room["revision"], room["updated"], store.dumps(room)))
    return domain.view(room, uid)


@app.post("/api/join/{key}")
async def join_room(key: str, data: JoinRoom, request: Request, response: Response):
    uid = ensure_guest(request, response)
    with store.transaction() as db:
        room = get_room(db, key)
        existing = next((m for m in room["members"] if m["id"] == uid), None)
        if existing:
            return domain.view(room, uid, hub.online(room["id"]))
        domain.editable(room)
        domain.require(len(room["members"]) < 128, "本房间累计申请数已达上限", 429)
        domain.require(len([m for m in room["members"] if m["status"] == "pending"]) < 32, "待审核申请已满，请稍后重试", 429)
        name = data.username.strip()
        domain.require(not any(m["name"].casefold() == name.casefold() and m["status"] in {"pending", "approved"} for m in room["members"]), "此用户名已在房间中使用，请换一个")
        room["members"].append(domain.new_member(uid, name))
        domain.event(room, "join_requested", "收到新的成员加入申请")
        store.save_room(db, room)
    hub.publish(room["id"])
    return domain.view(room, uid)


@app.get("/api/rooms/{key}")
async def room_state(key: str, request: Request):
    uid = authenticated(request)
    room = current_room(key)
    result = domain.view(room, uid, hub.online(room["id"]))
    result["ai_pending"] = (room["id"], uid) in coordinator.pending
    return result


@app.post("/api/rooms/{key}/actions")
async def room_action(key: str, data: Mutation, request: Request):
    uid = authenticated(request)
    # Persist expired votes first, even if the subsequent user action is rejected.
    current_room(key)
    with store.transaction() as db:
        room = get_room(db, key)
        domain.mutate(room, uid, data.action, data.payload, data.revision, store.settings(db))
        store.save_room(db, room)
    hub.publish(room["id"])
    return domain.view(room, uid, hub.online(room["id"]))


@app.get("/api/rooms/{key}/events")
async def events(key: str, request: Request):
    domain.require(not hub.closing, "服务正在停止，请稍后重新连接", 503)
    uid = authenticated(request)
    room = current_room(key)
    domain.member(room, uid, approved=False)
    subscription = hub.subscribe(room["id"], uid)
    domain.require(subscription is not None, "打开的房间页面过多，请关闭其他标签页", 429)
    token, queue = subscription
    async def stream():
        try:
            yield "event: change\ndata: {}\n\n"
            while not hub.closing and not await request.is_disconnected():
                if not store.session(request.cookies.get("wd_session")):
                    break
                try:
                    await asyncio.wait_for(queue.get(), timeout=20)
                    if hub.closing:
                        break
                    yield "event: change\ndata: {}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            hub.remove(room["id"], token)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


@app.get("/api/rooms/{key}/messages")
async def messages(key: str, request: Request, before: int | None = None):
    uid = authenticated(request)
    room = current_room(key)
    domain.member(room, uid)
    return store.messages(room["id"], uid, before=before)


@app.post("/api/rooms/{key}/messages")
async def shared_message(key: str, data: AIInput, request: Request):
    uid = authenticated(request)
    with store.transaction() as db:
        room = get_room(db, key)
        me = domain.member(room, uid)
        domain.require(room["state"] not in domain.TERMINAL, "决策已结束")
        store.append_message(db, room["id"], uid, "user", "shared", data.text, {"name": me["name"]})
        store.save_room(db, room)
    hub.publish(room["id"])
    return {"ok": True}


@app.post("/api/rooms/{key}/ai", status_code=202)
async def room_ai(key: str, data: AIInput, request: Request):
    uid = authenticated(request)
    room = current_room(key)
    domain.member(room, uid)
    domain.require(room["state"] not in domain.TERMINAL, "决策已结束")
    domain.require(data.kind != "scenario", "场景草稿请在创建页面生成")
    if data.kind in {"preferences", "negotiate"}:
        domain.editable(room)
    config = store.settings()
    async def operation():
        return await ai.complete(config, room, uid, data.kind, data.text)
    async def complete(result, error):
        with store.transaction() as db:
            current = store.load_room(db, room["id"])
            if not current or not any(m["id"] == uid and m["status"] == "approved" for m in current["members"]):
                return
            content, metadata = (error, {"error": True}) if error else result
            metadata["input_version"] = room["input_version"]
            metadata["preference_version"] = next(m["preference_version"] for m in room["members"] if m["id"] == uid)
            store.append_message(db, room["id"], uid, "assistant", data.kind, content, metadata)
        # pending is cleared before clients reload state; task finally also removes it.
        coordinator.pending.pop((room["id"], uid), None)
        hub.publish(room["id"])
    coordinator.submit((room["id"], uid), operation, complete)
    with store.transaction() as db:
        store.append_message(db, room["id"], uid, "user", data.kind, data.text)
        current = get_room(db, room["id"])
        store.save_room(db, current)
    hub.publish(room["id"])
    return {"queued": True}


async def bounded_call(key, operation, timeout=240):
    domain.require(key not in coordinator.pending, "这个请求仍在处理中", 429)
    domain.require(len(coordinator.pending) < store.settings()["ai_queue_limit"], "AI 队列已满", 429)
    coordinator.pending[key] = asyncio.current_task()
    try:
        return await asyncio.wait_for(coordinator.run(operation), timeout=timeout)
    except asyncio.TimeoutError:
        raise HTTPException(504, "第三方请求超时，请重试") from None
    finally:
        coordinator.pending.pop(key, None)


@app.post("/api/scenario")
async def scenario_draft(data: AIInput, request: Request):
    uid = authenticated(request)
    result = await bounded_call(("scenario", uid), lambda: ai.complete(store.settings(), None, uid, "scenario", data.text))
    return {"text": result[0], **result[1]}


@app.get("/api/rooms/{key}/provider")
async def room_provider(key: str, request: Request):
    uid = authenticated(request)
    room = current_room(key)
    domain.host(room, uid)
    return {"provider_id": room["provider_id"], "provider": ai.redact_provider(room["provider"])}


@app.put("/api/rooms/{key}/provider")
async def save_provider(key: str, request: Request):
    uid = authenticated(request)
    data = await request.json()
    domain.require(isinstance(data, dict), "请求内容必须为 JSON 对象")
    with store.transaction() as db:
        room = get_room(db, key)
        domain.host(room, uid)
        domain.require(data.get("revision") == room["revision"], "配置已变化，请刷新后再保存", 409)
        domain.require(room["state"] not in domain.TERMINAL, "决策已结束")
        config = store.settings(db)
        selected = str(data.get("provider_id", ""))[:48]
        domain.require(not selected or any(p["id"] == selected and p["enabled"] for p in config["providers"]), "全局接口不存在或已停用")
        room["provider_id"] = selected
        domain.require(data.get("provider") is None or isinstance(data["provider"], dict), "供应商配置必须为 JSON 对象")
        room["provider"] = ai.merge_provider(data["provider"], room["provider"]) if data.get("provider") else None
        domain.event(room, "provider_changed", "房主更新了房间 AI 接口配置")
        store.save_room(db, room)
    hub.publish(room["id"])
    return {"ok": True}


@app.post("/api/rooms/{key}/provider/models")
async def room_models(key: str, data: ModelDiscovery, request: Request):
    uid = authenticated(request)
    room = current_room(key)
    domain.host(room, uid)
    if data.provider is not None:
        provider = ai.merge_provider(data.provider.model_dump(), room["provider"])
    else:
        selection = dict(room)
        if data.provider_id is not None:
            selection.update(provider=None, provider_id=data.provider_id)
        provider = ai.resolve_provider(store.settings(), selection)
    domain.require(provider is not None, "请先选择全局接口或填写房间专用接口")
    return {"models": await bounded_call(("models", uid), lambda: ai.discover_models(provider))}


@app.get("/api/rooms/{key}/invite.svg")
async def invitation_qr(key: str, request: Request):
    import qrcode
    from qrcode.image.svg import SvgPathFillImage
    uid = authenticated(request)
    room = current_room(key)
    domain.member(room, uid)
    url = (PUBLIC_URL or str(request.base_url).rstrip("/")) + "/r/" + room["code"]
    image = qrcode.make(url, image_factory=SvgPathFillImage, border=4)
    return Response(image.to_string(), media_type="image/svg+xml")


@app.get("/api/rooms/{key}/report")
async def report(key: str, request: Request):
    uid = authenticated(request)
    room = current_room(key)
    data = domain.view(room, uid, ())
    domain.require(data["me"]["status"] == "approved", "未获准查看报告", 403)
    # Report is shareable: omit personal preferences, original feedback, private
    # requests, private vote reasons, and the public-display capability token.
    for field in ("me", "requests", "share_token", "provider_id", "feedback"):
        data.pop(field, None)
    for vote in [data.get("vote"), *data.get("vote_history", [])]:
        if vote:
            vote.pop("my_vote", None)
    return Response(store.dumps(domain.redact_evaluations(data)), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="wedecide-{room["code"]}.json"'})


@app.get("/api/display/{token}")
async def display(token: str):
    with store.connect() as db:
        for row in db.execute("SELECT data FROM rooms"):
            room = json.loads(row[0])
            if secrets.compare_digest(room["share_token"], token):
                return domain.display_view(room)
    raise HTTPException(404, "投屏链接不存在或已过期")


@app.post("/api/admin/login")
async def admin_login(data: Login, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    attempts, when = login_attempts.get(ip, (0, 0))
    domain.require(attempts < 8 or time.time() - when > 900, "尝试次数过多，请 15 分钟后重试", 429)
    if len(login_attempts) >= 2048 and ip not in login_attempts:
        login_attempts.pop(next(iter(login_attempts)))
    with store.connect() as db:
        row = db.execute("SELECT value FROM settings WHERE key='admin_password'").fetchone()
    domain.require(row is not None, "管理员密码尚未设置，请在后端运行 python -m wedecide.cli admin-password", 403)
    async with password_slots:
        valid = await asyncio.to_thread(verify_password, data.password, row[0])
    if not valid:
        login_attempts[ip] = (attempts + 1 if time.time() - when < 900 else 1, time.time())
        raise HTTPException(401, "密码不正确")
    login_attempts.pop(ip, None)
    token = store.make_session(admin=True)
    response.set_cookie("wd_admin", token, max_age=43200, httponly=True, secure=SECURE_COOKIE, samesite="strict", path="/")
    return {"ok": True}


@app.post("/api/admin/logout")
async def admin_logout(request: Request, response: Response):
    token = request.cookies.get("wd_admin", "")
    with store.connect() as db:
        db.execute("DELETE FROM sessions WHERE token=? AND admin=1", (store.digest(token),))
    response.delete_cookie("wd_admin", path="/")
    return {"ok": True}


@app.get("/api/admin/settings")
async def admin_settings(request: Request):
    authenticated(request, True)
    return safe_config(store.settings())


@app.put("/api/admin/settings")
async def admin_save(request: Request):
    authenticated(request, True)
    data = await request.json()
    domain.require(isinstance(data, dict), "请求内容必须为 JSON 对象")
    with store.transaction() as db:
        config = store.settings(db)
        domain.require(data.get("revision") == config["revision"], "管理员配置已在另一页面更新，请重新登录页面后再保存", 409)
        config["revision"] += 1
        for key, low, high in [("max_rooms", 1, 128), ("max_members", 1, 64), ("ai_concurrency", 1, 16), ("ai_queue_limit", 1, 128), ("room_idle_hours", 1, 720), ("retention_days", 1, 365)]:
            value = data.get(key, config[key])
            domain.require(type(value) is int and low <= value <= high, f"{key} 须为 {low}–{high} 的整数")
            config[key] = value
        domain.require(config["ai_queue_limit"] >= config["ai_concurrency"], "AI 队列上限不能小于并发数")
        providers = data.get("providers", config["providers"])
        domain.require(isinstance(providers, list) and len(providers) <= 16, "最多配置 16 个全局接口")
        domain.require(all(isinstance(p, dict) for p in providers), "每个供应商必须是 JSON 对象")
        old = {p["id"]: p for p in config["providers"]}
        config["providers"] = [ai.merge_provider(p, old.get(p.get("id"))) for p in providers]
        domain.require(len({p["id"] for p in config["providers"]}) == len(providers), "供应商 ID 不能重复")
        config["default_provider"] = str(data.get("default_provider", config["default_provider"]))[:48]
        domain.require(not config["default_provider"] or any(p["id"] == config["default_provider"] and p["enabled"] for p in config["providers"]), "默认接口不存在或未启用")
        prompts = data.get("prompts", config["prompts"])
        domain.require(isinstance(prompts, dict) and all(isinstance(v, str) and len(v) <= 12000 for v in prompts.values()), "提示词格式不正确或过长")
        config["prompts"] = {k: prompts.get(k, "") for k in ("context", "chat", "preferences", "scenario", "negotiate")}
        db.execute("UPDATE settings SET value=? WHERE key='config'", (store.dumps(config),))
    async with coordinator.condition:
        coordinator.condition.notify_all()
    return safe_config(config)


@app.post("/api/admin/providers/models")
async def admin_draft_models(data: ModelDiscovery, request: Request):
    uid = authenticated(request, True)
    domain.require(data.provider is not None, "请填写接口配置")
    old = None
    if data.saved_provider_id:
        old = next((p for p in store.settings()["providers"] if p["id"] == data.saved_provider_id), None)
        domain.require(old is not None, "原供应商已被移除，请重新打开配置", 409)
        domain.require(data.provider.id == data.saved_provider_id, "编辑期间不能变更原供应商 ID")
    provider = ai.merge_provider(data.provider.model_dump(), old)
    return {"models": await bounded_call(("models", uid), lambda: ai.discover_models(provider))}


@app.post("/api/admin/providers/{provider_id}/models")
async def admin_models(provider_id: str, request: Request):
    uid = authenticated(request, True)
    provider = next((p for p in store.settings()["providers"] if p["id"] == provider_id), None)
    domain.require(provider is not None, "请先保存接口")
    return {"models": await bounded_call(("models", uid), lambda: ai.discover_models(provider))}


@app.get("/api/admin/rooms")
async def admin_rooms(request: Request):
    authenticated(request, True)
    result = []
    with store.connect() as db:
        for row in db.execute("SELECT data FROM rooms ORDER BY updated DESC LIMIT 200"):
            room = json.loads(row[0])
            result.append({"id": room["id"], "code": room["code"], "title": room["scenario"]["title"], "state": room["state"], "members": len(engine.active_members(room)), "updated": room["updated"]})
    return {"rooms": result, "ai_running": coordinator.running, "ai_queued": len(coordinator.pending)}


@app.post("/api/admin/rooms/{key}/close")
async def admin_close(key: str, request: Request):
    authenticated(request, True)
    with store.transaction() as db:
        room = get_room(db, key)
        domain.require(room["state"] not in domain.TERMINAL, "房间已结束")
        if room["vote"] and room["vote"]["status"] == "OPEN":
            room["vote"].update(status="CANCELLED", finished=time.time())
        room["state"] = "CANCELLED"
        room["result"] = {"outcome": "CANCELLED", "at": time.time(), "explanation": "由管理员关闭"}
        domain.event(room, "admin_closed", "管理员关闭了本次决策")
        store.save_room(db, room)
    hub.publish(room["id"])
    return {"ok": True}


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/admin")
async def admin_page():
    return FileResponse(WEB_DIR / "admin.html")


@app.get("/{path:path}")
async def index(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "接口不存在")
    return FileResponse(WEB_DIR / "index.html")
