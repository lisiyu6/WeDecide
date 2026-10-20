import {esc,terminal} from './common.js';
const stages=[['overview','表达与提议'],['compare','比较与协商'],['vote','正式投票'],['result','决策结果']];
export function decisionFlow(state){
 const r=state.room,members=r.members.filter(m=>m.status==='approved'),ready=members.filter(m=>m.confirmed).length,isHost=r.me.id===r.host_id;
 const current=r.proposals.filter(p=>p.input_version===r.input_version),selected=current.find(p=>p.id===r.selected_id&&p.evaluation.status==='FEASIBLE');
 const ended=terminal.has(r.state),phase=ended?3:r.state==='VOTING'?2:['COMPARING','NEGOTIATING'].includes(r.state)?1:0;
 const fallbackStage=!r.resources.length?'needs_options':ready<members.length?'collecting':!current.length?'ready_to_compute':current.some(p=>p.evaluation.status==='FEASIBLE')?'comparing':current.some(p=>p.evaluation.status==='UNKNOWN')?'needs_facts':'conflict';
 const progress=r.decision_progress||{stage:fallbackStage,next_step:'按当前资料继续核对共同方案。'};
 const a=r.agent,hasDraft=a&&!a.applied&&!a.stale&&!a.error&&a.input_version===r.input_version&&(a.context_version||0)===(r.context_version||0)&&((a.resources?.length||0)+(a.resource_updates?.length||0)+(a.plans?.length||0));
 let hint=progress.next_step,target='',action='',label='';
 if(ended){hint=r.state==='APPROVED'?'本次选择已正式通过，结果与投票记录已经保存。':'本次决定已结束，具体结论和原因保存在结果中。';target='result';label='查看决策结果';}
 else if(r.state==='VOTING'){hint=r.vote?.my_vote?'你已提交本轮投票，等待本轮结束。':'正在对锁定的同一份方案投票，提交后本轮不能修改。';target='vote';label='为本轮方案表态';}
 else if(!r.me.confirmed){hint=`需求已确认 ${ready} / ${members.length} 人。先用卡片表达，再核对整理结果；左侧也可同时提议。`;target='preferences';label='表达并确认我的需求';}
 else if(hasDraft){hint=isHost?'已根据共同资料整理出备选草稿，请先核对采纳。':'已有共同备选草稿，等待房主核对采纳。';action='suggestions-open';label='查看左侧提议';}
 else if(progress.stage==='collecting'){hint=`需求已确认 ${ready} / ${members.length} 人。你的需求已保存，等待其他成员确认；可以继续提议。`;action='suggestions-open';label='查看大家的提议';}
 else if(progress.stage==='needs_options'){action='suggestions-open';label='提出备选想法';}
 else if(progress.stage==='ready_to_compute'){if(isHost){action=r.ai_available===false||a?.enabled===false?'analyze':'run-agent';label=r.agent_pending?'正在整理与校核':'整理并校核共同方案';}}
 else if(progress.stage==='needs_facts'){if(isHost){target='settings';label='补齐候选资料';}else{action='context-open';label='补充已知信息';}}
 else if(progress.stage==='conflict'){target='negotiate';label='一起讨论调整';}
 else if(selected){hint=isHost?'已选定当前有效方案，下一步锁定本轮名单并发起正式投票。':'房主已选定当前方案，等待发起正式投票。';if(r.vote?.status==='NOT_APPROVED')hint='上一轮未达到接受门槛，先核对协商后的方案；新一轮重新锁定名单，旧票不继承。';if(isHost){action='start_vote';label=r.vote?.status==='NOT_APPROVED'?'发起下一轮投票':'发起正式投票';}else{target='compare';label='查看选定方案';}}
 else{target='compare';label='查看方案取舍';}
 const next=action?`<button type="button" class="button secondary small" data-action="${action}" ${r.agent_pending&&['run-agent','analyze'].includes(action)?'disabled':''}>${label}</button>`:target&&target!==state.tab?`<a class="button secondary small" data-nav href="/r/${esc(r.code)}?view=${target}">${label}</a>`:'';
 return `<section class="decision-flow" aria-label="决策进度与下一步"><nav class="decision-flow-steps" aria-label="决策过程">${stages.map(([view,text],i)=>`<a data-nav href="/r/${esc(r.code)}?view=${view==='overview'&&!r.me.confirmed&&!ended&&r.state!=='VOTING'?'preferences':view}" ${i===phase?'aria-current="step"':''}><span>${i+1}</span>${text}</a>`).join('')}</nav><div class="decision-flow-next"><p>${esc(hint)}</p>${next}</div></section>`;
}

export function defaultDecisionView(room){
 if(terminal.has(room.state))return 'result';
 if(room.state==='VOTING')return 'vote';
 if(!room.me.confirmed)return 'preferences';
 if(['COMPARING','NEGOTIATING'].includes(room.state))return 'compare';
 return 'overview';
}
