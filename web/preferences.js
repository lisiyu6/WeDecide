import {installSwipe} from './swipe.js';
import {latestInterview,currentInterviewInput} from './interview-input.js';
export {latestInterview} from './interview-input.js';
import {$,$$,setText,esc,icon,field,textarea,select,check,time,money,minutes,number,terminal} from './common.js';
const split=value=>String(value||'').split(/[,，\n]/).map(v=>v.trim()).filter(Boolean);
const lines=value=>String(value||'').split('\n').map(v=>v.trim()).filter(Boolean);
const importance=[['1','不太在意'],['2','略微在意'],['3','一般'],['4','比较在意'],['5','非常在意']];
const ratings=[['','尚未评价'],['100','喜欢 / 希望具备'],['50','都可以'],['0','不喜欢 / 希望不具备']];
const readTime=value=>/^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(value)?minutes(value):value==='24:00'?1440:null;
const parse=(value,fallback)=>{try{return JSON.parse(value||'');}catch{return fallback;}};
export function interviewDraft(state){return state.prefDraft?.preference||latestInterview(state)?.metadata.draft||state.room.me.preference||{};}
function flowCard(state,locked,pending,q){
 const confirmed=state.room.me.confirmed;
 const preserved=latestInterview(state)?.metadata.mode==='preserved';
 if(preserved)return `<div class="interview-deck"><article class="interview-question" data-interview-card><span class="interview-stamp" data-interview-stamp aria-hidden="true"></span><div class="interview-content"><span class="eyebrow">这次整理尚未完成</span><h2>你的回答已保留，可以继续整理</h2></div><div class="interview-choices"><button type="button" class="button secondary" data-action="interview-next" data-choice="left" ${locked||pending?'disabled':''}>← 重新整理已有回答</button><button type="button" class="button secondary" data-pref-table data-choice="right">查看保留的需求 →</button></div></article></div>`;
 return `<div class="interview-deck"><article class="interview-question" data-interview-card><span class="interview-stamp" data-interview-stamp aria-hidden="true"></span><div class="interview-content"><span class="eyebrow">${q?.ready?'本轮卡片已整理':confirmed?'继续回答':'这次共同决定，先听听你'}</span><h2>${q?.ready?'这轮想法已经整理好了':confirmed?'你的想法，还可以继续补充':'你希望这次选择怎样？'}</h2></div><div class="interview-choices"><button type="button" class="button secondary" data-action="interview-next" data-choice="left" ${locked||pending?'disabled':''}>← ${q||confirmed?'继续回答卡片':'开始卡片表达'}</button><button type="button" class="button" data-choice="right" ${q||confirmed?'data-pref-table':'data-action="interview-focus"'} ${locked||pending?'disabled':''}>${q||confirmed?'查看整理结果':'先说一点想法'} →</button></div></article></div>`;
}
function inputCard(input,locked){
 const {spec,turn,choice,value}=input,q=turn.metadata.interview;
 const ending=spec.allow_midnight_end??spec.field?.endsWith('end');
 const extra=`required ${locked?'disabled':''} data-interview-value`;
 let control;
 if(spec.kind==='number')control=field(spec.label+(spec.unit?' / '+spec.unit:''),'answer',value,'number',`${extra} min="${Number(spec.min??0)}" max="${Number(spec.max??1000000)}" step="${Number(spec.step??.01)}" inputmode="${spec.step===1?'numeric':'decimal'}" placeholder="${esc(spec.placeholder||'填写具体数值')}"`);
 else if(spec.kind==='time')control=field(spec.label,'answer',value,ending?'text':'time',`${extra} ${ending?'maxlength="5" pattern="([01][0-9]|2[0-3]):[0-5][0-9]|24:00"':'step="60"'} placeholder="${esc(spec.placeholder||'HH:MM')}"`);
 else control=textarea(spec.label,'answer',value,`${extra} rows="3" maxlength="1000" placeholder="${esc(spec.placeholder||'说说你的具体想法')}"`);
 return `<div class="interview-deck"><article class="interview-question interview-input-card" data-interview-input-card><div class="interview-input-heading"><p class="interview-input-selection">${esc(q[choice])}</p><h2>${esc(spec.label)}</h2><details class="interview-input-context"><summary>查看原问题</summary><p>${esc(q.question)}</p></details></div><form id="interview-value-form" class="stack" data-source-message="${turn.id}">${control}<div class="interview-input-actions"><button type="button" class="button secondary" data-action="interview-input-back" ${locked?'disabled':''}>返回重选</button><button type="submit" class="button" ${locked?'disabled':''}>提交并继续 ${icon('arrow',18)}</button></div></form></article></div>`;
}
function questionCard(state,locked){
 const metadata=latestInterview(state)?.metadata,q=metadata?.interview,progress=metadata?.interview_progress,pending=state.room.ai_pending;
 if(pending)return `<div class="interview-deck"><article class="interview-question interview-pending" aria-busy="true"><span class="spinner"></span><h2>正在整理你的回答</h2></article></div>`;
 if(!q||q.ready)return flowCard(state,locked,pending,q);
 const input=currentInterviewInput(state);if(input)return inputCard(input,locked);
 return `<div class="interview-deck"><article class="interview-question" data-interview-card><span class="interview-stamp" data-interview-stamp aria-hidden="true"></span><div class="interview-content"><span class="eyebrow">${progress?`${progress.asked} / ${progress.limit}`:"你的选择"}</span><h2>${esc(q.question)}</h2></div><div class="interview-choices"><button type="button" class="button secondary" data-action="interview-answer" data-choice="left" ${locked?'disabled':''}>← ${esc(q.left)}</button><button type="button" class="button" data-action="interview-answer" data-choice="right" ${locked?'disabled':''}>${esc(q.right)} →</button></div></article></div>`;
}
function interviewCard(state,locked){
 if(state.room.ai_available===false)return `<section class="card interface-required"><h2>${state.room.me.id===state.room.host_id?'连接房间 AI':'等待房主连接 AI'}</h2><div class="actions">${state.room.me.id===state.room.host_id?`<a data-nav class="button" href="/r/${esc(state.room.code)}?view=settings">设置接口 ${icon('arrow',17)}</a>`:''}<button type="button" class="button secondary" data-pref-table>直接填写需求</button></div></section>`;
 const turn=latestInterview(state),q=turn?.metadata.interview,pending=state.room.ai_pending;
 const error=[...state.messages].reverse().find(row=>row.role==='assistant'&&row.kind==='interview');
 return `<section class="${state.zen?'focus-interview':'card interview-panel'}">${state.zen?'':`<div class="card-title"><h2>表达你对这次共同决定的想法</h2></div>`}${error?.metadata.error?`<div class="notice warm">${esc(error.content)}<button type="button" class="button ghost small" data-pref-table>暂时手动整理结果</button></div>`:''}<p class="interview-context">我们一起决定：<strong>${esc(state.room.scenario.title||"本次共同选择")}</strong></p>${questionCard(state,locked)}${q&&!q.ready&&!currentInterviewInput(state)?`<div class="actions interview-controls"><button type="button" class="button ghost small" data-action="interview-answer" data-choice="skip" ${locked||pending?'disabled':''}>暂未确定</button><button type="button" class="button secondary small" data-action="interview-summary" ${locked||pending?'disabled':''}>整理需求</button></div>`:''}<details class="interview-compose" data-disclosure="interview-input" ${state.zen?'':'open'}><summary>自由补充想法</summary><form id="interview-form" class="stack">${textarea('你的想法','text',state.interviewRaw||'','rows="3" maxlength="6000" placeholder="也可以用自己的话说，会和卡片回答一起整理。"')}<button type="submit" class="button" ${locked||pending?'disabled':''}>${pending?'正在整理…':q?'补充我的回答':'开始表达'}</button></form></details></section>`;
}
function criterionRows(criteria){return criteria.map((c,i)=>`<tr data-criterion-row="${i}"><th><input aria-label="具体要求名称 ${i+1}" name="criterion:${i}:name" data-criterion-field="name" value="${esc(c.name)}" maxlength="80" placeholder="要求名称"></th><td><div class="criteria-controls">${select('态度',`criterion:${i}:rating`,String(c.rating??100),ratings.slice(1),'data-criterion-field="rating"')}${select('用途',`criterion:${i}:hard`,c.hard?'hard':'soft',[['soft','偏好'],['hard','必要']],'data-criterion-field="hard"')}<details class="criterion-options"><summary>更多</summary>${select('范围',`criterion:${i}:scope`,c.scope||'any',[['any','至少一项'],['all','每一项']],'data-criterion-field="scope"')}${select('在意程度',`criterion:${i}:weight`,String(c.weight??3),importance,'data-criterion-field="weight"')}</details></div></td><td><button type="button" class="edit-row" data-pref-remove-criterion="${i}" aria-label="移除这项要求">${icon('close',17)}</button></td></tr>`).join('');}
function preferenceSummary(p,locked=false){
 const rows=[],add=(name,value,section,kind='')=>rows.push({name,value,section,kind});
 if(p.budget_max!=null)add('人均上限',money(p.budget_max),'cost','必要');
 if(p.cost_preference==='lower')add('费用倾向','越实惠越好','cost','偏好');
 if(p.budget_target!=null)add('理想人均',money(p.budget_target),'cost','偏好');
 if((p.available_start??0)!==0||(p.available_end??1440)!==1440)add('可参加时间',time(p.available_start)+'–'+time(p.available_end),'time','必要');
 if(p.max_duration!=null)add('最长时长',p.max_duration+' 分钟','time','必要');
 if(p.preferred_start!=null||p.preferred_end!=null)add('希望的时间',(p.preferred_start==null?'不限开始':time(p.preferred_start))+'–'+(p.preferred_end==null?'不限结束':time(p.preferred_end)),'time','偏好');
 for(const [name,value] of Object.entries(p.categories||{}))add(name,value===100?'喜欢':value===0?'不喜欢':'都可以','categories','偏好');
 for(const criterion of p.criteria||[])add(criterion.name,criterion.rating===100?'希望具备':criterion.rating===0?'希望避开':'都可以','criteria',criterion.hard?'必要':'偏好');
 if(p.excluded_categories?.length)add('排除类别',p.excluded_categories.join('、'),'limits','必要');
 if(p.allowed_locations?.length)add('可接受地点',p.allowed_locations.join('、'),'limits','必要');
 return `${p.other?`<blockquote class="original-expression">${esc(p.other)}</blockquote>`:''}${rows.length?`<table class="preference-summary"><thead><tr><th>我的需求</th><th>内容</th><th></th></tr></thead><tbody>${rows.map(row=>`<tr><th>${esc(row.name)}${row.kind?`<span class="requirement-kind">${row.kind}</span>`:''}</th><td>${esc(row.value)}</td><td>${locked?'':`<button type="button" class="edit-row" data-pref-edit="${row.section}" aria-label="修改${esc(row.name)}">${icon('sliders',17)}</button>`}</td></tr>`).join('')}</tbody></table>`:!p.other?'<p class="preference-empty">暂无特殊要求</p>':''}${p.notes?.length?`<details class="preference-notes"><summary>备注 ${p.notes.length}</summary><ul>${p.notes.map(note=>`<li>${esc(note)}</li>`).join('')}</ul></details>`:''}`;
}
export function preferenceEditor(state){
 const r=state.room,locked=terminal.has(r.state)||r.state==='VOTING',saving=state.savingPreferences?.has(r.id)||false;
 const turn=latestInterview(state),saved=locked?r.me.preference||{}:interviewDraft(state),original=state.messages.find(message=>message.role==='user'&&message.kind==='interview'&&message.metadata.preference_version===r.me.preference_version&&message.metadata.interview_action==='answer'&&!message.content.startsWith('针对问题'))?.content;
 const p={...saved,other:saved.other||original||''},draft=Boolean(state.prefDraft||turn),criteria=p.criteria||[];
 const categories=[...new Set([...r.resources.map(x=>x.category),...Object.keys(p.categories||{})])];
 const stage=locked||state.prefStep>0?1:0,unlimited=(p.available_start??0)===0&&(p.available_end??1440)===1440;
 const raw=state.messages.filter(message=>message.role==='user'&&message.kind==='interview'&&message.metadata.preference_version===r.me.preference_version&&!['continue','start','finish'].includes(message.metadata.interview_action));
 return `<div class="pref-editor stack"><details class="pref-process-guide" data-disclosure="interview-guide" data-pref-process-guide ${stage?'hidden':''}><summary>卡片操作</summary><p>左右滑动或点击作答，需要填写时会打开输入卡片。</p></details><div data-interview-panel ${stage?'hidden':''}>${interviewCard(state,locked)}</div>
 <section class="preference-result" data-pref-result ${stage?'':'hidden'}><header class="workspace-heading"><h1>我的需求</h1><div class="actions">${!locked&&turn?`<button type="button" class="text-button" data-action="interview-summary" ${r.ai_pending?'disabled':''}>重新整理</button>`:''}<span data-pref-badge class="badge ${r.me.confirmed&&!draft?'good':''}">${draft?'待确认':r.me.confirmed?'已确认 V'+r.me.preference_version:'待确认'}</span></div></header>
 ${state.prefDraft&&turn&&turn.id>(state.prefDraft.source_message_id||0)?`<div class="notice"><button type="button" class="text-button" data-action="apply-draft" data-id="${turn.id}">查看新整理的需求</button></div>`:''}
 ${turn?.metadata.warnings?.length?`<div class="notice warm">${esc(turn.metadata.warnings.join(' '))}<button type="button" class="text-button" data-action="interview-summary">重试整理</button></div>`:''}
 <form id="preference-form" data-preference-editor data-pref-step="${stage}" data-locked="${locked}" data-saving="${saving}" data-confirmed="${r.me.confirmed}" data-original="${esc(JSON.stringify(r.me.preference||{}))}" novalidate><div data-pref-table-panel ${stage?'':'hidden'}><fieldset class="pref-fields" ${locked||saving?'disabled':''}>
 <textarea name="criteria_json" hidden>${esc(JSON.stringify(criteria))}</textarea><textarea name="discovery_json" hidden>${esc(JSON.stringify(p.discovery||{}))}</textarea><textarea name="unresolved" hidden>${esc((p.unresolved||[]).join('\n'))}</textarea>
 <div data-pref-summary>${preferenceSummary(p,locked)}</div>
 ${locked?'':`<details class="pref-add-menu"><summary>添加需求 ${icon('plus',16)}</summary><div>${[['cost','费用'],['time','时间'],['criteria','具体要求'],['categories','类别喜好'],['limits','必要限制'],['notes','原话与备注']].map(([section,label])=>`<button type="button" class="text-button" data-pref-edit="${section}">${label}</button>`).join('')}</div></details>`}
 <div class="pref-edit-area" data-pref-edit-area hidden><header><h2>调整需求</h2><button type="button" class="text-button" data-pref-edit-close>完成修改 ${icon('check',16)}</button></header>
 <section data-pref-edit-section="cost" hidden><div class="form-grid">${select('费用倾向','cost_preference',p.cost_preference||'neutral',[['neutral','无特别倾向'],['lower','越实惠越好']])}${field('理想人均 / 元','budget_target',p.budget_target??'','number','min="0" max="1000000" step="0.01"')}${field('人均上限 / 元','budget_max',p.budget_max??'','number','min="0" max="1000000" step="0.01"')}${select('在意程度','budget_weight',String(p.budget_weight??3),importance)}</div></section>
 <section data-pref-edit-section="time" hidden>${check('当天时间不限','time_unlimited',unlimited)}<div class="form-grid">${field('最早参加','available_start',time(p.available_start??0),'time','step="60"')}${field('最晚结束','available_end',time(p.available_end??1440),'text','placeholder="24:00"')}${field('最长时长 / 分钟','max_duration',p.max_duration??'','number','min="15" max="1440"')}${field('希望开始','preferred_start',p.preferred_start==null?'':time(p.preferred_start),'time')}${field('希望结束','preferred_end',p.preferred_end==null?'':time(p.preferred_end),'text','placeholder="24:00"')}${select('在意程度','time_weight',String(p.time_weight??3),importance)}</div></section>
 <section data-pref-edit-section="categories" hidden><div class="form-grid">${categories.map(c=>select(c,`category:${c}`,String(p.categories?.[c]??''),ratings)).join('')}${select('在意程度','activity_weight',String(p.activity_weight??3),importance)}</div></section>
 <section data-pref-edit-section="limits" hidden><div class="form-grid">${field('排除的类别','excluded_categories',(p.excluded_categories||[]).join('，'),'text','placeholder="逗号分隔"')}${field('可接受地点','allowed_locations',(p.allowed_locations||[]).join('，'),'text','placeholder="逗号分隔"')}</div></section>
 <section data-pref-edit-section="criteria" hidden><table class="needs-table"><thead><tr><th>要求</th><th>选择</th><th></th></tr></thead><tbody data-pref-criteria>${criterionRows(criteria)}</tbody></table><button type="button" class="button secondary small" data-pref-add-criterion>添加要求</button></section>
 <section data-pref-edit-section="notes" hidden><div class="stack">${textarea('我的原话','other',p.other||'','rows="3" maxlength="2000"')}${textarea('备注','notes',(p.notes||[]).join('\n'),'rows="3" maxlength="10000"')}</div></section></div>
 <div data-pref-questions>${(p.unresolved||[]).map((text,i)=>`<article class="pref-question"><p>${esc(text)}</p><div class="actions"><button type="button" class="text-button" data-pref-edit="${/预算|金额|费用/.test(text)?'cost':'notes'}">补充</button><button type="button" class="text-button" data-pref-resolve="${i}">已明确</button><button type="button" class="text-button" data-pref-note="${i}">只作备注</button></div></article>`).join('')}</div></fieldset>
 <div class="pref-footer"><p data-pref-validation role="status" aria-live="polite" hidden></p>${locked?'':`<div class="actions"><button type="button" class="button secondary" data-pref-interview>继续回答</button><button type="submit" class="button" data-pref-confirm ${saving?'disabled':''}>${saving?'正在确认…':'确认需求'}</button></div>`}</div></div></form>
 ${raw.length?`<details class="workspace-evidence" data-disclosure="my-original-answers"><summary>我的回答</summary>${raw.map(message=>`<p>${esc(message.content)}</p>`).join('')}</details>`:''}</section></div>`;
}
export function readPreference(form){
 const d=Object.fromEntries([...form.elements].filter(el=>el.name&&!['submit','button'].includes(el.type)).map(el=>[el.name,el.value])),categories={};
 for(const [key,value] of Object.entries(d))if(key.startsWith('category:')&&value!=='')categories[key.slice(9)]=Number(value);
 const unlimited=form.elements.time_unlimited.checked;
 return {budget_max:number(d.budget_max),budget_target:number(d.budget_target),budget_weight:number(d.budget_weight??3),cost_preference:d.cost_preference||'neutral',available_start:unlimited?0:readTime(d.available_start),available_end:unlimited?1440:readTime(d.available_end),max_duration:number(d.max_duration),preferred_start:readTime(d.preferred_start),preferred_end:readTime(d.preferred_end),time_weight:number(d.time_weight??3),categories,activity_weight:number(d.activity_weight??3),criteria:parse(d.criteria_json,[]),discovery:parse(d.discovery_json,{}),excluded_categories:split(d.excluded_categories),allowed_locations:split(d.allowed_locations),other:d.other||'',unresolved:lines(d.unresolved),notes:lines(d.notes)};
}
export function updatePreferenceFeedback(form){
 if(!form)return {ready:false,pending:0,errors:[]};
 const p=readPreference(form),errors=[],locked=form.dataset.locked==='true',saving=form.dataset.saving==='true';
 const fail=text=>errors.push({step:1,text});
 for(const key of ['budget_max','budget_target'])if(!form.elements[key].checkValidity()||(p[key]!=null&&(!Number.isFinite(p[key])||p[key]<0||p[key]>1000000)))fail('金额请填写 0–1,000,000，最多两位小数。');
 if(p.available_start==null||p.available_end==null||p.available_end<=p.available_start)fail('参加时间需要有效，结束晚于开始；结束支持 24:00。');
 if((form.elements.preferred_start.value&&p.preferred_start==null)||(form.elements.preferred_end.value&&p.preferred_end==null))fail('希望的时间请按 HH:MM 填写。');
 if(p.preferred_start!=null&&p.preferred_end!=null&&p.preferred_end<=p.preferred_start)fail('希望的结束时间应晚于希望的开始时间。');
 if(!form.elements.max_duration.checkValidity()||(p.max_duration!=null&&(!Number.isInteger(p.max_duration)||p.max_duration<15||p.max_duration>1440)))fail('最长时长可留空，或填写 15–1440 分钟整数。');
 if(p.criteria.length>12||p.criteria.some(c=>!c.name.trim()||c.name.length>80||(c.hard&&c.rating===50))||new Set(p.criteria.map(c=>c.name.trim().toLowerCase())).size!==p.criteria.length)fail('具体要求最多 12 条，名称不可重复或为空；“都可以”不能设为必要条件。');
 if(Object.keys(p.categories).length>30||p.excluded_categories.length>30||p.allowed_locations.length>30||[...Object.keys(p.categories),...p.excluded_categories,...p.allowed_locations].some(v=>v.length>80))fail('类别与地点各最多 30 项，每项最多 80 字。');
 if(p.notes.length>20||p.notes.some(v=>v.length>500)||p.other.length>2000)fail('补充说明最多 20 条、每条 500 字；原话最多 2000 字。');
 const fingerprint=value=>JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
 const unchanged=form.dataset.confirmed==='true'&&fingerprint(p)===fingerprint(parse(form.dataset.original,{}));
 const pending=p.unresolved.length,ready=!locked&&!saving&&!pending&&!errors.length&&!unchanged;
 const status=setText('[data-pref-validation]',pending?`还有 ${pending} 项需要明确。`:errors[0]?.text||'',form);if(status)status.hidden=!pending&&!errors.length;
 const button=$('[data-pref-confirm]',form);if(button)button.disabled=!ready;
 const summary=$('[data-pref-summary]',form);if(summary)summary.innerHTML=preferenceSummary(p,locked);
 return {ready,pending,errors};
}
let cleanup=null,activeRoot=null,changeStage=null;
export function goToPreferenceStep(step){changeStage?.(step>0?1:0);activeRoot?.querySelector(step>0?'[data-pref-result]':'[data-pref-process-guide]')?.scrollIntoView({block:'start',behavior:'smooth'});}
export function mountPreferenceEditor(root,onStep){
 cleanup?.();cleanup=null;activeRoot=root;changeStage=null;
 const form=root?.querySelector('form[data-preference-editor]');if(!form)return;
 const controller=new AbortController(),opts={signal:controller.signal};
 changeStage=stage=>{form.dataset.prefStep=String(stage);$('[data-pref-table-panel]',form).hidden=stage===0;$('[data-interview-panel]',root).hidden=stage===1;$('[data-pref-process-guide]',root).hidden=stage===1;$('[data-pref-result]',root).hidden=stage===0;onStep(stage);};
 const persist=()=>form.elements.criteria_json.dispatchEvent(new Event('input',{bubbles:true}));
 const syncCriteria=()=>{const values=$$('[data-criterion-row]',form).map(row=>Object.fromEntries($$('[data-criterion-field]',row).map(el=>{const key=el.dataset.criterionField;return [key,key==='hard'?el.value==='hard':['rating','weight'].includes(key)?Number(el.value):el.value];})));form.elements.criteria_json.value=JSON.stringify(values);};
 root.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button||button.disabled)return;
  const area=$('[data-pref-edit-area]',form);
  if(button.hasAttribute('data-pref-edit')){
   area.hidden=false;
   for(const section of $$('[data-pref-edit-section]',form))section.hidden=section.dataset.prefEditSection!==button.dataset.prefEdit;
   $('.pref-add-menu',form)?.removeAttribute('open');
   area.scrollIntoView({block:'nearest',behavior:'smooth'});
  }else if(button.hasAttribute('data-pref-edit-close'))area.hidden=true;
 },opts);
 root.addEventListener('click',event=>{const button=event.target.closest('button');if(!button||button.disabled)return;if(button.hasAttribute('data-pref-table'))goToPreferenceStep(1);else if(button.hasAttribute('data-pref-interview'))goToPreferenceStep(0);else if(button.hasAttribute('data-pref-add-criterion')){const values=parse(form.elements.criteria_json.value,[]);if(values.length>=12)return;values.push({name:'',rating:100,weight:3,hard:false,scope:'any'});form.elements.criteria_json.value=JSON.stringify(values);$('[data-pref-criteria]',form).innerHTML=criterionRows(values);persist();}else if(button.hasAttribute('data-pref-remove-criterion')){const values=parse(form.elements.criteria_json.value,[]);values.splice(Number(button.dataset.prefRemoveCriterion),1);form.elements.criteria_json.value=JSON.stringify(values);$('[data-pref-criteria]',form).innerHTML=criterionRows(values);persist();}else if(button.hasAttribute('data-pref-resolve')||button.hasAttribute('data-pref-note')){const values=lines(form.elements.unresolved.value),index=values.indexOf(button.closest('.pref-question').querySelector('p').textContent);if(index<0)return;const [text]=values.splice(index,1);if(text&&button.hasAttribute('data-pref-note'))form.elements.notes.value=[...new Set([...lines(form.elements.notes.value),text])].join('\n');form.elements.unresolved.value=values.join('\n');button.closest('.pref-question').remove();persist();}},opts);
 const update=event=>{if(event?.target?.dataset.criterionField){syncCriteria();persist();}const disabled=form.elements.time_unlimited.checked||form.dataset.locked==='true'||form.dataset.saving==='true';form.elements.available_start.disabled=disabled;form.elements.available_end.disabled=disabled;updatePreferenceFeedback(form);};
 form.addEventListener('input',update,opts);form.addEventListener('change',update,opts);
 installSwipe($('[data-interview-card]',root),controller.signal);
 update();changeStage(Number(form.dataset.prefStep||0));cleanup=()=>controller.abort();
}
