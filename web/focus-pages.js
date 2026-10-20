import {esc,icon,badge,labels,time,money,terminal,dateTime} from './common.js';
import {proposalDetail} from './decision.js';

const link=(r,view,text)=>`<a data-nav class="button secondary small" href="/r/${esc(r.code)}?view=${view}">${text}</a>`;

// The same saved proposal is used for the overview, the locked ballot and the record.
export function proposalSynopsis(p){
 if(!p)return '';
 const general=p.kind==='decision'||p.evaluation.kind==='decision';
 const descriptions=[...new Set([p.description,...(p.itinerary||[]).map(item=>item.resource.description)].filter(Boolean))];
 return `<div class="focus-synopsis">${descriptions.map(text=>`<p>${esc(text)}</p>`).join('')}${general?'':`<ol class="focus-itinerary">${p.itinerary.map(item=>`<li><span>${time(item.start)}–${time(item.end)}</span> ${esc(item.resource.name)}</li>`).join('')}</ol>`}<p class="hint">${p.evaluation.cost==null?'费用待核对':money(p.evaluation.cost)+' / 人'} · 方案 V${p.version}</p></div>`;
}

export function focusedNegotiation(state,parts){
 const r=state.room;
 return `<div class="focus-journey"><header class="focus-page-title"><h1>共同协商</h1></header>${parts.current}${parts.pending?`<section class="card focus-request"><h2>需要你确认的调整</h2>${parts.pending}</section>`:''}${parts.chat}<div class="focus-secondary">${parts.lookup}<details class="focus-fold" data-disclosure="feedback"><summary>提出反馈或公开摘要</summary>${parts.feedback}</details>${parts.shared?`<details class="focus-fold" data-disclosure="shared-notes"><summary>查看大家愿意公开的想法</summary>${parts.shared}</details>`:''}${parts.history?`<details class="focus-fold" data-disclosure="request-history"><summary>查看已处理的调整</summary>${parts.history}</details>`:''}</div></div>`;
}

export function focusedVote(state,response){
 const r=state.room,v=r.vote,open=v.status==='OPEN';
 return `<div class="focus-journey"><section class="card focus-ballot"><div class="between"><span class="eyebrow">第 ${v.round} 轮正式投票</span>${badge(v.status)}</div><h1>${esc(v.proposal.title)}</h1>${proposalSynopsis(v.proposal)}<div class="focus-vote-meta"><p>锁定 ${v.electorate.length} 人 · 需要 ${v.required} 人明确接受 · 已提交 ${v.submitted.length} 人</p>${open?`<p>剩余 <strong data-deadline="${v.deadline}">—</strong><span class="hint"> · ${dateTime(v.deadline)} 截止</span></p>`:`<p>接受 ${v.counts?.accept??0} · 希望修改 ${v.counts?.revise??0} · 不接受 ${v.counts?.reject??0}</p>`}</div><details class="focus-fold" data-disclosure="ballot-facts"><summary>核对本轮完整方案与依据</summary>${proposalDetail(r,v.proposal)}</details><div class="focus-vote-response">${response}${!open?`<div class="actions">${link(r,terminal.has(r.state)?'result':'overview',terminal.has(r.state)?'查看正式结果':'继续共同调整')}</div>`:''}</div></section><details class="focus-fold" data-disclosure="ballot-progress"><summary>投票进度与规则</summary><ul class="focus-member-progress">${v.electorate.map(m=>`<li>${esc(m.name)}<span>${v.submitted.includes(m.id)?'已提交':'尚未提交'}</span></li>`).join('')}</ul>${v.counts?`<p>未投票 ${v.counts.missing} 人。</p>`:''}${r.me.id===r.host_id&&open?'<button class="button ghost small" data-action="cancel_vote">取消整轮投票</button>':''}</details></div>`;
}

export function focusedResult(state,participation,history){
 const r=state.room,done=terminal.has(r.state),record=r.result;
 if(!done)return `<div class="focus-journey"><section class="card"><h1>决定还在形成中</h1><div class="actions">${link(r,r.state==='VOTING'?'vote':'overview',r.state==='VOTING'?'查看正在进行的投票':'回到当前决策')}</div></section><details class="focus-fold" data-disclosure="record-history"><summary>查看已有决策记录</summary>${history}</details></div>`;
 const approved=r.state==='APPROVED',proposal=record?.proposal;
 return `<div class="focus-journey"><section class="card focus-final"><div class="between"><span class="eyebrow">本次决定</span>${badge(r.state)}</div><h1>${esc(proposal?.title||labels[r.state])}</h1><p class="focus-outcome">${approved?`${record.counts.accept} 位伙伴明确接受，达到本轮 ${record.required} 人门槛。`:esc(record?.explanation||'本次未形成共同接受的方案。')}</p>${proposal?proposalSynopsis(proposal):''}${proposal?`<details class="focus-fold" data-disclosure="record-facts"><summary>展开最终方案与完整依据</summary>${proposalDetail(r,proposal)}</details>`:''}<div class="actions"><a class="button" href="/api/rooms/${esc(r.id)}/report">${icon('download',16)} 下载决策报告</a><button class="button secondary" data-action="print">打印 / 保存 PDF</button></div></section>${proposal?`<details class="focus-fold" data-disclosure="participation"><summary>${proposal.kind==='decision'?'记录后续执行意愿（可选）':'记录实际参与意愿（可选）'}</summary>${participation}</details>`:''}<details class="focus-fold" data-disclosure="record-history"><summary>查看投票记录与决策过程</summary>${history}</details><div>${link(r,'overview','查看共同进展')} <a data-nav class="button ghost small" href="/new">发起新的决定</a></div></div>`;
}
