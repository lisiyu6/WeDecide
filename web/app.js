import {$,$$,esc,logo,icon,api,post,toast,dialog,confirmAction,copy,formData,number,minutes,time,field,textarea,select,badge,labels,terminal,empty,saveDraft,loadDraft,deleteDraft,startSpeech,captureInputs,restoreInputs,dateTime,money,score} from './common.js';
import {home,creation,joinPage,waiting} from './pages.js';
import {layout,tabs,resourceForm} from './room-views.js';
import {readProvider} from './provider.js';

const state={bootstrap:null,room:null,rooms:[],tab:'overview',route:'home',code:'',messages:[],hasOlder:false,provider:null,connected:false,chatMode:'private',chatRaw:'',prefDraft:null,simFairness:null,menu:false,creationDraft:loadDraft('wd-create')||{},dirtyForms:new Set(),formRevisions:{}};
let stream=null,routeVersion=0,refreshing=false,refreshAgain=false,deadlineRefresh=false,displayTimer=null;
const roomPath=suffix=>`/api/rooms/${encodeURIComponent(state.room.id)}${suffix}`;
const draftKey=()=>`wd-pref:${state.room.id}:${state.room.me.id}`;
const chatKey=()=>`wd-chat:${state.room.id}:${state.chatMode}`;
function render(preserve=false) {
 const root=$('#app');
 const saved=preserve?captureInputs(root):null;
 if(saved)saved.values=saved.values.filter(v=>state.dirtyForms.has(v.form));
 if(state.route==='home')root.innerHTML=home(state.rooms,state.bootstrap);
 else if(state.route==='new')root.innerHTML=creation(state.bootstrap,state.creationDraft);
 else if(state.route==='join')root.innerHTML=joinPage(state.code);
 else if(state.route==='room')root.innerHTML=state.room.me.status==='approved'?layout(state):waiting(state.room);
 if(saved)restoreInputs(root,saved);
 if(state.room?.me.status==='approved'){
   const chat=$('.chat-messages');if(chat)chat.scrollTop=chat.scrollHeight;
   countdown();
 }
 document.title=state.room?.scenario?.title?`${state.room.scenario.title} · WeDecide`:'WeDecide · 一起，做个好决定';
}
async function refresh(preserve=true) {
 if(state.route!=='room'||!state.room)return;
 if(refreshing){refreshAgain=true;return;}
 refreshing=true;const version=routeVersion,key=state.room.id;
 try{
   const room=await api(`/api/rooms/${encodeURIComponent(key)}`);
   if(version!==routeVersion)return;
   let recent=null,provider=state.provider;
   if(room.me.status==='approved'){
     const results=await Promise.all([
       api(`/api/rooms/${encodeURIComponent(key)}/messages`),
       room.host_id===room.me.id?api(`/api/rooms/${encodeURIComponent(key)}/provider`):Promise.resolve(null)
     ]);
     [recent,provider]=results;
   }
   if(version!==routeVersion)return;
   const sameVote=room.vote?.id===state.room.vote?.id;
   if(!sameVote){state.voteSession=null;state.dirtyForms.delete('vote-form');}
   state.room=room;state.provider=provider;
   if(recent){
     const previous=state.messages.filter(m=>recent.length&&m.id<recent[0].id);
     state.messages=[...previous,...recent].slice(-300);
   }
   render(preserve&&(state.tab!=='vote'||sameVote));
 }catch(error){
   if(version===routeVersion&&error.status===404){stream?.close();state.route='home';state.room=null;const rooms=await api('/api/rooms');if(version===routeVersion){state.rooms=rooms;render();toast(error.message,true);}}
   else if(version===routeVersion)toast(error.message,true);
 }finally{refreshing=false;if(refreshAgain){refreshAgain=false;void refresh(preserve);}}
}
function connect() {
 stream?.close();if(!state.room)return;
 const key=state.room.id,version=routeVersion;
 stream=new EventSource(`/api/rooms/${encodeURIComponent(key)}/events`);
 stream.onopen=()=>{if(version===routeVersion){state.connected=true;const el=$('.connection');if(el){el.classList.remove('off');el.innerHTML='<i class="online-dot on"></i>实时同步';}}};
 stream.addEventListener('change',()=>{if(version===routeVersion)void refresh(true);});
 stream.onerror=()=>{if(version===routeVersion){state.connected=false;const el=$('.connection');if(el){el.classList.add('off');el.textContent='连接中断 · 自动重连';}}};
}
async function route() {
 const version=++routeVersion;stream?.close();stream=null;clearInterval(displayTimer);
 state.connected=false;state.menu=false;state.voteSession=null;state.dirtyForms.clear();state.formRevisions={};
 const url=new URL(location.href),parts=url.pathname.split('/').filter(Boolean);
 try{
   if(parts[0]==='display'&&parts[1]){state.route='display';await showDisplay(parts[1],version);if(version===routeVersion)displayTimer=setInterval(()=>showDisplay(parts[1],version),8000);return;}
   if(!state.bootstrap){const bootstrap=await api('/api/bootstrap');if(version!==routeVersion)return;state.bootstrap=bootstrap;}
   if(version!==routeVersion)return;
   if(parts[0]==='new'){state.route='new';state.room=null;render();return;}
   if(parts[0]==='r'&&parts[1]){
     const code=parts[1];
     const tab=tabs.some(t=>t[0]===url.searchParams.get('view'))?url.searchParams.get('view'):'overview';
     const previousRoom=state.room?.id;
     let room;
     try{room=await api(`/api/rooms/${encodeURIComponent(code)}`);}catch(error){
       if(version!==routeVersion)return;
       if(error.status===403){state.route='join';state.code=code;state.room=null;render();return;}
       throw error;
     }
     if(version!==routeVersion)return;
     let messages=[],provider=null;
     if(room.me.status==='approved'){
       [messages,provider]=await Promise.all([
         api(`/api/rooms/${encodeURIComponent(room.id)}/messages`),
         room.host_id===room.me.id?api(`/api/rooms/${encodeURIComponent(room.id)}/provider`):Promise.resolve(null)
       ]);
     }
     if(version!==routeVersion)return;
     state.code=code;state.tab=tab;state.room=room;state.route='room';state.messages=messages;state.provider=provider;state.hasOlder=messages.length===50;
     if(previousRoom!==room.id){state.simFairness=null;state.chatMode='private';state.prefDraft=loadDraft(draftKey());}
     state.chatRaw=loadDraft(chatKey())||'';
     render();connect();return;
   }
   const rooms=await api('/api/rooms');if(version!==routeVersion)return;
   state.route='home';state.room=null;state.rooms=rooms;render();
 }catch(error){if(version!==routeVersion)return;$('#app').innerHTML=`<div class="waiting">${logo}<div class="card">${empty('暂时没有打开这个空间',error.message,'<a href="/" data-nav class="button secondary">返回首页</a>')}</div></div>`;}
}
function navigate(url) {history.pushState({},'',url);void route();window.scrollTo(0,0);}
async function mutate(action,payload={},revision=null) {
 const current=state.room.id,version=routeVersion;
 try{
   const r=await post(roomPath('/actions'),{revision:revision??state.room.revision,action,payload});
   if(state.room?.id===current&&version===routeVersion){state.room={...r,ai_pending:state.room.ai_pending};state.dirtyForms.clear();state.formRevisions={};render();await refresh(false);}
   return r;
 }catch(error){if(error.status===409&&version===routeVersion)await refresh(true);throw error;}
}
const csv=value=>value.split(/[,，\n]/).map(s=>s.trim()).filter(Boolean);
function readPreference(form) {
 const d=formData(form),categories={};for(const [k,v]of Object.entries(d))if(k.startsWith('category:')&&v!=='')categories[k.slice(9)]=Number(v);
 return {budget_max:number(d.budget_max),available_start:minutes(d.available_start),available_end:minutes(d.available_end),excluded_categories:csv(d.excluded_categories),allowed_locations:csv(d.allowed_locations),max_duration:number(d.max_duration),budget_target:number(d.budget_target),budget_weight:number(d.budget_weight),preferred_start:minutes(d.preferred_start),preferred_end:minutes(d.preferred_end),time_weight:number(d.time_weight),categories,activity_weight:number(d.activity_weight),other:d.other,unresolved:d.unresolved.split('\n').map(s=>s.trim()).filter(Boolean)};
}
function readRules(d,defaults={}) {return {...defaults,threshold:Number(d.threshold)/100,fairness:Number(d.fairness)/100,max_members:Number(d.max_members),max_rounds:Number(d.max_rounds),vote_seconds:Number(d.vote_seconds),...(d.max_activities?{max_activities:Number(d.max_activities),transfer_minutes:Number(d.transfer_minutes),transfer_cost:Number(d.transfer_cost)}:{})};}
function readScenario(d) {return {title:d.title.trim(),city:d.city.trim(),date:d.date,description:d.description,reference_budget:number(d.reference_budget)};}
async function resourceDialog(resource={}) {state.resourceRevision=state.room.revision;dialog(resource.id?'编辑候选活动':'添加一个候选活动',resourceForm(resource));}
async function modelDialog() {
 const data=await post(roomPath('/provider/models'));
 dialog('选择模型',`<p class="hint" style="margin-bottom:18px">点击填入房间专用接口表单，然后保存。全局供应商的模型由管理员设置。</p><div class="model-list">${data.models.map(m=>`<button class="button secondary small" data-action="choose-model" data-model="${esc(m)}">${esc(m)}</button>`).join('')||'<p class="muted">没有返回模型，可手动填写。</p>'}</div>`);
}
const handlers={
 'menu':()=>{state.menu=!state.menu;$('.sidebar')?.classList.toggle('open',state.menu);},
 'refresh':()=>refresh(true),
 'invite':()=>{const base=state.bootstrap.public_url||location.origin;const url=`${base}/r/${state.room.code}`;dialog('让伙伴一起加入',`<p class="muted">分享这个链接或房间码。申请加入后，需要房主批准。</p><div class="room-code">${esc(state.room.code)}</div><input class="copy-input" readonly value="${esc(url)}"><img class="qr" src="${roomPath('/invite.svg')}" alt="房间邀请二维码"><div class="actions"><button class="button" data-action="copy-invite">${icon('link',15)} 复制邀请链接</button></div>`);},
 'copy-invite':()=>copy(`${state.bootstrap.public_url||location.origin}/r/${state.room.code}`),
 'approve':el=>mutate('approve',{member_id:el.dataset.id}),
 'reject_join':el=>mutate('reject_join',{member_id:el.dataset.id}),
 'analyze':()=>mutate('analyze'),
 'select':el=>mutate('select',{proposal_id:el.dataset.id}).then(()=>toast('已选择待投票方案')),
 'start_vote':()=>confirmAction('发起正式投票','本轮将固定成员、条件、方案和截止时间。正式规则从此冻结，所有人对同一版本表达意见。',async()=>{await mutate('start_vote');navigate(`/r/${state.room.code}?view=vote`);}),
 'cancel_vote':()=>confirmAction('取消这一轮投票','已投票记录会保留，但不会继承到下一轮。成员可以重新协商后再投票。',()=>mutate('cancel_vote')),
 'withdraw':()=>confirmAction('退出本次决策','这会结束你的本次成员资格。如果正在投票，本轮会取消并重新计算；当前浏览器不能再次申请本房间。',()=>mutate('withdraw')),
 'negotiate':()=>mutate('negotiate').then(()=>toast('已检查你的条件与可选调整')),
 'accept-request':el=>confirmAction('同意修改自己的条件','此操作会产生新的个人条件版本，并重新检查全体方案。',()=>mutate('answer_request',{request_id:el.dataset.id,decision:'accept'})),
 'reject-request':el=>mutate('answer_request',{request_id:el.dataset.id,decision:'reject'}),
 'edit-request':el=>{const q=state.room.requests.find(q=>q.id===el.dataset.id);state.editRequest=q;dialog('调整后，由你确认',`<p class="hint">字段：${esc(q.field)}。时间输入一天内分钟数，类别或地点列表输入 JSON 数组，预算与时长填数值。</p><form id="edit-request-form" class="stack" style="margin-top:18px">${field('你愿意接受的新值','value',JSON.stringify(q.after),'text','required')}<button type="submit" class="button">按这个值确认修改</button></form>`);},
 'chat-mode':el=>{state.chatMode=el.dataset.mode;state.chatRaw=loadDraft(chatKey())||'';state.dirtyForms.delete('chat-form');render(true);},
 'older-messages':async()=>{if(!state.messages.length)return;const rows=await api(roomPath(`/messages?before=${state.messages[0].id}`));state.messages=[...rows,...state.messages].slice(-300);state.hasOlder=rows.length===50&&state.messages.length<300;render(true);},
 'apply-draft':el=>{const row=state.messages.find(m=>m.id===Number(el.dataset.id));if(!row?.metadata.draft)return;if(row.metadata.preference_version!==state.room.me.preference_version)throw new Error('这份 AI 草稿基于旧版个人条件，请重新提取或手动调整');state.prefDraft={preference:row.metadata.draft,preference_version:row.metadata.preference_version};saveDraft(draftKey(),state.prefDraft);state.dirtyForms.delete('preference-form');if(state.tab==='preferences')render(false);else navigate(`/r/${state.room.code}?view=preferences`);toast('草稿已填入，请逐项核对再确认');},
 'discard-pref':()=>{state.prefDraft=null;deleteDraft(draftKey());state.dirtyForms.delete('preference-form');render(false);},
 'add-resource':()=>resourceDialog(),
 'edit-resource':el=>resourceDialog(state.room.resources.find(r=>r.id===el.dataset.id)),
 'delete-resource':el=>confirmAction('移除这个候选活动','相关候选方案会失效，并按最新资源重新分析。',()=>mutate('resources',{resources:state.room.resources.filter(r=>r.id!==el.dataset.id)})),
 'discover-models':()=>modelDialog(),
 'choose-model':el=>{const form=$('#room-provider');if(form.elements.mode.value!=='custom')throw new Error('请先选择房间专用接口；全局供应商由管理员管理');form.elements.model.value=el.dataset.model;state.dirtyForms.add('room-provider');state.formRevisions['room-provider']??=state.room.revision;$('#dialog').close();toast('模型已填入，请保存接口配置');},
 'display':()=>window.open(`/display/${encodeURIComponent(state.room.share_token)}`,'_blank','noopener'),
 'print':()=>window.print(),
 'finish':()=>dialog('结束并留下记录',`<form id="finish-form" class="stack">${select('结束原因','outcome','CANCELLED',[['CANCELLED','主动结束本次决策'],['NO_CONSENSUS','有方案，但未形成共识'],['NO_FEASIBLE_PROPOSAL','当前范围内没有可行方案'],['INSUFFICIENT_DATA','信息不足，无法判断']])}${textarea('给这次讨论留一句说明','explanation','','rows="3" maxlength="1000" required')}<button type="submit" class="button danger">确认结束</button></form>`),
};

async function submit(form) {
 const d=formData(form);
 switch(form.id){
  case 'join-home':case 'join-direct':{
   let code=form.id==='join-home'?d.code.trim():state.code;
   if(code.includes('/r/'))code=code.split('/r/')[1].split(/[?#/]/)[0];
   const room=await post(`/api/join/${encodeURIComponent(code)}`,{username:d.username});navigate(`/r/${room.code}`);break;
  }
  case 'scenario-ai':{
   state.creationDraft.raw=d.text;saveDraft('wd-create',state.creationDraft);
   const result=await post('/api/scenario',{text:d.text,kind:'scenario'});state.creationDraft={...state.creationDraft,...result};saveDraft('wd-create',state.creationDraft);state.dirtyForms.clear();render();toast(result.text);break;
  }
  case 'create-room':{
   const room=await post('/api/rooms',{username:d.username,scenario:readScenario(d),rules:readRules(d),demo:form.elements.demo.checked});
   if(state.creationDraft.resources?.length&&!form.elements.demo.checked){
    try{await post(`/api/rooms/${room.id}/actions`,{revision:room.revision,action:'resources',payload:{resources:state.creationDraft.resources}});}catch(error){toast(`房间已创建，候选草稿未保存：${error.message}`,true);}
   }
   deleteDraft('wd-create');state.creationDraft={};navigate(`/r/${room.code}`);break;
  }
  case 'preference-form':{
   const preference=readPreference(form);
   await mutate('preference',{preference,preference_version:state.prefDraft?.preference_version??state.room.me.preference_version});
   state.prefDraft=null;deleteDraft(draftKey());render();toast('你的条件已确认，已保存新的个人版本');break;
  }
  case 'chat-form':{
   const text=d.text.trim();if(!text)throw new Error('请先写下你的想法');
   if(state.chatMode==='shared')await post(roomPath('/messages'),{text,kind:'chat'});
   else{await post(roomPath('/ai'),{text,kind:d.kind});state.room.ai_pending=true;}
   state.chatRaw='';deleteDraft(chatKey());state.dirtyForms.delete('chat-form');form.reset();await refresh(false);break;
  }
  case 'feedback-form':await mutate('feedback',{text:d.text,summary:d.summary,proposal_id:d.proposal_id||null});toast('反馈已保存');break;
  case 'vote-form':{
   const session=state.voteSession??state.room.vote.id;
   await mutate('vote',{session_id:session,choice:d.choice,reason:d.reason});toast('本轮投票已提交');break;
  }
  case 'attendance-form':await mutate('attendance',{value:d.value});toast('参与意愿已更新');break;
  case 'edit-request-form':{
   let value;try{value=JSON.parse(d.value);}catch{throw new Error('请输入数字、null 或 JSON 数组，例如 ["户外"]');}
   await mutate('answer_request',{request_id:state.editRequest.id,decision:'accept',value});$('#dialog').close();break;
  }
  case 'resource-form':{
   const resource={id:d.id,name:d.name.trim(),category:d.category.trim(),location:d.location.trim(),cost:number(d.cost),cost_upper:number(d.cost_upper),fixed_cost:number(d.fixed_cost),start:minutes(d.start),end:minutes(d.end),duration:number(d.duration),source:d.source,source_url:d.source_url.trim(),confirmed:form.elements.confirmed.checked,verified:form.elements.verified.checked};
   const resources=d.id?state.room.resources.map(r=>r.id===d.id?resource:r):[...state.room.resources,resource];
   await mutate('resources',{resources},state.resourceRevision);$('#dialog').close();toast('候选活动已保存');break;
  }
  case 'room-settings':await mutate('settings',{scenario:readScenario(d),rules:readRules(d,state.room.rules)},state.formRevisions[form.id]);toast('场景与规则已更新');break;
  case 'room-provider':{
   await api(roomPath('/provider'),{method:'PUT',body:{revision:state.formRevisions[form.id]??state.room.revision,provider_id:d.provider_id,provider:d.mode==='custom'?readProvider(form):null}});
   state.provider=null;state.dirtyForms.delete(form.id);delete state.formRevisions[form.id];await refresh(false);toast('接口配置已保存');break;
  }
  case 'finish-form':await mutate('finish',{outcome:d.outcome,explanation:d.explanation});$('#dialog').close();navigate(`/r/${state.room.code}?view=result`);break;
 }
}

document.addEventListener('click',async event=>{
 const nav=event.target.closest('a[data-nav]');if(nav&&!event.metaKey&&!event.ctrlKey&&!event.shiftKey){event.preventDefault();navigate(nav.href);return;}
 const speech=event.target.closest('[data-speech]');if(speech){startSpeech(speech.dataset.speech,speech);return;}
 const el=event.target.closest('[data-action]');if(!el||el.disabled)return;
 const handler=handlers[el.dataset.action];if(!handler)return;
 event.preventDefault();el.disabled=true;
 try{await handler(el);}catch(error){toast(error.message,true);}finally{el.disabled=false;}
});
document.addEventListener('submit',async event=>{
 if(!(event.target instanceof HTMLFormElement))return;event.preventDefault();
 const button=event.submitter,old=button?.innerHTML;if(button){button.disabled=true;button.innerHTML='<span class="spinner"></span> 正在处理';}
 try{await submit(event.target);}catch(error){toast(error.message,true);}finally{if(button){button.disabled=false;button.innerHTML=old;}}
});
document.addEventListener('input',event=>{
 const form=event.target.form;if(!form)return;
 state.dirtyForms.add(form.id);
 if(state.room)state.formRevisions[form.id]??=state.room.revision;
 if(form.id==='preference-form'){
   state.prefDraft={preference:readPreference(form),preference_version:state.prefDraft?.preference_version??state.room.me.preference_version};saveDraft(draftKey(),state.prefDraft);
 }else if(form.id==='chat-form'){state.chatRaw=form.elements.text.value;saveDraft(chatKey(),state.chatRaw);}
 else if(form.id==='vote-form'){state.voteSession??=state.room.vote.id;}
 else if(form.id==='fairness-sim'){state.simFairness=Number(event.target.value)/100;$('#fairness-label').textContent=`${event.target.value}%`;}
 else if(form.id==='create-room'){const d=formData(form);state.creationDraft={...state.creationDraft,username:d.username,scenario:readScenario(d)};saveDraft('wd-create',state.creationDraft);}
 else if(form.id==='scenario-ai'){state.creationDraft.raw=event.target.value;saveDraft('wd-create',state.creationDraft);}
});
document.addEventListener('change',event=>{
 const form=event.target.form;
 if(form?.id==='room-provider'&&event.target.name==='mode')$('#custom-provider-fields').hidden=event.target.value!=='custom';
 if(form?.id==='fairness-sim')render(true);
});
window.addEventListener('popstate',()=>void route());
window.addEventListener('beforeunload',()=>stream?.close());
function countdown(){
 for(const el of $$('[data-deadline]')){
  const remaining=Math.max(0,Math.ceil(Number(el.dataset.deadline)-Date.now()/1000));
  const hours=Math.floor(remaining/3600),minutes=Math.floor(remaining%3600/60),seconds=remaining%60;
  el.textContent=`${String(hours).padStart(2,'0')}:${String(minutes).padStart(2,'0')}:${String(seconds).padStart(2,'0')}`;
  if(!remaining&&!deadlineRefresh){deadlineRefresh=true;void refresh(true).finally(()=>setTimeout(()=>{deadlineRefresh=false;},5000));}
 }
}
setInterval(countdown,1000);
setInterval(()=>{if(state.route==='room'&&!state.connected)void refresh(true);},10000);
async function showDisplay(token,version){
 try{const d=await api(`/api/display/${encodeURIComponent(token)}`);if(version!==routeVersion)return;$('#app').innerHTML=`<main id="main" class="showcase"><div class="between">${logo}<span class="badge">只读投屏 · 自动更新</span></div><h1>${esc(d.scenario.title)}</h1><p class="muted">${esc(d.scenario.city)} · ${esc(d.scenario.date)} · ${labels[d.state]||d.state}</p><div class="three-columns"><div class="card metric"><div class="metric-label">有效参与</div><div class="metric-value">${d.member_count} 人</div></div><div class="card metric"><div class="metric-label">已确认需求</div><div class="metric-value">${d.ready_count} 人</div></div><div class="card metric"><div class="metric-label">正式投票轮次</div><div class="metric-value">${d.vote?.round||d.round||'—'}</div></div></div><div class="proposal-grid">${d.proposals.map(p=>`<div class="card proposal"><h2>${esc(p.title)}</h2><div class="proposal-score"><strong>${score(p.evaluation.score)}</strong><small>群体预测分 · 覆盖 ${p.evaluation.coverage.join('/')}</small></div>${badge(p.evaluation.status)}<p class="hint" style="margin-top:18px">${money(p.evaluation.cost)} / 人 · ${time(p.evaluation.start)} – ${time(p.evaluation.end)}</p></div>`).join('')}</div>${d.vote?`<div class="card" style="margin-top:25px"><div class="between"><h2>投票进度 ${d.vote.submitted} / ${d.vote.total}</h2>${badge(d.vote.status)}</div><p class="hint" style="margin-top:10px">至少 ${d.vote.required} 人明确接受 · 截止 ${dateTime(d.vote.deadline)}</p></div>`:''}<p class="hint" style="margin-top:30px">投屏只展示汇总信息，不展示成员的私密条件、消息与理由。</p></main>`;}catch(error){if(version===routeVersion)$('#app').innerHTML=`<div class="waiting">${empty('投屏暂不可用',error.message)}</div>`;}}
void route();
