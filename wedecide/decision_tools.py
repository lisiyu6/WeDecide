"""Read-only algorithm context, diagnostics and counterfactual tools.

Private interview evidence stays in its member context. Public progress and
stored tool receipts contain aggregate results only. Formal writes stay in domain.
"""
from copy import deepcopy
from . import engine
from .models import Preference


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
    return {"candidates":[{"id":p["id"],"title":p["title"],**{key:p["evaluation"].get(key) for key in ("status","cost_upper","score","average","minimum","coverage","partial")}} for p in current],"tradeoff_perspectives":perspectives,"non_dominated_on_known_axes":frontier,"known_axes":axes,"meaning":"只用于已知数据的取舍比较，不代表全局最优；未知维度不补分，实际投票仍由成员决定。"}


def interview_algorithm_context(room,member,preference):
    """Describe the actual engine inputs; choose no questions or answers here."""
    current=preference or member.get("preference") or Preference().model_dump()
    fields={
        "budget_max":"本人费用上限，按人均费用上界检查必要条件",
        "budget_target":"理想人均费用，参与费用满意度比较",
        "cost_preference":"更低费用倾向，无具体金额也可参与相对费用比较",
        "budget_weight":"费用偏好在本人满意度中的权重1至5",
        "available_start":"活动可参加时间下界，检查必要时间窗口",
        "available_end":"活动可参加时间上界，检查必要时间窗口",
        "max_duration":"活动最长总时长，含等待与转场",
        "preferred_start":"希望活动开始的时间，参与软偏好比较",
        "preferred_end":"希望活动结束的时间，参与软偏好比较",
        "time_weight":"活动时间偏好在本人满意度中的权重1至5",
        "categories":"对实际候选类别的偏好0/50/100，活动按时长加权",
        "activity_weight":"类别偏好在本人满意度中的权重1至5",
        "excluded_categories":"本人明确禁止的候选类别，检查必要条件",
        "allowed_locations":"本人明确允许的候选地点，按名称检查必要条件",
        "criteria":"本人具体要求，与同名候选布尔属性核对；hard/soft、态度及权重决定可行性或满意度",
    }
    resources=room["resources"];members=[m for m in room["members"] if m["status"]=="approved"]
    if resources and all(r.get("kind","activity")=="decision" for r in resources):
        for key in ("available_start","available_end","max_duration","preferred_start","preferred_end","time_weight"):fields.pop(key)
    names=list(dict.fromkeys([c["name"] for c in current.get("criteria",[])]+[key for r in resources for key in r.get("attributes",{})]))[:30]
    axes=[{"name":name,"evidence":[{"resource_id":r["id"],"value":r.get("attributes",{}).get(name),"confirmed":r["confirmed"]} for r in resources]} for name in names]
    gaps=[]
    for resource in resources:
        missing=[]
        if not resource["confirmed"]:missing.append("候选事实尚未核对")
        if resource["cost"] is None:missing.append("费用未知")
        missing.extend(c["name"] for c in current.get("criteria",[]) if c.get("hard") and c["name"] not in resource.get("attributes",{}))
        if missing:gaps.append({"resource_id":resource["id"],"needs_organizer_check":missing})
    effects=[]
    for proposal in room["proposals"]:
        if proposal["input_version"]!=room["input_version"]:continue
        evaluation=proposal["evaluation"];own=next((u for u in evaluation["utilities"] if u["member_id"]==member["id"]),{})
        effects.append({"proposal_id":proposal["id"],"status":evaluation["status"],"my_dimensions":own.get("dimensions",[]),"my_violations":[v for v in evaluation["violations"] if v.get("member_id")==member["id"]]})
    defaults=Preference().model_dump()
    contract={"objective":"先满足每位成员已确认的必要条件，再按(1-fairness)*平均预测满意度+fairness*最低预测满意度比较；正式共识只由投票决定。","fairness":room["rules"]["fairness"],"member_count":len(members),"supported_fields":fields,"known_fields":[key for key in fields if current.get(key,defaults[key])!=defaults[key]],"member_unresolved":current.get("unresolved",[]),"candidate_axes":axes,"candidate_categories":list(dict.fromkeys(r["category"] for r in resources)),"candidate_fact_gaps":gaps,"actual_effects":effects,"boundary":"只根据本人明确表达整理草稿。未表达的可选项无需补齐，不能由别人的偏好推断此人，也不能猜测价格或候选事实。"}
    gaps=[]
    if current.get("unresolved"):
        gaps.append({"scope":"member","fields":[],"reason":"本人已表达的必要条件尚待澄清，结合原话选择对应算法字段","priority":"clarify_constraint"})
    for effect in effects:
        if effect['my_violations']:
            gaps.append({"scope":"member","fields":list(dict.fromkeys(v['field'] for v in effect['my_violations'] if v['field'] in fields)),"reason":"当前实际校核存在与本人条件的冲突；先理解底线，不默认放宽","priority":"confirmed_conflict"})
    for axis in axes:
        known_values={item['value'] for item in axis['evidence'] if item['value'] is not None and item['confirmed']}
        if len(known_values)>1 and not any(c['name'].casefold()==axis['name'].casefold() for c in current.get('criteria',[])):
            gaps.append({"scope":"member","fields":["criteria"],"axis":axis['name'],"reason":"已核对候选在此属性上有真实差异，本人态度可影响取舍","priority":"candidate_difference"})
    costs=[r['cost']+r['fixed_cost']/max(1,len(members)) for r in resources if r['confirmed'] and r['cost'] is not None]
    if len(set(costs))>1 and current.get("cost_preference","neutral")=="neutral" and current.get("budget_target") is None:
        gaps.append({"scope":"member","fields":["cost_preference"],"reason":"已核对候选费用存在差异，可判断本人是否在意费用；具体金额由本人提供","evidence":{"lowest":min(costs),"highest":max(costs)},"priority":"candidate_difference"})
    if contract['candidate_fact_gaps']:
        gaps.append({"scope":"organizer","fields":[],"reason":"候选缺少已核对事实，应由房主补资料，不能让成员猜测","priority":"verify_facts"})
    contract['decision_gaps']=gaps[:12]
    contract['decision_progress']=decision_progress(room)
    return contract



def analysis_is_current(room):
    analysis=room.get('analysis')
    return bool(analysis and (analysis.get('input_version')==room['input_version'] or (room['proposals'] and all(p['input_version']==room['input_version'] for p in room['proposals']))))


def algorithm_status(room):
    members=engine.active_members(room)
    current=analysis_is_current(room)
    ready=bool(members and all(m['confirmed'] for m in members) and room['resources'] and room['state'] in {'COLLECTING','COMPARING','NEGOTIATING'})
    return {'can_analyze':ready,'current_analysis':current,'needs_analysis':ready and not current,'input_version':room['input_version'],'analysis_version':room['analysis_version'],'tools':{'analyze':'校核全体已确认条件，复用当前版本计算','simulate':'只读比较其他公平性权重或当前资源的替代行程，不修改正式数据'},'calculation':{'individual':'有效维度的加权平均；预算按超额线性衰减、时间每小时偏离减20、类别按时长加权','group':'(1-fairness)*平均预测满意度+fairness*最低预测满意度','fairness':room['rules']['fairness'],'hard_constraints':'先校核每个人确认的必要条件，违反不能由高分抵消','missing':'必要事实未知保留UNKNOWN；无有效偏好为N/A，部分评分显示覆盖率'}}


def _counts(proposals):
    return {status:sum(p['evaluation']['status']==status for p in proposals) for status in ('FEASIBLE','UNKNOWN','INFEASIBLE')}


def _identity(proposal):
    return proposal.get('plan_id') or '|'.join(sorted(item['resource']['id'] for item in proposal['itinerary']))


def decision_progress(room):
    """Describe current authoritative progress without exposing anyone's inputs."""
    members=engine.active_members(room);confirmed=sum(m['confirmed'] for m in members)
    current=[p for p in room['proposals'] if p['input_version']==room['input_version']]
    counts=_counts(current);partial=sum(bool(p['evaluation'].get('partial')) for p in current if p['evaluation']['status']=='FEASIBLE')
    version=room['analysis_version'];previous=room.get('history',[])[-1] if room.get('history') else None
    change=None
    if analysis_is_current(room) and previous:
        old=previous['proposals'];old_counts=_counts(old)
        old_feasible={_identity(p) for p in old if p['evaluation']['status']=='FEASIBLE'}
        old_by_id={_identity(p):p for p in old};changed=[]
        for proposal in current:
            prior=old_by_id.get(_identity(proposal))
            if not prior:continue
            fields={key:{'before':prior['evaluation'].get(key),'after':proposal['evaluation'].get(key)} for key in ('status','cost_upper','score','minimum','start','end') if prior['evaluation'].get(key)!=proposal['evaluation'].get(key)}
            if fields:changed.append({'title':proposal['title'],'fields':fields})
        now_feasible={_identity(p) for p in current if p['evaluation']['status']=='FEASIBLE'}
        now_failed={_identity(p) for p in current if p['evaluation']['status']=='INFEASIBLE'}
        change={'previous_version':previous['version'],'current_version':version,'previous_feasible':old_counts['FEASIBLE'],'current_feasible':counts['FEASIBLE'],'became_feasible':len(now_feasible-old_feasible),'lost_feasible':len(old_feasible & now_failed),'changed_options':changed[:6],'changed_option_count':len(changed)}
    stage='collecting';summary=f'{confirmed} / {len(members)} 位成员已确认需求。';next_step='尚未确认的成员先核对自己的需求；其他人可以继续提议。';owner='members'
    if room['state']=='VOTING':
        stage='voting';summary='本轮正在对锁定的方案与成员名单正式表态。';next_step='成员提交本轮表态，等待投票结束。';owner='members'
    elif room['state'] not in {'COLLECTING','COMPARING','NEGOTIATING'}:
        stage='finished';summary='本次方案已正式通过。' if room['state']=='APPROVED' else '本次决策已结束，结果与原因已保存。';next_step='查看结果与对应方案记录。';owner='members'
    elif confirmed==len(members) and members:
        if not room['resources']:
            stage='needs_options';summary='全体需求已确认，还需要可比较的候选。';next_step='成员从左侧提出方向，由房主核对并采纳。';owner='host'
        elif not analysis_is_current(room):
            stage='ready_to_compute';summary='本轮输入已就绪，需要按最新版本校核全体条件。';next_step='根据最新资料整理并校核共同方案。';owner='system'
        elif counts['FEASIBLE']:
            stage='comparing';summary=f'第 {version} 版校核找到 {counts["FEASIBLE"]} 个满足已确认必要条件的方案。'
            if partial:summary+=f'其中 {partial} 个方案的偏好评分仍不完整。'
            selected=any(p['id']==room.get('selected_id') and p['evaluation']['status']=='FEASIBLE' for p in current)
            next_step='房主核对选定方案，锁定名单后发起正式投票。' if selected else '比较费用与群体取舍，由房主选择待投票方案。';owner='host'
        elif counts['UNKNOWN']:
            stage='needs_facts';summary=f'第 {version} 版有 {counts["UNKNOWN"]} 个方案缺少判断所需的事实，暂不能作为正式可行方案。';next_step='房主补齐并核对候选资料，再按全体条件重新校核。';owner='host'
        else:
            stage='conflict';summary=f'第 {version} 版在当前搜索范围内没有满足全体必要条件的方案。';next_step='优先调整方案或寻找替代方向，重新校核；个人条件由本人决定。';owner='host'
    change_text=''
    if change:
        change_text=f'与第 {change["previous_version"]} 版相比，可行方案由 {change["previous_feasible"]} 个变为 {change["current_feasible"]} 个。'
        if change['changed_option_count']:change_text+=f'其中 {change["changed_option_count"]} 个候选的费用、时间或群体评价发生变化，展开可核对。'
        if change['became_feasible'] or change['lost_feasible']:
            change_text+=f'按同一候选资源组合核对，新增可行 {change["became_feasible"]} 个，本版明确冲突 {change["lost_feasible"]} 个。'
    return {'stage':stage,'summary':summary,'next_step':next_step,'owner':owner,'counts':counts,'partial_count':partial,'confirmed':confirmed,'members':len(members),'input_version':room['input_version'],'analysis_version':version,'current':analysis_is_current(room),'change':change,'change_text':change_text,'scope':(room.get('analysis') or {}).get('scope','') if analysis_is_current(room) else ''}


def simulate(room, arguments):
    """Run the existing engine on an isolated copy; return aggregate evidence."""
    if not algorithm_status(room)['can_analyze']:
        raise ValueError('模拟需要全体有效成员确认需求、已有候选，且不在投票或结束期间')
    simulated=deepcopy(room)
    if arguments.fairness is not None:simulated['rules']['fairness']=arguments.fairness
    known={r['id'] for r in room['resources'] if r.get('kind','activity')=='activity'}
    submitted=[]
    for index,plan in enumerate(arguments.plans):
        if any(step.resource_id not in known for step in plan.steps):
            raise ValueError('模拟行程只能引用当前房间已有的活动资源')
        value=plan.model_dump();value['id']='simulation-'+str(index+1);submitted.append(value)
    if submitted:simulated['manual_plans']=submitted
    result=engine.generate(simulated)
    digest=comparison_digest(result['proposals'],room['input_version'])
    feasible=sum(p['evaluation']['status']=='FEASIBLE' for p in result['proposals'])
    return {'tool':'simulate','hypothetical':True,'input_version':room['input_version'],'fairness':simulated['rules']['fairness'],'summary':f'只读模拟在当前搜索范围内得到 {feasible} 个通过必要条件检查的候选。正式规则、需求和投票方案均未改变。','candidates':digest['candidates'],'tradeoff_perspectives':digest['tradeoff_perspectives'],'scope':result['scope'],'plans':submitted,'warnings':result['warnings']}
