import {esc,terminal} from './common.js';
const stages=[['overview','表达与提议'],['compare','比较与协商'],['vote','正式投票'],['result','决策结果']];
export function decisionFlow(state){
 const r=state.room,members=r.members.filter(m=>m.status==='approved'),ready=members.filter(m=>m.confirmed).length,host=r.me.id===r.host_id;
 const proposals=r.proposals.filter(p=>p.input_version===r.input_version),selected=proposals.find(p=>p.id===r.selected_id&&p.evaluation.status==='FEASIBLE');
 const ended=terminal.has(r.state),phase=ended?3:r.state==='VOTING'?2:['COMPARING','NEGOTIATING'].includes(r.state)?1:0;
 let hint='',target='',action='',label='';
 if(ended){hint=r.state==='APPROVED'?'本次选择已正式通过，结果与投票记录已经保存。':'本次决定已结束，具体结论和原因保存在结果中。';target='result';label='查看决策结果';}
 else if(r.state==='VOTING'){hint=r.vote?.my_vote?'你已提交本轮投票，等待本轮结束。':'正在对锁定的同一份方案投票，提交后本轮不能修改。';target='vote';label='为本轮方案表态';}
 else if(!r.me.confirmed){hint=`需求已确认 ${ready} / ${members.length} 人。先用卡片表达，再核对整理结果；左侧也可同时提议。`;target='preferences';label='表达并确认我的需求';}
 else if(r.agent&&!r.agent.applied&&!r.agent.stale&&!r.agent.error&&r.agent.input_version===r.input_version&&(r.agent.context_version||0)===(r.context_version||0)&&((r.agent.resources?.length||0)+(r.agent.resource_updates?.length||0)+(r.agent.plans?.length||0))){hint=host?'AI 已整理出备选草稿，先核对并采纳，再检查候选事实。':'AI 已整理出备选草稿，等待房主核对采纳。';action='suggestions-open';label='查看左侧提议';}
 else if(!r.resources.length){hint='你的需求已确认。还需要可比较的备选，可以从左侧提交想法或让 AI 整理。';action='suggestions-open';label='提出备选想法';}
 else if(r.resources.some(item=>!item.confirmed)){hint=host?'已有候选资料，需由你核对后再用于正式方案比较。':'已有候选资料，等待房主核对；你的需求已保留。';target=host?'settings':'compare';label=host?'核对候选资料':'查看已有候选';}
 else if(ready<members.length){hint=`需求已确认 ${ready} / ${members.length} 人。等待其他成员确认，仍可继续提议和补充。`;action='suggestions-open';label='查看大家的提议';}
 else if(!proposals.length){hint='需求和候选已准备好，会根据全体已确认需求进行校核，形成可比较方案。';if(host){action='run-agent';label='整理并校核共同方案';}}
 else if(selected){hint=r.vote?.status==='NOT_APPROVED'?'上一轮未达到接受门槛，可先共同协商调整。新一轮会重新锁定方案和名单，旧票不继承。':host?'已选定当前有效方案，下一步锁定本轮名单并发起正式投票。':'房主已选定当前方案，等待发起正式投票。';if(host){action='start_vote';label=r.vote?.status==='NOT_APPROVED'?'发起下一轮投票':'发起正式投票';}else{target='compare';label='查看选定方案';}}
 else if(proposals.some(p=>p.evaluation.status==='FEASIBLE')){hint='已有可行方案。比较具体安排和群体取舍，再由房主选定待投票方案。';target='compare';label='查看方案取舍';}
 else if(proposals.some(p=>p.evaluation.status==='UNKNOWN')){hint=host?'当前缺少判断所需的事实，先补齐候选资料，再核对全体条件。':'当前缺少判断所需的事实，可以补充你掌握的信息。';if(host){target='settings';label='补齐候选资料';}else{action='context-open';label='补充已知信息';}}
 else{hint='当前方案与已确认条件冲突，先尝试调整方案或替代方向，个人条件仍由本人决定。';target='negotiate';label='一起讨论调整';}
 const disabled=r.agent_pending;
 const next=action?`<button type="button" class="button secondary small" data-action="${action}" ${disabled&&action==='run-agent'?'disabled':''}>${label}</button>`:target&&target!==state.tab?`<a class="button secondary small" data-nav href="/r/${esc(r.code)}?view=${target}">${label}</a>`:'';
 return `<section class="decision-flow" aria-label="决策进度与下一步"><nav class="decision-flow-steps" aria-label="决策过程">${stages.map(([view,text],i)=>`<a data-nav href="/r/${esc(r.code)}?view=${view==='overview'&&!r.me.confirmed&&!ended&&r.state!=='VOTING'?'preferences':view}" ${i===phase?'aria-current="step"':''}><span>${i+1}</span>${text}</a>`).join('')}</nav><div class="decision-flow-next"><p>${esc(hint)}</p>${next}</div></section>`;
}

export function defaultDecisionView(room){
 if(terminal.has(room.state))return 'result';
 if(room.state==='VOTING')return 'vote';
 if(!room.me.confirmed)return 'preferences';
 if(['COMPARING','NEGOTIATING'].includes(room.state))return 'compare';
 return 'overview';
}
