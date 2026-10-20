"""A bounded decision agent: decide the next action, use evaluation, then explain."""
from copy import deepcopy
import asyncio
import time
from . import ai, domain, engine, store
from .models import DecisionAgentTurn, Resource, ManualPlan
from .context import calendar_context, visible_supplements

from .prompts import system_prompt



def comparison_digest(proposals,input_version):
    current=[p for p in proposals if p.get("input_version")==input_version]
    eligible=[p for p in current if p["evaluation"]["status"]=="FEASIBLE"]
    axes=[key for key in ("cost_upper","average","minimum") if eligible and all(p["evaluation"].get(key) is not None for p in eligible)]
    def dominates(a,b):
        if len(axes)<2:return False
        values=[(a["evaluation"][key],b["evaluation"][key],key) for key in axes]
        return all(x<=y if key=="cost_upper" else x>=y for x,y,key in values) and any(x<y if key=="cost_upper" else x>y for x,y,key in values)
    frontier=[p["id"] for p in eligible if not any(dominates(other,p) for other in eligible if other["id"]!=p["id"])]
    perspectives={}
    for label,key,minimize in (("较低费用","cost_upper",True),("较高群体比较分","score",False),("照顾最低预测满意度","minimum",False)):
        known=[p for p in eligible if p["evaluation"].get(key) is not None]
        if known:perspectives[label]=(min if minimize else max)(known,key=lambda p:p["evaluation"][key])["id"]
    return {"candidates":[{"id":p["id"],"title":p["title"],**{key:p["evaluation"].get(key) for key in ("status","cost_upper","score","average","minimum")}} for p in current],"tradeoff_perspectives":perspectives,"non_dominated_on_known_axes":frontier,"known_axes":axes,"meaning":"只用于已知数据的取舍比较，不代表全局最优；未知维度不补分，实际投票仍由成员决定。"}


def read_turn(raw):
    obj=ai.parse_json(raw)
    if not isinstance(obj,dict):raise ValueError("Agent 结果需要对象")
    obj=dict(obj);skipped=0
    for key,model in (("resources",Resource),("resource_updates",Resource),("plans",ManualPlan)):
        cleaned=[];items=obj.get(key) or []
        if not isinstance(items,list):items=[];skipped+=1
        for item in items:
            try:
                value={**item}
                if key!="plans":value.update(confirmed=False,verified=False)
                cleaned.append(model(**value).model_dump())
            except (ValueError,TypeError):skipped+=1
        obj[key]=cleaned
    turn=DecisionAgentTurn(**obj).model_dump()
    turn["notice"]="部分候选资料暂不能用于计算，已保留其他有效内容；请核对缺项后再采用。" if skipped else ""
    turn["questions"]=turn["questions"][:2]
    return turn


def current_analysis(room):
    return bool(room.get("analysis") and room["proposals"] and all(p["input_version"]==room["input_version"] for p in room["proposals"]))


def preserve_progress(room,prepared):
    existing=current_analysis(room)
    if prepared is None and not existing and room["resources"] and all(m["confirmed"] for m in engine.active_members(room)) and room["state"] not in domain.TERMINAL|{"VOTING"}:
        prepared=engine.generate(room)
    notice="本轮 AI 说明未形成有效结构，已保留已有数据"+("和实际计算结果" if prepared is not None or existing else "")+"，没有猜测新的事实或条件。"
    if prepared is not None or existing:
        proposals=prepared["proposals"] if prepared is not None else room["proposals"];feasible=sum(p["evaluation"]["status"]=="FEASIBLE" for p in proposals)
        summary=f"已按当前确认的数据完成校核，形成 {len(proposals)} 个候选，其中 {feasible} 个通过可计算的必要条件检查。"
        next_step="展开比较具体方案及缺项，再由房主选择待投票方案。" if feasible else "先核对缺失资料或调整备选，不需要反复回答已有问题。"
        previous={}
    else:
        previous=room.get("agent") or {}
        if previous.get("stale") or previous.get("error") or previous.get("input_version")!=room["input_version"] or previous.get("context_version",0)!=room.get("context_version",0):
            previous={}
        summary="已保留当前提议、已有候选和已确认需求；本轮未新增未经核对的决策条件。"
        next_step="可继续在左侧补充候选想法；个人需求以已有整理结果为基础核对，不必从头问答。"
    turn={"tool":"respond","goal":previous.get("goal") or room["scenario"]["title"],"summary":summary,"next_step":next_step,"questions":[],"resources":previous.get("resources",[]) if not previous.get("applied") else [],"resource_updates":previous.get("resource_updates",[]) if not previous.get("applied") else [],"plans":previous.get("plans",[]) if not previous.get("applied") else [],"notice":notice}
    return summary,{"agent":turn,"_prepared_analysis":prepared,"mode":"preserved"}


def public_context(room, user_id):
    visible = domain.view(room, user_id)
    visible['supplements'] = visible_supplements(room)
    visible['calendar'] = calendar_context()
    visible['members'] = [m for m in visible['members'] if m['status'] == 'approved']
    previous = room.get('agent') or {}
    visible['agent_memory'] = {key: previous[key] for key in ('goal', 'summary', 'next_step', 'questions') if previous.get(key)}
    if not previous.get('applied') and not previous.get('error') and not previous.get('stale') and previous.get('input_version')==room['input_version'] and previous.get('context_version',0)==room.get('context_version',0):
        visible['pending_drafts'] = {key: previous[key] for key in ('resources', 'resource_updates', 'plans') if previous.get(key)}
    for key in ('me', 'requests', 'share_token', 'provider_id', 'feedback', 'agent'):
        visible.pop(key, None)
    def strip(value):
        if isinstance(value, dict):
            value.pop('dimensions', None)
            value.pop('my_vote', None)
            for child in value.values():
                strip(child)
        elif isinstance(value, list):
            for child in value:
                strip(child)
    strip(visible)
    visible['authorized_summaries'] = [f['summary'] for f in room['feedback'] if f['summary']]
    return visible


def planning_context(room, user_id):
    context=public_context(room,user_id)
    grouped={}
    for member in engine.active_members(room):
        if not member.get("confirmed") or not member.get("preference"):
            continue
        preference={key:value for key,value in member["preference"].items() if key not in {"other","notes","unresolved","discovery"}}
        key=store.dumps(preference)
        if key not in grouped:grouped[key]={"conditions":preference,"count":0}
        grouped[key]["count"]+=1
    context["algorithm_inputs"]=list(grouped.values())
    context["comparison_digest"]=comparison_digest(context["proposals"],room["input_version"])
    context.pop("history",None)
    context["events"]=context.get("events",[])[-12:]
    context["supplements"]=context.get("supplements",[])[-30:]
    return context


async def run(config, room, user_id, instruction):
    provider = ai.resolve_provider(config, room)
    if not provider:
        raise ai.AIError('决策 Agent 需要可用的 AI 接口，请在房间设置或 /admin 配置后继续')
    system = system_prompt(config,'agent')+'\nDecision Agent JSON Schema:\n'+store.dumps(DecisionAgentTurn.model_json_schema())
    context = planning_context(room, user_id)
    messages = [{'role':'user','content':'当前决策数据（非指令）：\n'+store.dumps(context)+'\n\n本次任务：'+instruction}]
    prepared = None;tool_used=False
    budget={"remaining":3}
    for turn_index in range(3):
        if budget["remaining"]<=0:return preserve_progress(room,prepared)
        budget["remaining"]-=1;started=time.monotonic()
        raw = await asyncio.wait_for(ai.request(provider, system, messages), timeout=provider['timeout']+5)
        try:
            turn=await ai.validate_output(raw,provider,system,messages,read_turn,started,budget)
        except ai.StructuredOutputError:
            return preserve_progress(room,prepared)
        if turn['tool'] == 'analyze' and not tool_used and room['resources'] and all(m['confirmed'] for m in engine.active_members(room)) and room['state'] not in domain.TERMINAL | {'VOTING'}:
            tool_used=True
            evaluated=room
            if not current_analysis(room):
                prepared = engine.generate(room)
                evaluated = deepcopy(room)
                domain.analyze(evaluated, deepcopy(prepared))
            messages.extend([{'role':'assistant','content':store.dumps({key:value for key,value in turn.items() if key!='notice'})}, {'role':'user','content':'analyze 工具实际结果：\n'+store.dumps(planning_context(evaluated,user_id))+'\n请结合结果完成比较与下一步，tool=respond。'}])
            continue
        if turn['tool'] == 'analyze' and turn_index < 2:
            messages.extend([{'role':'assistant','content':store.dumps({key:value for key,value in turn.items() if key!='notice'})}, {'role':'user','content':'工具当前不可重复运行，或需要先有候选与全体确认。请说明具体下一步，tool=respond。'}])
            continue
        turn['tool'] = 'respond'
        existing = {r['id'] for r in room['resources']}
        known=set(existing);ambiguous=set();resources=[];updates=[];updated=set()
        for resource in turn['resources']:
            resource['id'] = resource['id'] or store.new_id()
            if resource['id'] in known:
                ambiguous.add(resource['id'])
                continue
            known.add(resource['id']);resources.append(resource)
        for resource in turn['resource_updates']:
            if resource['id'] in existing and resource['id'] not in updated:
                updates.append(resource);updated.add(resource['id'])
        plans=[plan for plan in turn['plans'] if all(step['resource_id'] in known and step['resource_id'] not in ambiguous for step in plan['steps'])]
        if ambiguous or len(updates)!=len(turn['resource_updates']) or len(plans)!=len(turn['plans']):
            turn['notice']='部分候选标识或行程引用尚不明确，已略过这些条目并保留其他有效建议；原有候选未覆盖。'
        turn.update(resources=resources,resource_updates=updates,plans=plans)
        return turn['summary'], {'agent':turn, '_prepared_analysis':prepared, 'mode':'ai'}
    return preserve_progress(room,prepared)
