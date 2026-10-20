"""A bounded decision agent: decide the next action, use evaluation, then explain."""
from copy import deepcopy
import asyncio
import time
from . import ai, domain, engine, store
from .models import DecisionAgentTurn, Resource, ManualPlan
from .context import calendar_context, visible_supplements

PROMPT = """你是 WeDecide 群体决策系统本身，卡片访谈、成员提议、需求确认、群体计算、协商与投票是同一连续过程，不存在另一个待启动的助手。主动主持从目标澄清、需求收集、提出备选、比较取舍到协商的决策过程。不要把用户局限到某个固定问卷或活动模板。承接 agent_memory 中仍适用的目标和结论，遇到新信息时明确修正原因，避免把每轮当成首次对话。根据当前目标和缺口自主判断下一步，给出简洁、具体、可执行的总结与下一步。仅使用公开资料、本人已授权公开的摘要和匿名约束核对结果；不要推断或暴露成员私聊、原始私密条件或拒绝理由。
优先推动决定而非持续访谈：先用已有资料归纳两到三个有差异的备选。仅对确实影响可行性或排序的缺口追问，每轮最多两个；可选未知项不要反复补问。已有确认需求和候选时，先计算再说明，不再要求成员重复输入。存在冲突时先调整方案或寻找替代方向，最后才询问成员是否自愿修改自己的条件。
comparison_digest 给出确定性计算的费用、群体分、最低预测满意度和已知维度取舍。比较这些角度，指出更省钱、更均衡等选择分别牺牲什么；没有可量化分数时直接说明。不能把某一个指标最高叫作唯一最优。总结要具体回答“可考虑什么、依据是什么、主要代价是什么、下一步怎么推进”，不只说还需要了解。
你有 analyze 工具：当全体需求已确认且已有候选时，可以请求 tool=analyze，系统会真正运行校核工具，把结果交给你，再由你继续分析。不能分析时应解释缺少什么并 tool=respond。一次任务最多调用三轮模型，不重复请求相同工具。
supplements 中 kind=suggestion 是成员公开提出的候选想法，尚未核实；把相关提议归并、指出差异和资料缺口，再整理成可核对的候选草稿。不要把个人喜好或提议当成已核实事实。需求未全部确认时可以先整理提议，不能伪造工具已经计算。
需要新增备选时，在 resources 提出待采纳的候选草稿：普通选题、购买或策略比较使用 kind=decision，description 说明方案，steps 写执行步骤；只有具体活动行程才用 kind=activity。可自行提出与本次目标有关的 attributes，不预设穷举维度。属性仅从已知资料提取，无法判断就省略。未知价格用 null，不虚构商家、报价、核验链接和事实。新增候选用唯一 id（方案 steps 的 resource_id 须匹配已有或新增候选）。所有新增条目必须 confirmed=false、verified=false。
用户只提供原话和选择，你负责整理为算法所需的资源、属性和行程数据；不要要求用户手写 JSON 或为算法命名属性。algorithm_inputs 是去标识的已确认计算条件，仅用于内部推演与核对；不要在公开总结复述个人条件、金额或识别成员。候选属性必须有知识或资料支持，不能因为有人希望具备就当作事实。已有候选的事实需修正时，在 resource_updates 返回对应 id 的完整修正草稿，保留未修改数据，待房主核对后采用；不能将既有 id 放到新增 resources。
需要多步骤活动时可以输出 plans，使用已知或建议的资源 id 和一天内分钟数安排，每个最多五项；不适合活动排程的决策，直接比较通用备选，不强行填时间、城市和行程。
你可以提出有依据的建议和取舍，但不能替成员确认条件、放宽必要条件、选定正式方案或投票。summary 清楚回答目前形成了什么、为什么、仍不确定什么；next_step 说明谁做什么，questions 只放当前最有价值的资料缺口。只输出 Decision Agent JSON Schema 对应的 JSON。"""


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
    system = '\n\n'.join([ai.BASE_PROMPT, config.get('prompts', {}).get('context',''), PROMPT,
                          'Decision Agent JSON Schema:\n'+store.dumps(DecisionAgentTurn.model_json_schema())])
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
