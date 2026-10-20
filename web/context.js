import {esc,icon,field,textarea,select,dateTime,terminal,api} from './common.js';
const editable=r=>!terminal.has(r.state)&&r.state!=='VOTING';
export function dateField(label,value,expression=''){
 return `<div class="date-assistant">${field(label,'date',value||'','date')}<div class="date-expression">${field('用自然语言说日期','date_expression',expression,'text','maxlength="500" placeholder="例如：这周六、三天后"')}<button type="button" class="button secondary small" data-action="resolve-date">AI 换算</button></div></div>`;
}
export async function resolveDate(form,room=null,isCurrent=()=>true){
 const expression=form.elements.date_expression.value.trim();let result=form.querySelector('[data-date-result]');
 if(!expression)throw new Error('先说一下日期，例如“这周六”');
 const token=expression,endpoint=room?`/api/rooms/${encodeURIComponent(room.id)}/date`:'/api/date/resolve';
 result.textContent='正在换算日期…';
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
function suggestionsContent(state){
 const r=state.room,draft=state.suggestionDraft||{},cards=(r.supplements||[]).filter(item=>item.kind==='suggestion').slice(-30).reverse(),used=new Set(r.agent?.synthesis?.source_ids||[]);
 return `${terminal.has(r.state)?'':`<form id="suggestion-form" class="stack">${field('提议名称','title',draft.title||'','text','maxlength="80" placeholder="可选"')}${textarea('你的提议','text',draft.text||'','rows="5" maxlength="2000" required placeholder="说说可以考虑的选择"')}<button type="submit" class="button">提交提议</button></form>`}<div class="context-card-list">${cards.map(item=>`<article class="context-card"><div class="between"><strong>${esc(item.title||'提议')}</strong><span class="badge">${used.has(item.id)?'已引用':'待整理'}</span></div><p class="context-prose">${esc(item.text)}</p><div class="context-meta">${esc(r.members.find(m=>m.id===item.member_id)?.name||'伙伴')} · ${dateTime(item.at)}</div></article>`).join('')}</div>`;
}
export function contextDrawer(state){
 const r=state.room;if(!r||r.me.status!=='approved')return '';
 const host=r.me.id===r.host_id,open=state.contextOpen,left=state.contextSide==='left',knowledge=state.contextTab==='knowledge',draft=state.contextDraft||{},ended=terminal.has(r.state);
 const cards=(r.supplements||[]).filter(item=>item.kind!=='suggestion').slice(-30).reverse();
 const content=left?suggestionsContent(state):knowledge?host?`<form id="knowledge-form" class="stack"><input type="hidden" name="knowledge_version" value="${state.knowledgeDraft?.knowledge_version??r.knowledge_version??0}">${textarea('前置知识','text',state.knowledgeDraft?.text??r.knowledge??'','rows="12" maxlength="12000" placeholder="已有资料、背景、参考链接" '+(editable(r)?'':'disabled'))}<div class="actions"><button type="submit" class="button" ${editable(r)?'':'disabled'}>保存</button>${state.knowledgeDraft?'<button type="button" class="button ghost" data-action="knowledge-discard">撤销修改</button>':''}</div></form>`:`<p class="context-prose">${esc(r.knowledge||'暂无前置知识')}</p>`:`${ended?'':`<form id="supplement-form" class="stack">${field('标题','title',draft.title||'','text','maxlength="80" placeholder="可选"')}${textarea('补充信息','text',draft.text||'','rows="5" required maxlength="2000"')}${select('可见范围','visibility',draft.visibility||'private',[['private','仅自己'],['shared','全体成员']])}<button type="submit" class="button">保存</button></form>`}<div class="context-card-list">${cards.map(item=>`<article class="context-card"><div class="between"><strong>${esc(item.title||'补充信息')}</strong><span class="badge">${item.visibility==='private'?'仅自己':'全体'}</span></div><p class="context-prose">${esc(item.text)}</p><div class="context-meta">${esc(r.members.find(m=>m.id===item.member_id)?.name||'伙伴')} · ${dateTime(item.at)}</div>${item.member_id===r.me.id&&item.visibility==='private'&&editable(r)?'<button type="button" class="text-button" data-action="context-to-preferences">查看我的需求</button>':''}</article>`).join('')}</div>`;
 const launchers=ended&&state.tab==='result'?'':`<button type="button" class="suggestion-launcher button secondary" data-action="suggestions-open" aria-label="划入提议卡片" aria-expanded="${Boolean(open&&left)}">${icon('spark',18)} 提议</button><button type="button" class="context-launcher button secondary" data-action="context-open" aria-label="划入补充信息" aria-expanded="${Boolean(open&&!left)}">${icon('plus',18)} 补充</button>`;
 return `${launchers}${open?`<dialog id="context-drawer" class="context-drawer ${left?'context-drawer-left':''}" aria-labelledby="context-title"><header class="context-drawer-heading" data-context-handle><h2 id="context-title">${left?'提议':'补充信息'}</h2><button type="button" class="icon-button" data-action="context-close" aria-label="收起侧边卡片">${icon('close')}</button></header>${left?'':`<nav class="context-tabs" aria-label="补充资料类型"><button type="button" class="button ${knowledge?'ghost':'secondary'}" data-action="context-tab" data-tab="supplements">成员补充</button><button type="button" class="button ${knowledge?'secondary':'ghost'}" data-action="context-tab" data-tab="knowledge">知识空间</button></nav>`}<div class="context-drawer-body">${content}</div></dialog>`:''}`;
}
export function mountContextDrawer(root){
 const drawer=root.querySelector('#context-drawer');
 document.body.classList.toggle('context-open',Boolean(drawer));
 if(drawer&&!drawer.open)drawer.showModal();
}
