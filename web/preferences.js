import {$,$$,setText,esc,icon,field,textarea,select,check,time,money,minutes,number,terminal} from './common.js';

const STEPS=['预算','时间','活动偏好','待确认问题','预览确认'];
const split=value=>String(value||'').split(/[,，\n]/).map(v=>v.trim()).filter(Boolean);
const lines=value=>String(value||'').split('\n').map(v=>v.trim()).filter(Boolean);
const importance=[['1','不太在意'],['2','略微在意'],['3','一般'],['4','比较在意'],['5','非常在意']];
function endTimes(value,optional=false){
  const values=new Set(Array.from({length:48},(_,i)=>time((i+1)*30)));
  if(value!=null)values.add(time(value));
  return [...(optional?[['','暂不设置']]:[]),...[...values].sort().map(v=>[v,v])];
}
function endTimeField(label,name,value,optional=false){
  return field(label,name,value==null?'':time(value),'text',`list="${name}-choices" maxlength="5" placeholder="${optional?'可留空，':''}例如 18:45 或 24:00"`)+`<datalist id="${name}-choices">${endTimes(value).map(([v])=>`<option value="${v}"></option>`).join('')}</datalist>`;
}
const readTime=value=>/^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(value)?minutes(value):value==='24:00'?1440:null;
function questionCards(questions){
  return questions.length?questions.map((text,i)=>`<article class="pref-question"><div class="between"><strong>需要你核对 · ${i+1}</strong><span class="badge warm">待确认</span></div><p>${esc(text)}</p><div class="actions"><button type="button" class="button secondary small" data-pref-resolve="${i}">已核对，按我填写的条件处理</button><button type="button" class="button ghost small" data-pref-note="${i}">只作补充，不设为限制</button></div></article>`).join(''):'<div class="notice">没有尚未处理的问题。下面的补充说明不会阻止你确认需求。</div>';
}
function page(index,title,description,content){
  return `<section class="pref-step" data-pref-page="${index}" aria-label="第 ${index+1} 步：${STEPS[index]}"><div class="pref-step-heading"><span class="eyebrow">STEP ${String(index+1).padStart(2,'0')}</span><h2>${title}</h2><p>${description}</p></div>${content}</section>`;
}
export function preferenceEditor(state){
  const r=state.room,locked=terminal.has(r.state)||r.state==='VOTING',saving=state.savingPreferences?.has(r.id)||false;
  const draft=!locked&&state.prefDraft,p=draft?.preference||r.me.preference||{};
  const categories=[...new Set(['户外','文化','室内','美食','运动','休闲',...r.resources.map(x=>x.category),...Object.keys(p.categories||{})])];
  const questions=p.unresolved||[],unlimited=(p.available_start??0)===0&&(p.available_end??1440)===1440;
  const step=Math.max(0,Math.min(4,state.prefStep||0));
  return `<div class="card pref-editor"><div class="card-title"><div><h2>慢慢填，一步一步就好</h2><p class="hint">左右滑动卡片，或点击步骤与下方按钮。填写内容会保留在当前浏览器。</p></div><span data-pref-badge class="badge ${!draft&&r.me.confirmed?'good':''}">${draft?'草稿 · 待你确认':r.me.confirmed?'已确认 V'+r.me.preference_version:'尚未确认'}</span></div>
  ${locked?'<div class="notice warm">投票期间或决策结束后，个人条件已锁定；仍可翻看各张卡片。</div>':''}
  <form id="preference-form" data-preference-editor novalidate data-pref-step="${step}" data-locked="${locked}" data-saving="${saving}">
    <nav class="pref-progress" aria-label="填写步骤">${STEPS.map((label,i)=>`<button type="button" data-pref-go="${i}" class="${i===step?'active':''}" ${i===step?'aria-current="step"':''}><span>${i+1}</span>${label}${i===3?'<b data-pref-pending></b>':''}</button>`).join('')}</nav>
    <fieldset class="pref-fields" ${locked||saving?'disabled':''}>
      <textarea name="unresolved" hidden>${esc(questions.join('\n'))}</textarea>
      <div class="pref-track" data-pref-track tabindex="0" role="region" aria-label="个人需求填写卡片，可用左右方向键翻页">
        ${page(0,'这次，花多少比较舒服？','预算上限是必须遵守的条件；理想预算只是偏好，留空也可以确认。',`<div class="form-grid pref-large-fields">${field('最多能花多少 / 人','budget_max',p.budget_max??'','number','min="0" max="1000000" step="0.01" placeholder="留空表示暂不设上限"')}${field('希望控制在多少 / 人','budget_target',p.budget_target??'','number','min="0" max="1000000" step="0.01" placeholder="可选，填一个更舒服的金额"')}</div><div class="pref-quick"><span class="hint">快速设置理想预算</span>${[50,100,150,200,300,500].map(v=>`<button type="button" data-pref-budget="${v}">${v} 元</button>`).join('')}</div><div class="notice" style="margin-top:24px">例如上限 500 元、理想 150 元：超过 500 的方案直接排除，150 元以内会更符合你的预算偏好。</div><div class="pref-compact">${select('低预算对你有多重要？','budget_weight',String(p.budget_weight??3),importance)}</div>`)}
        ${page(1,'什么时候，方便一起出发？','没有时间限制可以直接选择“时间不限”，不必手动填写 00:00 到 24:00。',`${check('时间不限，按当天活动安排','time_unlimited',unlimited)}<div class="form-grid pref-large-fields" style="margin-top:20px">${field('最早可以参加','available_start',time(p.available_start??540),'time','step="60"')}${endTimeField('最晚需要结束','available_end',p.available_end??1260)}</div><div class="pref-compact">${field('最多能玩多久 / 分钟（含转场和等待）','max_duration',p.max_duration??'','number','min="15" max="1440" step="1" placeholder="可留空，例如 90 分钟"')}</div><details class="advanced"><summary>我还有希望尽量满足的时间偏好（可选）</summary><div class="form-grid">${field('希望尽量晚于这个时间开始','preferred_start',p.preferred_start==null?'':time(p.preferred_start),'time','step="60"')}${endTimeField('希望尽量早于这个时间结束','preferred_end',p.preferred_end,true)}${select('时间偏好有多重要？','time_weight',String(p.time_weight??3),importance)}</div></details>`)}
        ${page(2,'哪些活动，会让你更期待？','点选你的态度，不感兴趣的类别也可以保持“未评价”。明确不能参加的类别放在下方必要限制里。',`<div class="pref-category-grid">${categories.map(c=>`<div class="pref-category" data-category="${esc(c)}"><strong>${esc(c)}</strong><input type="hidden" name="category:${esc(c)}" value="${p.categories?.[c]??''}"><div>${[['','未评价'],['100','喜欢'],['50','一般'],['0','不喜欢']].map(([value,label])=>`<button type="button" data-pref-category="${esc(c)}" data-value="${value}" aria-pressed="${String(p.categories?.[c]??'')===value}">${label}</button>`).join('')}</div></div>`).join('')}</div><div class="pref-compact">${select('活动类型对你有多重要？','activity_weight',String(p.activity_weight??3),importance)}</div><div style="margin-top:22px">${textarea('还有什么想说的？','other',p.other||'','rows="3" maxlength="2000" placeholder="例如：想吃自助，希望环境安静、适合慢慢聊天。"')}</div><details class="advanced"><summary>必须避开的活动或必须去的地点（可选）</summary><div class="form-grid">${field('明确不能参加的活动类别','excluded_categories',(p.excluded_categories||[]).join('，'),'text','placeholder="例如 运动，户外；逗号分隔"')}${field('允许的地点名称','allowed_locations',(p.allowed_locations||[]).join('，'),'text','placeholder="留空不限制；多个名称用逗号分隔"')}</div><p class="hint">地点限制按候选活动中填写的地点名称匹配；没有这个必要条件时请留空。</p></details>`)}
        ${page(3,'把不确定的地方，说清楚就好。','逐条核对 AI 的提问。已经通过填写解决的问题，可标记已处理；只是建议或候选资料不足，可保留为补充说明。',`<div class="pref-questions" data-pref-questions>${questionCards(questions)}</div><div class="form-section">${textarea('补充说明与建议（不会阻止确认）','notes',(p.notes||[]).join('\n'),'rows="3" maxlength="10000" placeholder="一行一条。候选资源待补充、理想预算未设置等，可记在这里。"')}<p class="hint">缺少理想预算、没有选择某类偏好、候选活动需要补充，都不等于你的个人硬约束尚未确认。</p></div>`)}
        ${page(4,'最后看一眼，这些是你的想法。','只有你点击确认，下面的条件才会成为正式决策依据。AI 草稿不会自动生效。',`<div class="pref-review" data-pref-review></div><div class="notice" style="margin-top:20px">没有设置的可选项不会被强行补成限制。候选活动的费用、地点与日期是否完整，由房间方案分析另外检查。</div>`)}
      </div>
    </fieldset>
    <div class="pref-footer"><div class="pref-validation" data-pref-validation role="status" aria-live="polite"></div><div class="between"><span class="hint" data-pref-position aria-live="polite">${step+1} / 5 · ${STEPS[step]}</span><div class="actions"><button type="button" class="button secondary" data-pref-back>上一步</button><button type="button" class="button" data-pref-next>下一步 ${icon('arrow',15)}</button><button type="submit" class="button" data-pref-confirm hidden>${saving?'<span class="spinner"></span> 正在保存':icon('check',16)+' 由我确认这些条件'}</button></div></div></div>
  </form></div>`;
}
export function readPreference(form){
  // FormData skips disabled controls; locked records must remain readable in the preview.
  const d=Object.fromEntries([...form.elements].filter(el=>el.name&&!['submit','button'].includes(el.type)).map(el=>[el.name,el.value])),categories={};
  for(const [key,value] of Object.entries(d))if(key.startsWith('category:')&&value!=='')categories[key.slice(9)]=Number(value);
  const unlimited=form.elements.time_unlimited.checked;
  return {budget_max:number(d.budget_max),budget_target:number(d.budget_target),budget_weight:number(d.budget_weight??3),available_start:unlimited?0:readTime(d.available_start),available_end:unlimited?1440:readTime(d.available_end),max_duration:number(d.max_duration),preferred_start:readTime(d.preferred_start),preferred_end:readTime(d.preferred_end),time_weight:number(d.time_weight??3),categories,activity_weight:number(d.activity_weight??3),excluded_categories:split(d.excluded_categories),allowed_locations:split(d.allowed_locations),other:d.other||'',unresolved:lines(d.unresolved),notes:lines(d.notes)};
}
export function updatePreferenceFeedback(form){
  if(!form)return {ready:false,pending:0,errors:[]};
  const p=readPreference(form),errors=[],locked=form.dataset.locked==='true',saving=form.dataset.saving==='true';
  for(const key of ['budget_max','budget_target']){
    const input=form.elements[key];
    if(input.validity.badInput||input.validity.stepMismatch||(p[key]!=null&&(!Number.isFinite(p[key])||p[key]<0||p[key]>1000000)))errors.push({step:0,text:'预算请填写 0–1,000,000 之间的金额，最多保留两位小数。'});
  }
  if(!form.elements.time_unlimited.checked&&(p.available_start==null||p.available_end==null||p.available_end<=p.available_start))errors.push({step:1,text:'请选择有效的时间段，结束时间需要晚于开始时间。'});
  if((form.elements.preferred_start.value&&p.preferred_start==null)||(form.elements.preferred_end.value&&p.preferred_end==null))errors.push({step:1,text:'希望的时间请按 HH:MM 填写，例如 18:45；结束时间支持 24:00。'});
  if(form.elements.max_duration.validity.badInput||(p.max_duration!=null&&(!Number.isInteger(p.max_duration)||p.max_duration<15||p.max_duration>1440)))errors.push({step:1,text:'最长总时长可留空，或填写 15–1,440 分钟之间的整数。'});
  if(p.preferred_start!=null&&p.preferred_end!=null&&p.preferred_end<=p.preferred_start)errors.push({step:1,text:'希望的结束时间需要晚于希望的开始时间。'});
  if(Object.keys(p.categories).length>30||p.excluded_categories.length>30||p.allowed_locations.length>30||[...Object.keys(p.categories),...p.excluded_categories,...p.allowed_locations].some(v=>v.length>80))errors.push({step:2,text:'活动偏好、排除类别和地点各最多 30 项，每项不超过 80 字。'});
  if(p.other.length>2000)errors.push({step:2,text:'其他想法请控制在 2,000 字以内。'});
  if(p.notes.length>20||p.notes.some(v=>v.length>500))errors.push({step:3,text:'补充说明最多 20 条，每条不超过 500 字。'});
  const pending=p.unresolved.length,ready=!locked&&!saving&&!pending&&!errors.length;
  const status=setText('[data-pref-validation]',saving?'正在保存这次确认，请稍候。':locked?'这些是已锁定的个人条件，可以翻页查看。':pending?`还有 ${pending} 项待核对，请在“待确认问题”卡片中逐条处理。`:errors[0]?.text||'内容会保留；最后一步由你确认生效。',form);
  status?.classList.toggle('pref-invalid',!locked&&Boolean(pending||errors.length));
  $('[data-pref-confirm]',form).disabled=!ready;
  setText('[data-pref-pending]',pending?String(pending):'',form);
  const weight=value=>importance.find(([v])=>v===String(value))?.[1]||'一般';
  const categories=Object.entries(p.categories).map(([c,v])=>`${v===100?'喜欢':v===50?'一般':'不喜欢'}：${c}`).join('；')||'尚未评价，保留选择空间';
  const preferred=[p.preferred_start==null?'':`希望 ${time(p.preferred_start)} 之后开始`,p.preferred_end==null?'':`希望 ${time(p.preferred_end)} 之前结束`].filter(Boolean).join('；');
  const rows=[['必须遵守的预算上限',p.budget_max==null?'暂不设上限':money(p.budget_max)+' / 人'],['希望的理想预算',p.budget_target==null?'暂不设置，不影响确认':`${money(p.budget_target)} / 人 · ${weight(p.budget_weight)}`],['可参加时间',p.available_start===0&&p.available_end===1440?'当天时间不限':`${time(p.available_start)} – ${time(p.available_end)}`],['最长总时长',p.max_duration==null?'暂不限制':`${p.max_duration} 分钟`],['希望的时间偏好',preferred?`${preferred} · ${weight(p.time_weight)}`:'暂不设置'],['活动偏好',categories+(Object.keys(p.categories).length?` · ${weight(p.activity_weight)}`:'')],['明确排除的类别',p.excluded_categories.join('、')||'暂不设置'],['地点限制',p.allowed_locations.join('、')||'暂不设置'],['其他想法',p.other||'无'],['补充说明（不作为限制）',p.notes.join('\n')||'无'],['待核对问题',pending?`${pending} 项尚未处理`:'已处理完毕']];
  $('[data-pref-review]',form).innerHTML=rows.map(([label,value])=>`<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('');
  return {ready,pending,errors};
}
let cleanup=null,activeForm=null,changeStep=null;
export function goToPreferenceStep(step){
  if(!activeForm)return;
  const track=$('[data-pref-track]',activeForm),index=Math.max(0,Math.min(4,step));
  track.scrollTo({left:index*track.clientWidth,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
  changeStep?.(index);
}
export function mountPreferenceEditor(root,onStep){
  cleanup?.();cleanup=null;activeForm=null;changeStep=null;
  const form=root?.querySelector('form[data-preference-editor]');
  if(!form)return;
  const track=$('[data-pref-track]',form),pages=$$('[data-pref-page]',form);
  // Mount only the complete card editor, never another room page or a stale form.
  const complete=['validation','confirm','position','back','next','review','questions'].every(name=>$(`[data-pref-${name}]`,form));
  if(!track||pages.length!==STEPS.length||!complete)return;
  activeForm=form;
  let timer=null,current=Number(form.dataset.prefStep||0),observer=null,previousWidth=track.clientWidth;
  const resize=()=>{const width=track.clientWidth;if(width!==previousWidth){previousWidth=width;track.scrollLeft=current*width;}track.style.height=Math.max(280,Math.ceil(pages[current].scrollHeight))+'px';};
  changeStep=index=>{
    current=index;form.dataset.prefStep=String(index);onStep(index);
    for(const page of pages){const inactive=Number(page.dataset.prefPage)!==index;page.inert=inactive;page.setAttribute('aria-hidden',String(inactive));}
    for(const button of $$('[data-pref-go]',form)){const selected=Number(button.dataset.prefGo)===index;button.classList.toggle('active',selected);if(selected)button.setAttribute('aria-current','step');else button.removeAttribute('aria-current');}
    $('[data-pref-back]',form).disabled=index===0;
    $('[data-pref-next]',form).hidden=index===4;
    $('[data-pref-confirm]',form).hidden=index!==4;
    setText('[data-pref-position]',`${index+1} / 5 · ${STEPS[index]}`,form);
    resize();
  };
  const persist=()=>form.elements.unresolved.dispatchEvent(new Event('input',{bubbles:true}));
  form.addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button||button.disabled)return;
    if(button.closest('fieldset:disabled'))return;
    if(button.hasAttribute('data-pref-go'))goToPreferenceStep(Number(button.dataset.prefGo));
    else if(button.hasAttribute('data-pref-back'))goToPreferenceStep(current-1);
    else if(button.hasAttribute('data-pref-next'))goToPreferenceStep(current+1);
    else if(button.hasAttribute('data-pref-budget')){form.elements.budget_target.value=button.dataset.prefBudget;persist();}
    else if(button.hasAttribute('data-pref-category')){
      form.elements.namedItem('category:'+button.dataset.prefCategory).value=button.dataset.value;
      for(const option of $$('button',button.closest('[data-category]')))option.setAttribute('aria-pressed',String(option===button));
      persist();
    }else if(button.hasAttribute('data-pref-resolve')||button.hasAttribute('data-pref-note')){
      const questions=lines(form.elements.unresolved.value),index=Number(button.dataset.prefResolve??button.dataset.prefNote),[question]=questions.splice(index,1);
      if(question&&button.hasAttribute('data-pref-note'))form.elements.notes.value=[...new Set([...lines(form.elements.notes.value),question])].join('\n');
      form.elements.unresolved.value=questions.join('\n');
      $('[data-pref-questions]',form).innerHTML=questionCards(questions);persist();resize();
    }
  });
  const update=()=>{const disabled=form.elements.time_unlimited.checked||form.dataset.locked==='true'||form.dataset.saving==='true';form.elements.available_start.disabled=disabled;form.elements.available_end.disabled=disabled;updatePreferenceFeedback(form);resize();};
  form.addEventListener('input',update);
  form.addEventListener('change',event=>{
    if(event.target.name==='time_unlimited'&&!event.target.checked&&form.elements.available_start.value==='00:00'&&form.elements.available_end.value==='24:00'){form.elements.available_start.value='09:00';form.elements.available_end.value='21:00';persist();}
    update();
  });
  form.addEventListener('keydown',event=>{
    if(event.key==='Enter'&&!event.isComposing&&current<4&&event.target.matches('input:not([type=checkbox])')){event.preventDefault();goToPreferenceStep(current+1);return;}
    if(!['ArrowLeft','ArrowRight'].includes(event.key)||(event.target!==track&&!event.target.closest('[data-pref-go]')))return;
    event.preventDefault();goToPreferenceStep(current+(event.key==='ArrowRight'?1:-1));
    if(event.target!==track)$(`[data-pref-go="${current}"]`,form).focus({preventScroll:true});
  });
  track.addEventListener('scroll',()=>{clearTimeout(timer);timer=setTimeout(()=>{if(track.clientWidth)changeStep?.(Math.max(0,Math.min(4,Math.round(track.scrollLeft/track.clientWidth))));},120);},{passive:true});
  if(window.ResizeObserver){observer=new ResizeObserver(resize);for(const page of pages)observer.observe(page);observer.observe(track);}
  update();changeStep(current);track.scrollLeft=current*track.clientWidth;
  cleanup=()=>{clearTimeout(timer);observer?.disconnect();};
}
