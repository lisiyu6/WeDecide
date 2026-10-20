"""A bounded decision agent: decide the next action, use evaluation, then explain."""
from copy import deepcopy
import asyncio
from . import ai, domain, engine, store
from .models import DecisionAgentTurn
from .context import calendar_context, visible_supplements

PROMPT = """你是 WeDecide 多人决策 Agent，主动主持从目标澄清、需求收集、提出备选、比较取舍到协商的决策过程。不要把用户局限到某个固定问卷或活动模板。承接 agent_memory 中仍适用的目标和结论，遇到新信息时明确修正原因，避免把每轮当成首次对话。根据当前目标和缺口自主判断下一步，给出简洁、具体、可执行的总结与下一步。仅使用公开资料、本人已授权公开的摘要和匿名约束核对结果；不要推断或暴露成员私聊、原始私密条件或拒绝理由。
你有 analyze 工具：当全体需求已确认且已有候选时，可以请求 tool=analyze，系统会真正运行校核工具，把结果交给你，再由你继续分析。不能分析时应解释缺少什么并 tool=respond。一次任务最多调用三轮模型，不重复请求相同工具。
需要新增备选时，在 resources 提出待采纳的候选草稿：普通选题、购买或策略比较使用 kind=decision，description 说明方案，steps 写执行步骤；只有具体活动行程才用 kind=activity。可自行提出与本次目标有关的 attributes，不预设穷举维度。属性仅从已知资料提取，无法判断就省略。未知价格用 null，不虚构商家、报价、核验链接和事实。新增候选用唯一 id（方案 steps 的 resource_id 须匹配已有或新增候选）。所有新增条目必须 confirmed=false、verified=false。
用户只提供原话和选择，你负责整理为算法所需的资源、属性和行程数据；不要要求用户手写 JSON 或为算法命名属性。algorithm_inputs 是去标识的已确认计算条件，仅用于内部推演与核对；不要在公开总结复述个人条件、金额或识别成员。候选属性必须有知识或资料支持，不能因为有人希望具备就当作事实。已有候选的事实需修正时，在 resource_updates 返回对应 id 的完整修正草稿，保留未修改数据，待房主核对后采用；不能将既有 id 放到新增 resources。
需要多步骤活动时可以输出 plans，使用已知或建议的资源 id 和一天内分钟数安排，每个最多五项；不适合活动排程的决策，直接比较通用备选，不强行填时间、城市和行程。
你可以提出有依据的建议和取舍，但不能替成员确认条件、放宽必要条件、选定正式方案或投票。summary 清楚回答目前形成了什么、为什么、仍不确定什么；next_step 说明谁做什么，questions 只放当前最有价值的资料缺口。只输出 Decision Agent JSON Schema 对应的 JSON。"""


def public_context(room, user_id):
    visible = domain.view(room, user_id)
    visible['supplements'] = visible_supplements(room)
    visible['calendar'] = calendar_context()
    visible['members'] = [m for m in visible['members'] if m['status'] == 'approved']
    previous = room.get('agent') or {}
    visible['agent_memory'] = {key: previous[key] for key in ('goal', 'summary', 'next_step', 'questions') if previous.get(key)}
    if not previous.get('applied') and not previous.get('error'):
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
    prepared = None
    for turn_index in range(3):
        raw = await asyncio.wait_for(ai.request(provider, system, messages), timeout=provider['timeout']+5)
        try:
            turn = DecisionAgentTurn(**ai.parse_json(raw)).model_dump()
        except (ValueError, TypeError):
            raise ai.AIError('Agent 返回结构不完整，本次未改变正式决策，请重试') from None
        if turn['tool'] == 'analyze' and prepared is None and room['resources'] and all(m['confirmed'] for m in engine.active_members(room)) and room['state'] not in domain.TERMINAL | {'VOTING'}:
            prepared = engine.generate(room)
            evaluated = deepcopy(room)
            domain.analyze(evaluated, deepcopy(prepared))
            messages.extend([{'role':'assistant','content':store.dumps(turn)}, {'role':'user','content':'analyze 工具实际结果：\n'+store.dumps(planning_context(evaluated,user_id))+'\n请结合结果完成比较与下一步，tool=respond。'}])
            continue
        if turn['tool'] == 'analyze' and turn_index < 2:
            messages.extend([{'role':'assistant','content':store.dumps(turn)}, {'role':'user','content':'工具当前不可重复运行，或需要先有候选与全体确认。请说明具体下一步，tool=respond。'}])
            continue
        turn['tool'] = 'respond'
        known = {r['id'] for r in room['resources']}
        for resource in turn['resources']:
            resource['id'] = resource['id'] or store.new_id()
            if resource['id'] in known:
                raise ai.AIError('Agent 新增候选与现有标识重复，请重试；未覆盖原候选')
            known.add(resource['id'])
            resource['confirmed'] = resource['verified'] = False
        for resource in turn["resource_updates"]:
            if resource["id"] not in {item["id"] for item in room["resources"]}:
                raise ai.AIError("Agent 修正了不存在的候选，请重试；未覆盖现有数据")
            resource["confirmed"] = resource["verified"] = False
        if any(step['resource_id'] not in known for plan in turn['plans'] for step in plan['steps']):
            raise ai.AIError('Agent 行程引用了未知候选，请重试；未修改现有方案')
        return turn['summary'], {'agent':turn, '_prepared_analysis':prepared, 'mode':'ai'}
    raise ai.AIError('Agent 本轮已达到执行步数限制，请补充信息后继续')
