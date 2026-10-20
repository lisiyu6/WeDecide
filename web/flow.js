import {esc,icon,terminal} from './common.js';

export function freshAgent(room){
 const a=room.agent;
 return a&&!a.error&&!a.stale&&a.input_version===room.input_version&&(a.context_version||0)===(room.context_version||0)&&(a.round??room.round)===room.round?a:null;
}

export function decisionTask(state){
 const r=state.room,host=r.me.id===r.host_id,members=r.members.filter(m=>m.status==='approved');
 const ready=members.filter(m=>m.confirmed).length,a=freshAgent(r);
 const proposals=r.proposals.filter(p=>p.input_version===r.input_version);
 const selected=proposals.find(p=>p.id===r.selected_id&&p.evaluation.status==='FEASIBLE');
 const drafts=a&&!a.applied&&((a.resources?.length||0)+(a.resource_updates?.length||0)+(a.plans?.length||0));
 const task=(title,description,label='',target='',action='',extra={})=>({title,description,label,target,action,...extra});
 if(terminal.has(r.state))return task(r.state==='APPROVED'?'这次决定已经通过':'本次讨论已结束','查看正式结论、最终方案和每一轮记录。','查看决策结果','result');
 if(r.state==='VOTING')return r.vote?.my_vote?task('你的表态已收到','等待其他成员提交或本轮截止。离线不会减少通过所需的人数。','查看本轮进度','vote'):task('现在，请为共同方案表态','大家对同一版本作出选择。预测分不会代替任何人的投票。','提交我的正式投票','vote');
 if(!r.me.confirmed)return task('先表达并确认你的想法','卡片回答会整理为需求结果，由你核对后计入群体计算。','开始我的需求卡片','preferences');
 if(r.ai_available===false&&host&&!proposals.length&&!r.resources.length)return task('先连接本房间使用的 AI','你的需求与已提交资料已保存。配置接口后会继续整理。','设置房间接口','settings');
 if(drafts)return host?task('核对整理出的共同备选','已把已有想法整理为候选。核对事实并保存，之后自动按全体需求计算。','核对共同备选','','review-agent-draft',{drafts}):task('共同备选已整理，等待房主核对','你可以先查看形成的方向，或继续补充已知资料。','查看左侧提议','','suggestions-open',{drafts});
 const unconfirmed=r.resources.find(resource=>!resource.confirmed);
 if(unconfirmed)return host?task(`先核对「${unconfirmed.name}」的事实`,'确认候选资料后才能用于判断；不确定的数值可以留空。','核对这项候选','','edit-resource',{id:unconfirmed.id}):task('等待房主核对候选资料','已确认的个人需求会保留。你可以补充可靠资料，帮助判断。','补充已知信息','','context-open');
 if(ready<members.length)return task('你的需求已进入共同整理',`还有 ${members.length-ready} 位伙伴正在表达。大家可以同时操作，不必等人回答完再提议。`,'提出一个备选想法','','suggestions-open');
 if(!r.resources.length)return r.agent_pending?task('正在把想法整理成备选','整理完成后，候选会直接出现在这里。可以先查看或补充提议。','查看大家的提议','','suggestions-open'):task('还需要可以比较的备选','从左侧提出一个方向或已有选项，共同资料会交给 AI 整理。','提出备选想法','','suggestions-open');
 const progress=r.decision_progress;
 if(progress?.stage==='needs_facts'){
  const unknown=proposals.find(p=>p.evaluation.status==='UNKNOWN');
  const resource=unknown?.itinerary?.find(item=>r.resources.some(x=>x.id===item.resource.id))?.resource;
  return host?task('先补齐影响判断的事实','候选仍有未知信息，不能把未知当作满足。展开方案可查看具体缺项。',resource?'核对候选资料':'查看待核实项',resource?'':'compare',resource?'edit-resource':'',{id:resource?.id}):task('共同方案还有资料待核实','可以补充已知信息；不需要重复回答自己的卡片。','补充已知信息','','context-open');
 }
 if(progress?.stage==='conflict')return task('先调整方案，保留每个人的底线','当前候选还不能满足全体必要条件。查看冲突，优先寻找替代安排。','查看冲突与取舍','compare');
 if(selected)return host?task('已选定方案，交给大家正式决定','发起投票后锁定方案和名单，所有成员对同一版本表态。','发起正式投票','','start_vote'):task('房主已选定待投票方案','你可以先核对具体安排，等待正式投票开始。','核对选定方案','compare');
 if(proposals.length)return task('比较可行方案，再选一个交给大家','先看具体方案与主要取舍；房主选定后仍需正式投票。','比较方案并选择','compare');
 if(r.agent_pending)return task('正在校核共同方案','会检查每个人确认的必要条件，再计算群体取舍。结果就绪后会自动更新。');
 return host?task('资料已就绪，继续共同校核','使用当前确认数据检查候选，形成可展开的比较结果。','校核共同方案','',r.ai_available===false?'analyze':'run-agent'):task('已准备好共同校核','等待本轮整理完成，当前需求已保存。');
}

export function taskAction(task,room,cls='button'){
 if(!task.label)return '';
 if(task.action)return `<button type="button" class="${cls}" data-action="${esc(task.action)}" ${task.id?`data-id="${esc(task.id)}"`:''}>${esc(task.label)} ${icon('arrow',17)}</button>`;
 return `<a class="${cls}" data-nav href="/r/${esc(room.code)}?view=${task.target}">${esc(task.label)} ${icon('arrow',17)}</a>`;
}

export function taskPanel(state){
 const task=decisionTask(state);
 return `<section class="next-task" aria-label="现在做什么"><h2>${esc(task.title)}</h2>${taskAction(task,state.room)}</section>`;
}

export function decisionFlow(state){
 const r=state.room,done=terminal.has(r.state);
 const phase=done||r.state==='VOTING'?3:r.decision_progress?.current||['COMPARING','NEGOTIATING'].includes(r.state)?2:r.me.confirmed?1:0;
 const stages=[['preferences','表达想法'],['overview','整理备选'],['compare','比较取舍'],[done?'result':'vote',done?'决策结果':'正式投票']];
 return `<section class="decision-flow" aria-label="决策进度与下一步"><nav class="decision-flow-steps" aria-label="决策过程">${stages.map(([view,label],i)=>`<a data-nav href="/r/${esc(r.code)}?view=${view}" class="${view===state.tab?'is-viewing':''}" ${i===phase?'aria-current="step"':''}><span>${i<phase?icon('check',14):i+1}</span>${label}</a>`).join('')}</nav></section>`;
}

export function defaultDecisionView(room){
 if(terminal.has(room.state))return 'result';
 if(room.state==='VOTING')return 'vote';
 if(!room.me.confirmed)return 'preferences';
 return 'overview';
}
