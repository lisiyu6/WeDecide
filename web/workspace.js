import {esc,icon,badge,money,terminal,dateTime} from './common.js';
import {freshAgent,taskPanel} from './flow.js';

const phases={queued:'等待整理',integrating:'正在整合大家的想法',checking:'正在校核共同方案',simulating:'正在试算替代方案',explaining:'正在整理方案取舍'};
export function processingStatus(room){
 if(!room.agent_pending)return '';
 const a=room.agent||{};
 return `<div class="processing-state" role="status"><span class="spinner" aria-hidden="true"></span><strong>${phases[a.phase]||'正在整理'}</strong>${a.started?`<span data-elapsed="${a.started}"></span>`:''}</div>`;
}

function receipts(room,report){
 const intake=report?.intake;if(!intake)return '';
 const included=new Set(intake.source_ids),used=new Set(report.synthesis?.source_ids||[]);
 return `<details class="workspace-evidence" data-disclosure="integration-receipt"><summary>整理记录</summary><div class="receipt-counts"><span>${intake.confirmed_members} 人已确认</span><span>${intake.suggestions} 条提议</span><span>${intake.information} 条补充</span></div><ul class="integration-sources">${(room.supplements||[]).filter(item=>item.visibility==='shared').slice(-30).map(item=>`<li><span>${esc(item.title||item.text.slice(0,50))}</span><span>${used.has(item.id)?'已引用':included.has(item.id)?'已读取':'待整理'}</span></li>`).join('')}</ul><time>${dateTime(report.updated)}</time></details>`;
}

function directions(room,report){
 const previous=room.agent&&!room.agent.applied?room.agent:null;
 const source=report||previous,updating=!report&&Boolean(previous);
 const drafts=source&&!source.applied?[...(source.resources||[]),...(source.resource_updates||[])]:[];
 const items=drafts.length?drafts:room.resources;
 if(!items.length)return '';
 const host=room.me.id===room.host_id,editable=!terminal.has(room.state)&&room.state!=='VOTING';
 return `<section class="workspace-directions"><div class="section-heading"><h2>共同备选 <span>${items.length}</span></h2></div><div class="direction-grid">${items.map((item,i)=>`<article class="direction-card"><div class="between"><span class="direction-index">${String(i+1).padStart(2,'0')}</span>${badge(drafts.length||!item.confirmed?'UNKNOWN':'approved',drafts.length?(updating?'更新中':'待采用'):item.confirmed?'已核对':'待核对')}</div><h3>${esc(item.name)}</h3>${item.description?`<p>${esc(item.description)}</p>`:''}<div class="direction-bottom"><span>${money(item.cost)}${item.cost==null?'':' / 人'}</span>${host&&editable?`<button type="button" class="text-button" data-action="${drafts.length?'review-agent-draft':'edit-resource'}" ${drafts.length?'':`data-id="${esc(item.id)}"`} ${drafts.length&&updating?'disabled':''}>${drafts.length?(updating?'正在更新':'核对并采用'):'查看详情'} ${icon('arrow',15)}</button>`:''}</div></article>`).join('')}</div></section>`;
}

export function decisionWorkspace(state,{calculation,current}){
 const r=state.room,a=freshAgent(r),old=r.agent,members=r.members.filter(m=>m.status==='approved');
 const brief=a?.synthesis||{},pending=r.members.filter(m=>m.status==='pending');
 const summary=brief.recommendation||a?.summary||'';
 const lead=summary.length>180?summary.slice(0,180)+'…':summary;
 return `<div class="decision-workspace">
  <header class="workspace-heading"><h1>大家的选择</h1><div class="actions"><button type="button" class="people-button" data-action="focus-members">${icon('users',18)} ${members.length} 人${pending.length?` · ${pending.length} 待加入`:''}</button><button type="button" class="button secondary small" data-action="invite">邀请</button></div></header>
  ${processingStatus(r)}
  ${taskPanel(state)}
  ${r.selected_id||r.state==='VOTING'||r.state==='APPROVED'?current:''}
  ${directions(r,a)}
  ${summary?`<section class="synthesis-card"><h2>${icon('spark',20)} 本轮整理</h2><p class="synthesis-summary">${esc(lead)}</p>${brief.tradeoffs?.length?`<ul class="synthesis-tradeoffs">${brief.tradeoffs.slice(0,2).map(point=>`<li>${esc(point)}</li>`).join('')}</ul>`:''}${summary.length>180||brief.common_ground?.length?`<details class="workspace-evidence" data-disclosure="synthesis-full"><summary>展开整理</summary>${summary.length>180?`<p>${esc(summary)}</p>`:''}${brief.common_ground?.length?`<ul>${brief.common_ground.map(point=>`<li>${esc(point)}</li>`).join('')}</ul>`:''}</details>`:''}${receipts(r,a)}</section>`:''}
  ${a?.questions?.length?`<details class="workspace-evidence" data-disclosure="agent-questions"><summary>待补资料 ${a.questions.length}</summary><ul>${a.questions.map(question=>`<li>${esc(question)}</li>`).join('')}</ul><button type="button" class="text-button" data-action="context-open">补充 ${icon('plus',16)}</button></details>`:''}
  ${old?.error?`<div class="notice error"><p>${esc(old.error)}</p>${r.me.id===r.host_id?'<button type="button" class="button secondary small" data-action="run-agent">重试整理</button>':''}</div>`:''}
  ${a?.notice?`<div class="notice warm">${esc(a.notice)}</div>`:''}
  ${!a&&old?.summary?`<details class="workspace-evidence" data-disclosure="previous-agent-summary"><summary>上轮整理</summary><p class="context-prose">${esc(old.summary)}</p></details>`:''}
  ${calculation?`<details class="workspace-evidence" data-disclosure="workspace-calculation"><summary>计算结果</summary>${calculation}</details>`:''}
  <details class="workspace-evidence" data-disclosure="group-preparation"><summary>成员需求 ${members.filter(m=>m.confirmed).length} / ${members.length}</summary><ul class="group-preparation">${members.map(m=>`<li><span>${esc(m.name)}${m.id===r.me.id?' · 你':''}</span><span>${m.confirmed?'已确认':'表达中'}</span></li>`).join('')}</ul>${r.me.confirmed?`<a class="text-button" data-nav href="/r/${esc(r.code)}?view=preferences&stage=result">我的需求 ${icon('arrow',16)}</a>`:''}</details>
  ${old?.enabled===false&&r.me.id===r.host_id?'<button class="text-button" data-action="toggle-agent" data-enabled="true">恢复整理</button>':a&&!r.agent_pending&&r.me.id===r.host_id&&!terminal.has(r.state)&&r.state!=='VOTING'?'<button type="button" class="text-button workspace-refresh" data-action="run-agent">重新整理</button>':''}
 </div>`;
}
