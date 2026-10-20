import {esc,icon,field,textarea,select,dateTime,terminal,api} from './common.js';
import {mountContextMotion} from './context-motion.js';
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
 return `${terminal.has(r.state)?'':`<form id="suggestion-form" class="stack">${textarea('你的提议','text',draft.text||'','rows="5" maxlength="2000" required placeholder="说说可以考虑的选择"')}<details class="context-optional" data-disclosure="suggestion-title"><summary>添加标题</summary>${field('提议名称','title',draft.title||'','text','maxlength="80" placeholder="可选"')}</details><button type="submit" class="button">提交提议</button></form>`}${cards.length?`<details class="context-history" data-disclosure="suggestion-history"><summary>提议记录 · ${cards.length}</summary><div class="context-card-list">${cards.map(item=>`<article class="context-card"><div class="between"><strong>${esc(item.title||'提议')}</strong><span class="badge">${used.has(item.id)?'已引用':'待整理'}</span></div><p class="context-prose">${esc(item.text)}</p><div class="context-meta">${esc(r.members.find(m=>m.id===item.member_id)?.name||'伙伴')} · ${dateTime(item.at)}</div></article>`).join('')}</div></details>`:''}`;
}
export function contextDrawer(state){
 const r=state.room;if(!r||r.me.status!=='approved')return '';
 const host=r.me.id===r.host_id,open=state.contextOpen,left=state.contextSide==='left',knowledge=state.contextTab==='knowledge',draft=state.contextDraft||{},ended=terminal.has(r.state);
 const cards=(r.supplements||[]).filter(item=>item.kind!=='suggestion').slice(-30).reverse();
 const content=left?suggestionsContent(state):knowledge?host?`<form id="knowledge-form" class="stack"><input type="hidden" name="knowledge_version" value="${state.knowledgeDraft?.knowledge_version??r.knowledge_version??0}">${textarea('前置知识','text',state.knowledgeDraft?.text??r.knowledge??'','rows="12" maxlength="12000" placeholder="已有资料、背景、参考链接" '+(editable(r)?'':'disabled'))}<div class="actions"><button type="submit" class="button" ${editable(r)?'':'disabled'}>保存</button>${state.knowledgeDraft?'<button type="button" class="button ghost" data-action="knowledge-discard">撤销修改</button>':''}</div></form>`:`<p class="context-prose">${esc(r.knowledge||'暂无前置知识')}</p>`:`${ended?'':`<form id="supplement-form" class="stack">${textarea('补充信息','text',draft.text||'','rows="5" required maxlength="2000"')}${select('可见范围','visibility',draft.visibility||'private',[['private','仅自己'],['shared','全体成员']])}<details class="context-optional" data-disclosure="information-title"><summary>添加标题</summary>${field('标题','title',draft.title||'','text','maxlength="80" placeholder="可选"')}</details><button type="submit" class="button">保存补充</button></form>`}${cards.length?`<details class="context-history" data-disclosure="information-history"><summary>补充记录 · ${cards.length}</summary><div class="context-card-list">${cards.map(item=>`<article class="context-card"><div class="between"><strong>${esc(item.title||'补充信息')}</strong><span class="badge">${item.visibility==='private'?'仅自己':'全体'}</span></div><p class="context-prose">${esc(item.text)}</p><div class="context-meta">${esc(r.members.find(m=>m.id===item.member_id)?.name||'伙伴')} · ${dateTime(item.at)}</div>${item.member_id===r.me.id&&item.visibility==='private'&&editable(r)?'<button type="button" class="text-button" data-action="context-to-preferences">查看我的需求</button>':''}</article>`).join('')}</div></details>`:''}`;
 const launchers=ended&&state.tab==='result'?'':[['left','提议','suggestions-open','划入提议卡片'],['right','补充信息','context-open','划入补充信息']].map(([side,label,action,name])=>`<button type="button" class="context-edge context-edge-${side}" data-context-edge="${side}" data-action="${action}" aria-label="${name}" aria-expanded="${Boolean(open&&((side==='left')===left))}" title="${label}"><span class="context-edge-arrow" aria-hidden="true"></span><span class="context-edge-label" aria-hidden="true">${label}</span></button>`).join('');
 return `${launchers?'<div class="context-wings" aria-hidden="true"><span class="context-wing-paper context-wing-left"></span><span class="context-wing-paper context-wing-right"></span></div>':''}${launchers}${open?`<dialog id="context-drawer" class="context-deck" data-side="${left?'left':'right'}" aria-labelledby="context-title"><div class="context-fan-stack"><section class="context-sheet"><header class="context-sheet-header" data-context-handle><div class="context-sheet-title">${icon(left?'spark':'plus',22)}<h2 id="context-title">${left?'提议':'补充信息'}</h2></div><span class="context-sheet-grip" aria-hidden="true"></span><button type="button" class="icon-button" data-action="context-close" aria-label="收起侧边卡片">${icon('close')}</button></header>${left?'':`<nav class="context-tabs" aria-label="补充资料类型"><button type="button" class="button ${knowledge?'ghost':'secondary'}" data-action="context-tab" data-tab="supplements">成员补充</button><button type="button" class="button ${knowledge?'secondary':'ghost'}" data-action="context-tab" data-tab="knowledge">知识空间</button></nav>`}<div class="context-card-body"><div class="context-card-feedback" data-context-feedback role="status" aria-live="polite" hidden></div>${content}</div></section></div></dialog>`:''}`;
}
export function mountContextDrawer(root){
 const drawer=root.querySelector('#context-drawer');
 const restored=document.body.classList.contains('context-open');
 document.body.classList.toggle('context-open',Boolean(drawer));
 document.body.classList.toggle('has-context-wings',Boolean(root.querySelector('.context-edge')));
 document.body.dataset.contextSide=drawer?.dataset.side||'';
 if(drawer&&!drawer.open){mountContextMotion(drawer,{restored});drawer.showModal();}
}
