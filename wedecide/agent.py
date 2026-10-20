"""A bounded decision agent: decide the next action, use evaluation, then explain."""
from copy import deepcopy
import asyncio
import time
from . import ai, domain, engine, store
from .models import DecisionAgentTurn, DecisionSimulation, Resource, ManualPlan
from .context import calendar_context, visible_supplements

from .prompts import system_prompt
from .decision_tools import comparison_digest, algorithm_status, analysis_is_current, decision_progress, simulate






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
    return analysis_is_current(room)


def preserve_progress(room,prepared,tool_results=None):
    existing=current_analysis(room)
    if prepared is None and not existing and room["resources"] and all(m["confirmed"] for m in engine.active_members(room)) and room["state"] not in domain.TERMINAL|{"VOTING"}:
        prepared=engine.generate(room)
    notice="本轮 AI 说明暂未完成，已保留已有数据"+("和实际计算结果" if prepared is not None or existing else "")+"，没有猜测新的事实或条件。"
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
    turn["tool_results"]=tool_results or []
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
    context["algorithm_status"]=algorithm_status(room)
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
    prepared=None;evaluated=room;used=set();tool_results=[]
    budget={"remaining":3}
    for turn_index in range(3):
        if budget["remaining"]<=0:return preserve_progress(room,prepared,tool_results)
        budget["remaining"]-=1;started=time.monotonic()
        try:
            raw = await asyncio.wait_for(ai.request(provider, system, messages), timeout=provider['timeout']+5)
        except (ai.AIError,TimeoutError):
            if prepared is not None or current_analysis(evaluated) or tool_results:
                return preserve_progress(room,prepared,tool_results)
            raise
        try:
            turn=await ai.validate_output(raw,provider,system,messages,read_turn,started,budget)
        except ai.StructuredOutputError:
            return preserve_progress(room,prepared,tool_results)
        status=algorithm_status(evaluated)
        # Ready data always reaches the real engine before a public conclusion,
        # even if a compatible model initially skips its analyze instruction.
        if (turn['tool']=='analyze' or status['needs_analysis']) and 'analyze' not in used and status['can_analyze']:
            used.add('analyze')
            if not current_analysis(evaluated):
                prepared=engine.generate(room)
                evaluated=deepcopy(room)
                domain.analyze(evaluated,deepcopy(prepared))
            progress=decision_progress(evaluated)
            receipt={'tool':'analyze','hypothetical':False,'input_version':room['input_version'],'analysis_version':evaluated['analysis_version'],'summary':progress['summary'],'counts':progress['counts']}
            tool_results.append(receipt)
            messages.extend([{'role':'assistant','content':store.dumps({key:value for key,value in turn.items() if key!='notice'})},{'role':'user','content':'analyze 工具实际结果：\n'+store.dumps(planning_context(evaluated,user_id))+'\n请读取真实校核与版本变化，完成比较和下一步。必要时可调用一次只读 simulate，否则 tool=respond。'}])
            continue
        if turn['tool']=='simulate' and 'simulate' not in used:
            used.add('simulate')
            try:
                receipt=simulate(evaluated,DecisionSimulation(**turn['simulation']))
            except ValueError:
                receipt={'tool':'simulate','hypothetical':True,'input_version':room['input_version'],'error':'模拟未执行：需要可编辑阶段、全体确认，以及当前活动资源的有效行程或公平性权重。'}
            tool_results.append(receipt)
            messages.extend([{'role':'assistant','content':store.dumps({key:value for key,value in turn.items() if key!='notice'})},{'role':'user','content':'simulate 工具实际结果（只读假设，不改变正式数据）：\n'+store.dumps(receipt)+'\n基于真实结果完成取舍说明，tool=respond。'}])
            continue
        if turn['tool'] in {'analyze','simulate'} and turn_index<2:
            messages.extend([{'role':'assistant','content':store.dumps({key:value for key,value in turn.items() if key!='notice'})},{'role':'user','content':'工具已调用或当前前提不满足；请使用已有真实结果说明下一步，tool=respond。'}])
            continue
        turn['tool'] = 'respond'
        turn['tool_results']=tool_results
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
    return preserve_progress(room,prepared,tool_results)
