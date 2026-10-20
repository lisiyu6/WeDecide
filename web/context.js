import {esc,icon,field,textarea,select,dateTime,terminal,api} from './common.js';
const editable=r=>!terminal.has(r.state)&&r.state!=='VOTING';
export function dateField(label,value,expression=''){
 return `<div class="date-assistant">${field(label,'date',value||'','date')}<div class="date-expression">${field('用自然语言说日期','date_expression',expression,'text','maxlength="500" placeholder="例如：这周六、三天后"')}<button type="button" class="button secondary small" data-action="resolve-date">AI 换算</button></div><p class="hint" data-date-result role="status">可直接说日期，由房间 Agent 帮你换算，也可选日历。</p></div>`;
}
export async function resolveDate(form,room=null,isCurrent=()=>true){
 const expression=form.elements.date_expression.value.trim();let result=form.querySelector('[data-date-result]');
 if(!expression)throw new Error('先说一下日期，例如“这周六”');
 const token=expression,endpoint=room?`/api/rooms/${encodeURIComponent(room.id)}/date`:'/api/date/resolve';
 result.textContent='Agent 正在换算日期…';
 try{
  const answer=await api(endpoint,{method:'POST',body:{text:expression}});
  if(!isCurrent())throw new Error('页面已切换，请在当前页面重新换算');
  form=document.getElementById(form.id)||form;result=form.querySelector('[data-date-result]');
  if(!form.isConnected||form.elements.date_expression.value.trim()!==token)throw new Error('日期输入已变化，请重新换算');
  if(answer.needs_clarification){result.textContent=answer.question;throw new Error(answer.question);}
  form.elements.date.value=answer.date;form.elements.date.dataset.expression=token;
  result.textContent=`${answer.date} · ${answer.explanation}（基准 ${answer.reference_date}，${answer.timezone}）`;
  return answer;
 }catch(error){result.textContent=error.message;throw error;}
}
export function contextDrawer(state){
 const r=state.room;if(!r||r.me.status!=='approved')return '';
 const host=r.me.id===r.host_id,open=state.contextOpen,knowledge=state.contextTab==='knowledge',draft=state.contextDraft||{},ended=terminal.has(r.state);
 const cards=(r.supplements||[]).slice(-30).reverse();
 return `<button type="button" class="context-launcher button secondary" data-action="context-open" aria-label="划入补充信息" aria-expanded="${Boolean(open)}">${icon('plus',17)} 补充信息</button>${open?`<dialog id="context-drawer" class="context-drawer" aria-labelledby="context-title"><header class="context-drawer-heading" data-context-handle><div><span class="eyebrow">同一个房间 Agent</span><h2 id="context-title">为这次决策补充信息</h2></div><button type="button" class="icon-button" data-action="context-close" aria-label="收起补充信息">${icon('close')}</button></header><nav class="context-tabs" aria-label="补充资料类型"><button type="button" class="button ${knowledge?'ghost':'secondary'}" data-action="context-tab" data-tab="supplements">成员补充</button><button type="button" class="button ${knowledge?'secondary':'ghost'}" data-action="context-tab" data-tab="knowledge">房主知识空间</button></nav><div class="context-drawer-body">${knowledge?`<p class="hint">可选填背景、已有资料、术语和来源链接。本房间的 Agent 统一参考，成员可查看；文字与链接不等于已核验事实，链接不会自动抓取。</p>${host?`<form id="knowledge-form" class="stack"><input type="hidden" name="knowledge_version" value="${state.knowledgeDraft?.knowledge_version??r.knowledge_version??0}">${textarea('给房间 Agent 的前置知识（可留空）','text',state.knowledgeDraft?.text??r.knowledge??'','rows="12" maxlength="12000" placeholder="例如已有方案、已知事实、目标背景，以及需要参考的资料…" '+(editable(r)?'':'disabled'))}<div class="actions"><button type="submit" class="button" ${editable(r)?'':'disabled'}>保存前置知识</button>${state.knowledgeDraft?'<button type="button" class="button ghost" data-action="knowledge-discard">恢复已保存的知识</button>':''}</div>${r.state==='VOTING'?'<p class="hint">正式投票期间保留当前知识版本；新信息可用成员补充卡片记录。</p>':''}</form>`:`<article class="context-card"><h3>本次决策的前置知识</h3><p class="context-prose">${esc(r.knowledge||'房主暂未填写，留空也可继续决策。')}</p></article>`}`:`<p class="hint">补充给同一个房间 Agent。原文可仅本人可见，或明确共享到共同决策。AI 负责整理计算数据，个人条件仍由本人核对确认。</p>${ended?'':`<form id="supplement-form" class="stack">${field('补充标题（可选）','title',draft.title||'','text','maxlength="80" placeholder="方便稍后找到"')}${textarea('想补充的信息','text',draft.text||'','rows="5" required maxlength="2000" placeholder="新发现、补充想法、背景资料或选择原因…"')}${select('原文可见范围','visibility',draft.visibility||'private',[['private','仅本人可见，交给房间 Agent 私密整理'],['shared','全体成员可见，加入共同决策']])}<button type="submit" class="button">提交给房间 Agent</button>${r.state==='VOTING'?'<p class="hint">可以记录新信息；本轮锁定的方案与投票不会因此更改。</p>':''}</form>`}<div class="context-card-list"><h3>已补充的信息</h3>${cards.length?cards.map(item=>`<article class="context-card"><div class="between"><strong>${esc(item.title||'补充信息')}</strong><span class="badge">${item.visibility==='private'?'仅本人可见':'共同参考'}</span></div><p class="context-prose">${esc(item.text)}</p><small class="hint">${esc(r.members.find(m=>m.id===item.member_id)?.name||'伙伴')} · ${dateTime(item.at)}${item.during_vote?' · 投票期间记录':''}</small>${item.member_id===r.me.id&&item.visibility==='private'&&editable(r)?`<button type="button" class="button ghost small" data-action="context-to-preferences">核对 Agent 整理的需求</button>`:''}</article>`).join(''):'<p class="hint">还没有补充。需要时随时从右侧划入。</p>'}</div>`}</div></dialog>`:''}`;
}
export function mountContextDrawer(root){
 const drawer=root.querySelector('#context-drawer');
 document.body.classList.toggle('context-open',Boolean(drawer));
 if(drawer&&!drawer.open)drawer.showModal();
}
