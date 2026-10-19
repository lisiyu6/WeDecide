"""Authoritative room workflow; no model output can bypass these transitions."""
from copy import deepcopy
import math
import time
from fastapi import HTTPException
from pydantic import ValidationError
from . import engine
from .models import ManualPlan, Preference, Resource, Rules, Scenario
from .store import new_id

TERMINAL = {"APPROVED", "NO_CONSENSUS", "NO_FEASIBLE_PROPOSAL", "INSUFFICIENT_DATA", "CANCELLED"}


def require(condition, message, status=400):
    if not condition:
        raise HTTPException(status, message)


def member(room, user_id, approved=True):
    m = next((m for m in room["members"] if m["id"] == user_id), None)
    require(m is not None and (not approved or m["status"] == "approved"), "你尚未获准进入这个房间", 403)
    return m


def host(room, user_id):
    require(room["host_id"] == user_id, "此操作需要房主权限", 403)


def event(room, kind, text):
    room["events"].append({"id": new_id(), "kind": kind, "text": text, "at": time.time()})
    room["events"] = room["events"][-200:]


def new_member(user_id, username, status="pending"):
    username = username.strip()
    require(1 <= len(username) <= 30, "请输入 1–30 字的用户名")
    return {"id": user_id, "name": username, "status": status, "preference": None, "preference_version": 0, "confirmed": False, "attendance": "undecided", "joined": time.time()}


def new_room(user_id, data, max_members):
    rules = data.rules.model_dump()
    rules["max_members"] = min(rules["max_members"], max_members)
    now = time.time()
    room = {"id": new_id(), "code": "", "revision": 1, "state": "COLLECTING", "host_id": user_id, "created": now, "updated": now, "scenario": data.scenario.model_dump(), "rules": rules, "members": [new_member(user_id, data.username, "approved")], "agent": None, "manual_plans": [], "resources": engine.demo_resources() if data.demo else [], "resource_version": 1, "input_version": 1, "analysis_version": 0, "analysis": None, "proposals": [], "history": [], "selected_id": None, "round": 0, "vote": None, "vote_history": [], "requests": [], "feedback": [], "events": [], "provider_id": "", "provider": None, "result": None, "share_token": new_id()}
    event(room, "created", "房间已创建，等待成员加入并确认各自需求")
    return room


def invalidate(room, text):
    room["input_version"] += 1
    room["selected_id"] = None
    for req in room["requests"]:
        if req["status"] == "PENDING":
            req["status"] = "STALE"
    room["state"] = "COLLECTING"
    event(room, "changed", text)
    if room["analysis"] and room["resources"] and all(m["confirmed"] for m in engine.active_members(room)) and engine.active_members(room):
        analyze(room)


def analyze(room, prepared=None):
    members = engine.active_members(room)
    require(members and all(m["confirmed"] for m in members), "所有有效成员必须先确认个人需求")
    require(room["resources"], "请先添加候选活动")
    if room["proposals"]:
        room["history"].append({"version": room["analysis_version"], "proposals": room["proposals"], "at": time.time()})
        room["history"] = room["history"][-10:]
    analysis = prepared if prepared is not None else engine.generate(room)
    room["analysis_version"] += 1
    room["analysis"] = {k: v for k, v in analysis.items() if k != "proposals"}
    room["proposals"] = analysis["proposals"]
    room["selected_id"] = None
    room["state"] = "COMPARING" if analysis["feasible_count"] else "NEGOTIATING"
    event(room, "analysis", f"完成第 {room['analysis_version']} 版全体评价，当前搜索范围内有 {analysis['feasible_count']} 个可行时间安排")


def finish_vote(room):
    vote = room["vote"]
    if not vote or vote["status"] != "OPEN":
        return
    counts = {choice: sum(v["choice"] == choice for v in vote["votes"].values()) for choice in ("accept", "revise", "reject")}
    counts["missing"] = len(vote["electorate"]) - len(vote["votes"])
    accepted = counts["accept"] >= vote["required"]
    vote.update(status="APPROVED" if accepted else "NOT_APPROVED", counts=counts, finished=time.time())
    room["round"] += 1
    if accepted:
        room["state"] = "APPROVED"
    elif room["round"] >= room["rules"]["max_rounds"]:
        room["state"] = "NO_CONSENSUS"
    else:
        room["state"] = "NEGOTIATING"
    if room["state"] in TERMINAL:
        room["result"] = {"outcome": room["state"], "at": time.time(), "proposal": deepcopy(vote["proposal"]), "counts": counts, "required": vote["required"]}
    event(room, "vote_finished", f"第 {room['round']} 轮结束：{counts['accept']} / {len(vote['electorate'])} 人接受，需要 {vote['required']} 人")


def tick(room):
    changed = False
    vote = room["vote"]
    if vote and vote["status"] == "OPEN" and vote["deadline"] <= time.time():
        finish_vote(room)
        changed = True
    for req in room["requests"]:
        if req["status"] == "PENDING" and req["expires"] <= time.time():
            req["status"] = "EXPIRED"
            changed = True
    return changed


def editable(room):
    require(room["state"] not in TERMINAL, "本次决策已结束，记录已冻结")
    require(room["state"] != "VOTING", "投票进行中，当前成员、条件与候选方案已锁定")


def field_request(room, target_id, field, value, reason):
    target = member(room, target_id)
    require(target["confirmed"], "该成员还未确认需求")
    allowed = {"budget_max", "available_start", "available_end", "max_duration", "excluded_categories", "allowed_locations"}
    require(field in allowed, "不支持的修改条件")
    revised = Preference(**{**target["preference"], field: value})
    value = revised.model_dump()[field]
    require(len([r for r in room["requests"] if r["status"] == "PENDING"]) < 64, "待确认请求已达上限")
    req = {"id": new_id(), "member_id": target_id, "field": field, "before": target["preference"][field], "after": value, "preference_version": target["preference_version"], "input_version": room["input_version"], "reason": str(reason)[:1000], "status": "PENDING", "created": time.time(), "expires": time.time() + 86400}
    room["requests"].append(req)
    room["requests"] = room["requests"][-128:]
    event(room, "request", "已向相关成员发送条件修改请求，等待本人决定")
    return req


def negotiate(room, user_id):
    """Only proposes changes to the caller's own private conditions."""
    m = member(room, user_id)
    require(m["confirmed"], "请先确认个人需求")
    require(room["proposals"], "请先由房主生成候选方案")
    if any(p["evaluation"]["status"] == "FEASIBLE" for p in room["proposals"]):
        return "已有可行方案。优先比较活动、费用和时间的取舍；请提出你希望改变的环节，无需先放宽个人硬约束。", []
    requests = []
    for proposal in room["proposals"]:
        evaluation = proposal["evaluation"]
        fields = {v["field"] for v in evaluation["violations"] if v["member_id"] == user_id}
        if "budget_max" in fields and evaluation["cost_upper"] is not None:
            value = evaluation["cost_upper"]
            exists = any(r["member_id"] == user_id and r["field"] == "budget_max" and r["status"] == "PENDING" and r["after"] == value for r in room["requests"])
            if not exists:
                requests.append(field_request(room, user_id, "budget_max", value, f"若你愿意，此上限可消除「{proposal['title']}」对你的预算冲突；其他人的条件仍须独立满足。"))
            break
    return ("请优先让房主补充更便宜或时间更合适的候选资源。已根据你的条件生成可选请求，只有你明确同意才会生效。" if requests else "当前冲突涉及时间、地点、类别或缺失数据。请优先补充候选活动，或在个人需求中明确修改自己的条件；系统不会替你放宽条件。"), requests


def mutate(room, user_id, action, payload, revision, limits):
    m = member(room, user_id)
    tick(room)
    independent = {"preference", "vote", "answer_request", "feedback", "attendance"}
    if action not in independent:
        require(revision == room["revision"], "房间已经更新，请刷新后重新操作", 409)
    if action == "attendance":
        require(payload.get("value") in {"yes", "no", "undecided"}, "请选择参与意愿")
        m["attendance"] = payload["value"]
        event(room, "attendance", "一位成员更新了实际参与意愿（不改变已记录的正式投票）")
        return
    require(room["state"] not in TERMINAL, "本次决策已结束，记录已冻结")
    if action == "approve" or action == "reject_join":
        host(room, user_id)
        editable(room)
        target = member(room, payload.get("member_id"), approved=False)
        require(target["status"] == "pending", "这条加入申请已处理", 409)
        if action == "approve":
            require(len(engine.active_members(room)) < min(room["rules"]["max_members"], limits["max_members"]), "房间人数已达上限")
            target["status"] = "approved"
            invalidate(room, f"{target['name']} 已获准加入，等待本人确认需求")
        else:
            target["status"] = "rejected"
            event(room, "join_rejected", "房主拒绝了一条加入申请")
    elif action == "preference":
        editable(room)
        require(payload.get("preference_version") == m["preference_version"], "你的需求已在其他页面更新，请重新核对", 409)
        pref = Preference(**payload.get("preference", {}))
        require(not pref.unresolved, f"还有 {len(pref.unresolved)} 项待确认问题，请在问题卡片中逐条处理后再确认")
        m.update(preference=pref.model_dump(), preference_version=m["preference_version"] + 1, confirmed=True)
        invalidate(room, f"{m['name']} 已确认第 {m['preference_version']} 版个人需求")
    elif action == "resources":
        host(room, user_id)
        editable(room)
        values = payload.get("resources", [])
        require(isinstance(values, list) and len(values) <= 20, "候选活动最多 20 个")
        require(all(isinstance(v, dict) for v in values), "每个候选活动必须是 JSON 对象")
        resources = [Resource(**v).model_dump() for v in values]
        for r in resources:
            r["id"] = r["id"] or new_id()
        require(len({r["id"] for r in resources}) == len(resources), "候选活动 ID 重复")
        room["resources"] = resources
        room["resource_version"] += 1
        invalidate(room, "房主更新候选活动，所有方案按新数据重新评价")
    elif action == "agent_toggle":
        host(room, user_id)
        require(isinstance(payload.get("enabled"), bool), "请选择是否自动推进")
        room["agent"] = {**(room.get("agent") or {}), "enabled":payload["enabled"]}
        event(room, "agent_control", "房主调整 Agent 后续自动推进状态")
    elif action == "agent_draft":
        host(room, user_id)
        editable(room)
        report = room.get("agent")
        require(report and report["input_version"] == room["input_version"], "Agent 草稿已过期，请让 Agent 继续后再采纳", 409)
        require(not report.get("running") and not report.get("error") and not report.get("stale"), "Agent 仍在处理或结果不可用，请继续后重试")
        require(not report.get("applied"), "这份 Agent 草稿已采纳", 409)
        additions = [Resource(**resource).model_dump() for resource in report.get("resources", [])]
        plans = [ManualPlan(**plan).model_dump() for plan in report.get("plans", [])]
        require(len(room["resources"])+len(additions)<=20, "候选条目总数最多 20 个，请先整理已有候选")
        known = {resource["id"] for resource in room["resources"]}
        for resource in additions:
            require(resource["id"] not in known, "Agent 建议的候选标识重复，请重新生成")
            resource["confirmed"] = resource["verified"] = False
            known.add(resource["id"])
        require(all(step["resource_id"] in known for plan in plans for step in plan["steps"]), "Agent 行程引用了未知候选，请重新生成")
        require(len(room.get("manual_plans", []))+len(plans)<=6, "自定义行程最多 6 个")
        for plan in plans:
            plan["id"] = new_id()
        room["resources"].extend(additions)
        room["manual_plans"] = room.get("manual_plans", [])+plans
        report["applied"] = True
        room["resource_version"] += 1
        invalidate(room, "房主采纳 Agent 建议为候选草稿，需核对事实并全体重新评价")
    elif action == "plans":
        host(room, user_id)
        editable(room)
        values = payload.get("plans", [])
        require(isinstance(values, list) and len(values) <= 6, "自定义方案最多 6 个")
        require(all(isinstance(value, dict) for value in values), "方案必须是 JSON 对象")
        plans = [ManualPlan(**value).model_dump() for value in values]
        resources = {resource["id"] for resource in room["resources"]}
        for plan in plans:
            plan["id"] = plan["id"] or new_id()
            require(all(step["resource_id"] in resources for step in plan["steps"]), "自定义方案引用的活动已不存在")
        require(len({plan["id"] for plan in plans}) == len(plans), "方案标识重复")
        room["manual_plans"] = plans
        invalidate(room, "房主更新自定义行程，需按最新条件重新分析")
    elif action == "settings":
        host(room, user_id)
        editable(room)
        require(room["round"] == 0 and not room["vote_history"] and not room["vote"], "正式投票开始后，决策规则不可更改")
        rules = Rules(**payload.get("rules", room["rules"]))
        require(len(engine.active_members(room)) <= rules.max_members <= limits["max_members"], "人数上限不能低于现有成员数或高于系统限制")
        room["rules"] = rules.model_dump()
        room["scenario"] = Scenario(**payload.get("scenario", room["scenario"])).model_dump()
        invalidate(room, "房主更新场景与规则")
    elif action == "analyze":
        host(room, user_id)
        editable(room)
        analyze(room)
    elif action == "select":
        host(room, user_id)
        editable(room)
        proposal = next((p for p in room["proposals"] if p["id"] == payload.get("proposal_id")), None)
        require(proposal is not None and proposal["input_version"] == room["input_version"], "方案已过期，请重新分析", 409)
        require(proposal["evaluation"]["status"] == "FEASIBLE", "只有通过硬约束检查的方案可以投票")
        room["selected_id"] = proposal["id"]
        event(room, "selected", f"房主选择了「{proposal['title']}」等待正式投票")
    elif action == "start_vote":
        host(room, user_id)
        editable(room)
        require(room["round"] < room["rules"]["max_rounds"], "已达到正式投票轮数上限")
        require(len(room["vote_history"]) < 20, "本房间投票历史已达上限，请结束并创建新房间")
        proposal = next((p for p in room["proposals"] if p["id"] == room["selected_id"]), None)
        require(proposal is not None and proposal["input_version"] == room["input_version"], "请先选择当前版本的可行方案")
        current = engine.evaluate(room, proposal["itinerary"])
        require(current["status"] == "FEASIBLE", "方案不再满足全体成员条件，请重新分析")
        members = engine.active_members(room)
        if room["vote"]:
            room["vote_history"].append(room["vote"])
        room["vote"] = {"id": new_id(), "status": "OPEN", "round": room["round"] + 1, "proposal": deepcopy(proposal), "electorate": [{"id": x["id"], "name": x["name"], "preference_version": x["preference_version"]} for x in members], "resource_version": room["resource_version"], "input_version": room["input_version"], "threshold": room["rules"]["threshold"], "required": math.ceil(len(members) * room["rules"]["threshold"] - 1e-9), "started": time.time(), "deadline": time.time() + room["rules"]["vote_seconds"], "votes": {}}
        room["state"] = "VOTING"
        event(room, "vote_started", "正式投票开始，已锁定成员、方案版本、条件版本与截止时间")
    elif action == "vote":
        vote = room["vote"]
        require(vote and vote["status"] == "OPEN" and payload.get("session_id") == vote["id"], "当前投票已结束或版本已变化", 409)
        require(user_id in {x["id"] for x in vote["electorate"]}, "你不在本轮投票名单中", 403)
        require(user_id not in vote["votes"], "你已经提交本轮正式投票", 409)
        require(payload.get("choice") in {"accept", "revise", "reject"}, "请选择接受、修改或拒绝")
        reason = str(payload.get("reason", ""))[:2000]
        vote["votes"][user_id] = {"choice": payload["choice"], "reason": reason, "at": time.time()}
        event(room, "vote_cast", f"已有 {len(vote['votes'])} / {len(vote['electorate'])} 人提交投票")
        if len(vote["votes"]) == len(vote["electorate"]):
            finish_vote(room)
    elif action == "cancel_vote":
        host(room, user_id)
        require(room["vote"] and room["vote"]["status"] == "OPEN", "没有正在进行的投票")
        room["vote"].update(status="CANCELLED", finished=time.time())
        room["state"] = "NEGOTIATING"
        event(room, "vote_cancelled", "房主取消本轮投票；已投票记录保留且不会继承")
    elif action == "withdraw":
        require(user_id != room["host_id"], "房主请使用结束决策，避免留下无人管理的房间")
        if room["vote"] and room["vote"]["status"] == "OPEN":
            room["vote"].update(status="CANCELLED", finished=time.time())
            event(room, "vote_cancelled", "成员明确退出，本轮投票取消，旧票不继承")
        m["status"] = "withdrawn"
        invalidate(room, f"{m['name']} 自行退出本次决策，重新计算成员数与分摊费用")
    elif action == "request_change":
        editable(room)
        require(payload.get("member_id", user_id) == user_id, "个人条件请求只能针对自己；其他成员通过协商区提出建议", 403)
        field_request(room, user_id, payload.get("field"), payload.get("value"), payload.get("reason", "本人提出修改"))
    elif action == "answer_request":
        editable(room)
        req = next((r for r in room["requests"] if r["id"] == payload.get("request_id")), None)
        require(req is not None and req["member_id"] == user_id, "只有本人可以回应此请求", 403)
        require(req["status"] == "PENDING" and req["preference_version"] == m["preference_version"] and req["input_version"] == room["input_version"], "此请求已失效，请按最新条件重新协商", 409)
        require(payload.get("decision") in {"accept", "reject"}, "请选择同意或拒绝")
        if payload["decision"] == "reject":
            req["status"] = "REJECTED"
            event(room, "request_rejected", "成员拒绝条件修改，原条件保持有效")
        else:
            pref = Preference(**{**m["preference"], req["field"]: payload.get("value", req["after"])})
            m.update(preference=pref.model_dump(), preference_version=m["preference_version"] + 1)
            req.update(status="ACCEPTED", applied_value=pref.model_dump()[req["field"]])
            invalidate(room, "成员本人接受条件修改，全体方案已重新评价")
    elif action == "negotiate":
        editable(room)
        negotiate(room, user_id)
    elif action == "feedback":
        require(room["proposals"], "生成候选方案后才能提交反馈")
        text = str(payload.get("text", "")).strip()
        require(1 <= len(text) <= 2000, "反馈须为 1–2000 字")
        summary = str(payload.get("summary", ""))[:1000].strip()
        proposal_id = payload.get("proposal_id") or room.get("selected_id")
        require(proposal_id is None or any(p["id"] == proposal_id for p in room["proposals"]), "反馈方案版本已变化", 409)
        room["feedback"].append({"id": new_id(), "member_id": user_id, "text": text, "summary": summary, "proposal_id": proposal_id, "version": room["analysis_version"], "at": time.time()})
        room["feedback"] = room["feedback"][-100:]
        event(room, "feedback", "收到一条方案反馈")
    elif action == "finish":
        host(room, user_id)
        require(room["state"] != "VOTING", "请先取消正在进行的投票")
        reason = payload.get("outcome", "CANCELLED")
        require(reason in TERMINAL - {"APPROVED"}, "不支持的结束原因")
        if reason == "NO_CONSENSUS":
            require(any(p["evaluation"]["status"] == "FEASIBLE" and p["input_version"] == room["input_version"] for p in room["proposals"]), "当前没有有效可行方案，请选择无可行方案、信息不足或主动结束")
        if reason == "NO_FEASIBLE_PROPOSAL":
            require(room["analysis"] and not room["analysis"]["feasible_count"] and room["proposals"] and all(p["evaluation"]["status"] == "INFEASIBLE" for p in room["proposals"]), "当前数据不支持无可行方案结论")
        if reason == "INSUFFICIENT_DATA":
            require(not room["proposals"] or any(p["evaluation"]["status"] == "UNKNOWN" for p in room["proposals"]), "当前方案没有缺失数据，请选择其他结束原因")
        room["state"] = reason
        room["result"] = {"outcome": reason, "at": time.time(), "explanation": str(payload.get("explanation", "由房主结束本次决策"))[:1000]}
        event(room, "finished", "决策已结束并保存报告")
    else:
        raise HTTPException(400, "未知操作")


def redact_evaluations(value, user_id=None):
    """Keep the agreed score matrix, but not others' personal scoring inputs."""
    if isinstance(value, list):
        for item in value:
            redact_evaluations(item, user_id)
    elif isinstance(value, dict):
        for utility in value.get("utilities", []):
            if utility.get("member_id") != user_id:
                utility.pop("dimensions", None)
        for violation in value.get("violations", []):
            if violation.get("member_id") != user_id:
                violation["member_id"] = None
        for child in value.values():
            if isinstance(child, (dict, list)):
                redact_evaluations(child, user_id)
    return value


def public_vote(vote, user_id=None):
    if not vote:
        return None
    result = {k: deepcopy(v) for k, v in vote.items() if k != "votes"}
    result["submitted"] = list(vote["votes"])
    result["my_vote"] = deepcopy(vote["votes"].get(user_id))
    return result


def view(room, user_id, online=()):
    m = member(room, user_id, approved=False)
    if m["status"] != "approved":
        return {"id": room["id"], "code": room["code"], "revision": room["revision"], "scenario": {"title": room["scenario"]["title"]}, "state": room["state"], "me": {"id": m["id"], "name": m["name"], "status": m["status"]}}
    r = {k: deepcopy(room[k]) for k in ("id", "code", "revision", "state", "host_id", "created", "updated", "scenario", "rules", "resources", "resource_version", "input_version", "analysis_version", "analysis", "proposals", "history", "selected_id", "round", "events", "result", "provider_id")}
    r["members"] = [{k: deepcopy(x[k]) for k in ("id", "name", "status", "confirmed", "preference_version", "attendance")} | {"online": x["id"] in online} for x in room["members"] if x["status"] == "approved" or user_id == room["host_id"]]
    r["agent"] = deepcopy(room.get("agent"))
    r["manual_plans"] = deepcopy(room.get("manual_plans", []))
    r["me"] = deepcopy(m)
    r["vote"] = public_vote(room["vote"], user_id)
    r["vote_history"] = [public_vote(v, user_id) for v in room["vote_history"]]
    r["requests"] = [deepcopy(q) for q in room["requests"] if q["member_id"] == user_id]
    r["feedback"] = [deepcopy(f) if f["member_id"] == user_id else {"summary": f["summary"], "version": f["version"]} for f in room["feedback"] if f["member_id"] == user_id or f["summary"]]
    r["has_custom_provider"] = bool(room["provider"])
    if user_id == room["host_id"]:
        r["share_token"] = room["share_token"]
    if room["result"] and room["result"].get("proposal"):
        attendees = [x for x in engine.active_members(room) if x["attendance"] != "no"]
        r["attendance_evaluation"] = engine.evaluate(room, room["result"]["proposal"]["itinerary"], members=attendees)
        r["attendance_provisional"] = any(x["attendance"] == "undecided" for x in attendees)
    return redact_evaluations(r, user_id)


def display_view(room):
    return {"scenario": room["scenario"], "state": room["state"], "member_count": len(engine.active_members(room)), "ready_count": sum(m["confirmed"] for m in engine.active_members(room)), "round": room["round"], "proposals": [{"title": p["title"], "evaluation": {k: p["evaluation"][k] for k in ("status", "score", "average", "minimum", "coverage", "cost", "start", "end")}} for p in room["proposals"]], "vote": {"deadline": room["vote"]["deadline"], "status": room["vote"]["status"], "submitted": len(room["vote"]["votes"]), "total": len(room["vote"]["electorate"]), "round": room["vote"]["round"], "required": room["vote"]["required"]} if room["vote"] else None, "result": {"outcome": room["result"]["outcome"]} if room["result"] else None}
