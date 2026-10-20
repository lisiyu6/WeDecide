import {defaultDecisionView} from './flow.js';
import {buildCreationScenario} from './creation.js';
import {$,$$,setText,esc,logo,icon,api,post,toast,dialog,confirmAction,copy,formData,formId,number,minutes,time,field,textarea,select,badge,labels,terminal,empty,saveDraft,loadDraft,deleteDraft,startSpeech,captureInputs,restoreInputs,dateTime,money,score,themeControl} from './common.js';
import {contextDrawer,mountContextDrawer,resolveDate} from './context.js';
import {manualPlanForm} from './decision.js';
import {home,creation,joinPage,waiting,accountPage} from './pages.js';
import {layout,tabs,resourceForm} from './room-views.js';
import {readProvider,installProviderModels,renderProviderModels} from './provider.js';
import {readPreference,updatePreferenceFeedback,mountPreferenceEditor,goToPreferenceStep,latestInterview,interviewDraft} from './preferences.js';

const state={zen:loadDraft('wd-zen')??true,focusProposal:null,bootstrap:null,room:null,rooms:[],tab:'overview',route:'home',code:'',messages:[],hasOlder:false,provider:null,connected:false,chatMode:'private',chatRaw:'',interviewRaw:'',prefDraft:null,simFairness:null,menu:false,contextOpen:false,contextSide:'right',suggestionDraft:null,contextTab:'supplements',contextDraft:null,knowledgeDraft:null,creationDraft:loadDraft('wd-create')||{},dirtyForms:new Set(),formRevisions:{},savingPreferences:new Set()};
let stream=null,deletingRoom=null,routeVersion=0,refreshing=false,refreshAgain=false,deadlineRefresh=false,displayTimer=null;
const roomPath=suffix=>`/api/rooms/${encodeURIComponent(state.room.id)}${suffix}`;
const draftKey=()=>`wd-pref:${state.room.id}:${state.room.me.id}`;
const chatKey=()=>`wd-chat:${state.room.id}:${state.room.me.id}:${state.chatMode}`;
function leaveDeletedRoom(room,message='房主已删除这个空间，已返回首页') {
 deleteDraft(`wd-pref:${room.id}:${room.me.id}`);
 deleteDraft(`wd-context:${room.id}:${room.me.id}`);deleteDraft(`wd-knowledge:${room.id}:${room.me.id}`);deleteDraft(`wd-suggestion:${room.id}:${room.me.id}`);deleteDraft(`wd-interview:${room.id}:${room.me.id}`);
 for(const mode of ['private','shared'])deleteDraft(`wd-chat:${room.id}:${room.me.id}:${mode}`);
 if(state.room?.id!==room.id)return;
 stream?.close();stream=null;
 $('#dialog')?.close();state.room=null;state.messages=[];state.prefDraft=null;state.provider=null;state.chatRaw='';
 navigate('/');toast(message);
}
function deleteCurrentRoom() {
 const room=state.room,version=routeVersion;
 confirmAction(`删除「${room.scenario.title}」？`,'这个空间的全部成员、消息、需求、方案、投票记录和专用接口配置将永久删除。删除后，所有成员都会离开这个空间。',async()=>{
   if(version!==routeVersion||state.room?.id!==room.id)throw new Error('页面已切换，请重新打开删除窗口');
   deletingRoom=room.id;stream?.close();stream=null;
   try{
     await api(`/api/rooms/${encodeURIComponent(room.id)}?revision=${room.revision}`,{method:'DELETE'});
   }catch(error){
     deletingRoom=null;
     if(version===routeVersion){await refresh(true);if(state.room?.id===room.id)connect();}
     if(error.status===409)$('#dialog')?.close();
     throw error;
   }finally{if(deletingRoom===room.id)deletingRoom=null;}
   leaveDeletedRoom(room,'决策空间已删除');
 },{danger:true,confirmLabel:'确认删除空间'});
}
function accountNext(value='/'){try{const url=new URL(value,location.origin);return url.origin===location.origin&&!['/login','/admin'].includes(url.pathname)?url.pathname+url.search:'/';}catch{return '/';}}
function showAccount(next,mode=null){state.route='auth';state.room=null;state.authNext=accountNext(next);state.authMode=mode||(state.bootstrap.has_legacy_rooms?'register':'login');render();}
function render(preserve=false) {
 const root=$('#app');
 const saved=preserve?captureInputs(root):null,contextScroll=preserve?$('#context-drawer .context-drawer-body',root)?.scrollTop:0;
 const expanded=preserve?$$('details[data-proposal-detail][open]',root).map(el=>el.dataset.proposalDetail):[];
 const disclosures=preserve?$$('details[data-disclosure]',root).map(el=>({key:el.dataset.disclosure,open:el.open})):[];
 if(saved)saved.values=saved.values.filter(v=>state.dirtyForms.has(v.form)&&!(v.form==='preference-form'&&(terminal.has(state.room?.state)||state.room?.state==='VOTING')));
 if(state.route==='home')root.innerHTML=home(state.rooms,state.bootstrap);
 else if(state.route==='new')root.innerHTML=creation(state.bootstrap,state.creationDraft);
 else if(state.route==='join')root.innerHTML=joinPage(state.code,state.bootstrap);
 else if(state.route==='auth')root.innerHTML=accountPage(state.bootstrap,state.authMode,state.authNext);
 else if(state.route==='room')root.innerHTML=state.room.me.status==='approved'?layout(state)+contextDrawer(state):waiting(state.room);
 mountContextDrawer(root);
 for(const savedDetail of disclosures){const detail=$$('details[data-disclosure]',root).find(el=>el.dataset.disclosure===savedDetail.key);if(detail)detail.open=savedDetail.open;}
 if(saved)restoreInputs(root,saved);
 const contextBody=$('#context-drawer .context-drawer-body',root);if(contextBody&&contextScroll)contextBody.scrollTop=contextScroll;
 for(const id of expanded){const detail=$$('details[data-proposal-detail]',root).find(el=>el.dataset.proposalDetail===id);if(detail)detail.open=true;}
 const roomView=state.route==='room'&&state.room?.me.status==='approved'?$('#room-view',root):null;
 if(roomView&&state.tab==='settings')renderProviderModels(roomView);
 mountPreferenceEditor(state.tab==='preferences'?roomView:null,step=>{state.prefStep=step;if(state.prefDraft&&state.prefDraft.step!==step){state.prefDraft.step=step;saveDraft(draftKey(),state.prefDraft);}});
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
   const oldSnapshot=JSON.stringify([state.room,state.provider,state.messages]);
   if(state.room.me.status!=='approved'&&room.me.status==='approved')state.tab=defaultDecisionView(room);
   state.room=room;state.provider=provider;
   if(recent){
     const previous=state.messages.filter(m=>recent.length&&m.id<recent[0].id);
     state.messages=[...previous,...recent].slice(-300);
   }
   const interview=latestInterview(state);
   if(interview&&interview.id!==state.interviewSeenId){state.interviewSeenId=interview.id;if(state.tab==='preferences'&&interview.metadata.interview.ready)state.prefStep=1;}
   if(!preserve||oldSnapshot!==JSON.stringify([state.room,state.provider,state.messages]))render(preserve&&(state.tab!=='vote'||sameVote));
 }catch(error){
   if(version===routeVersion&&error.status===404){if(deletingRoom!==key)leaveDeletedRoom(state.room);}
   else if(version===routeVersion)toast(error.message,true);
 }finally{refreshing=false;if(refreshAgain){refreshAgain=false;void refresh(preserve);}}
}
function connect() {
 stream?.close();if(!state.room)return;
 const key=state.room.id,version=routeVersion;
 stream=new EventSource(`/api/rooms/${encodeURIComponent(key)}/events`);
 stream.onopen=()=>{if(version===routeVersion){state.connected=true;const el=$('.connection');if(el){el.classList.remove('off');el.innerHTML='<i class="online-dot on"></i>实时同步';}}};
 stream.addEventListener('change',()=>{if(version===routeVersion)void refresh(true);});
 stream.addEventListener('deleted',()=>{if(version===routeVersion&&deletingRoom!==key)leaveDeletedRoom(state.room);});
 stream.onerror=()=>{if(version===routeVersion){state.connected=false;const el=$('.connection');if(el){el.classList.add('off');el.textContent='连接中断 · 自动重连';}}};
}
async function route() {
 const version=++routeVersion;stream?.close();stream=null;clearInterval(displayTimer);
 state.connected=false;state.menu=false;state.contextOpen=false;document.body.classList.remove('context-open');state.voteSession=null;state.dirtyForms.clear();state.formRevisions={};
 const url=new URL(location.href),parts=url.pathname.split('/').filter(Boolean);
 try{
   if(parts[0]==='display'&&parts[1]){state.route='display';await showDisplay(parts[1],version);if(version===routeVersion)displayTimer=setInterval(()=>showDisplay(parts[1],version),8000);return;}
   if(!state.bootstrap){const bootstrap=await api('/api/bootstrap');if(version!==routeVersion)return;state.bootstrap=bootstrap;}
   if(version!==routeVersion)return;
   if(parts[0]==='login'){showAccount(url.searchParams.get('next')||'/',url.searchParams.get('mode')==='register'?'register':'login');return;}
   if(parts[0]==='new'){if(!state.bootstrap.account){showAccount('/new');return;}state.route='new';state.room=null;render();return;}
   if(parts[0]==='r'&&parts[1]){
     const code=parts[1];
     let tab=tabs.some(t=>t[0]===url.searchParams.get('view'))?url.searchParams.get('view'):null;
     const previousRoom=state.room?.id;
     let room;
     try{room=await api(`/api/rooms/${encodeURIComponent(code)}`);}catch(error){
       if(version!==routeVersion)return;
       if(error.status===401||error.status===403){if(!state.bootstrap.account){showAccount(url.pathname+url.search);return;}if(error.status===403){state.route='join';state.code=code;state.room=null;render();return;}}
       throw error;
     }
     if(version!==routeVersion)return;
     tab=tab||defaultDecisionView(room);
     let messages=[],provider=null;
     if(room.me.status==='approved'){
       [messages,provider]=await Promise.all([
         api(`/api/rooms/${encodeURIComponent(room.id)}/messages`),
         room.host_id===room.me.id?api(`/api/rooms/${encodeURIComponent(room.id)}/provider`):Promise.resolve(null)
       ]);
     }
     if(version!==routeVersion)return;
     state.code=code;state.tab=tab;state.room=room;state.route='room';state.messages=messages;state.provider=provider;state.hasOlder=messages.length===50;
     if(previousRoom!==room.id){state.prefAiOpen=false;state.simFairness=null;state.chatMode='private';state.prefDraft=loadDraft(draftKey());state.prefStep=state.prefDraft?.step??0;}
     state.interviewSeenId=latestInterview(state)?.id||0;if(tab==='preferences')state.prefStep=url.searchParams.get('stage')==='result'?1:0;
     state.chatRaw=loadDraft(chatKey())||'';state.interviewRaw=loadDraft(`wd-interview:${room.id}:${room.me.id}`)||'';state.contextDraft=loadDraft(`wd-context:${room.id}:${room.me.id}`)||{};state.suggestionDraft=loadDraft(`wd-suggestion:${room.id}:${room.me.id}`)||{};state.knowledgeDraft=loadDraft(`wd-knowledge:${room.id}:${room.me.id}`);
     render();connect();return;
   }
   const rooms=await api('/api/rooms');if(version!==routeVersion)return;
   state.route='home';state.room=null;state.rooms=rooms;render();
 }catch(error){
   if(version!==routeVersion)return;
   const roomLoaded=parts[0]==='r'&&state.room&&[state.room.id,state.room.code].includes(parts[1]);
   // Retain the created room and log the stack instead of making it look like a failed POST.
   console.error('WeDecide page navigation failed',error);
   mountPreferenceEditor(null,()=>{});state.route='error';
   const retry=`<a href="${esc(url.pathname+url.search)}" data-nav class="button">重新打开${roomLoaded?'这个空间':'页面'}</a>`;
   const message=roomLoaded&&!error.status?'空间已经保存，页面显示时出现问题。可以重新打开，无需再次创建。':error.message;
   $('#app').innerHTML=`<div class="waiting">${logo}<div class="card">${empty(roomLoaded?'空间页面暂时没有显示完整':'暂时没有打开这个空间',message,retry+'<a href="/" data-nav class="button secondary">返回首页</a>')}${roomLoaded?`<p class="hint">房间码 ${esc(state.room.code)}</p>`:''}<details class="advanced"><summary>错误详情</summary><p class="hint">${esc(error.message)}</p></details></div></div>`;
 }
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
function readRules(d,defaults={}) {return {...defaults,threshold:Number(d.threshold)/100,fairness:Number(d.fairness)/100,max_members:Number(d.max_members),max_rounds:Number(d.max_rounds),vote_seconds:Number(d.vote_seconds),...(d.max_activities?{min_activities:Number(d.min_activities||1),max_activities:Number(d.max_activities),transfer_minutes:Number(d.transfer_minutes),transfer_cost:Number(d.transfer_cost)}:{})};}
function readScenario(d) {return {title:d.title.trim(),city:d.city.trim(),date:d.date,description:d.description,reference_budget:number(d.reference_budget)};}
async function saveRoomContext(action,payload){
 const key=state.room.id,version=routeVersion;
 const room=await post(roomPath('/actions'),{revision:state.room.revision,action,payload});
 if(version!==routeVersion||state.room?.id!==key)return;
 state.room={...room,ai_pending:state.room.ai_pending};
 state.dirtyForms.delete(action==='knowledge'?'knowledge-form':payload.kind==='suggestion'?'suggestion-form':'supplement-form');
 if(action==='supplement'){if(payload.kind==='suggestion'){state.suggestionDraft={};deleteDraft(`wd-suggestion:${key}:${room.me.id}`);}else{state.contextDraft={};deleteDraft(`wd-context:${key}:${room.me.id}`);}}
 else{state.knowledgeDraft=null;deleteDraft(`wd-knowledge:${key}:${room.me.id}`);}
 render(true);await refresh(true);
}
async function resolveFormDate(form){
 const version=routeVersion,room=formId(form)==='room-settings'?state.room:null;
 const answer=await resolveDate(form,room,()=>version===routeVersion);
 if(version!==routeVersion)return;
 state.dirtyForms.add(formId(form));
 if(formId(form)==='create-room'){state.creationDraft.date_expression=form.elements.date_expression.value;state.creationDraft.manual={...state.creationDraft.manual,date:answer.date};saveDraft('wd-create',state.creationDraft);}
 return answer;
}
async function resourceDialog(resource={}) {state.resourceRevision=state.room.revision;dialog(resource.id?'核对备选方案':'补充备选方案',resourceForm(resource));}
installProviderModels(form=>{
 if(form.elements.mode.value!=='custom')throw new Error('请先选择房间专用接口，再填写端点与密钥');
 return post(roomPath('/provider/models'),{provider:readProvider(form)});
});
async function askInterview(text,interview_action='answer') {
 if(state.room.ai_pending)throw new Error('AI 正在处理你上一条回答，请稍候');
 const form=$('#preference-form'),draft=form?readPreference(form):interviewDraft(state);
 await post(roomPath('/ai'),{kind:'interview',text,draft,interview_action,request_id:crypto.randomUUID?.()||String(Date.now())});
 state.room.ai_pending=true;state.interviewRaw='';state.dirtyForms.delete('interview-form');deleteDraft(`wd-interview:${state.room.id}:${state.room.me.id}`);state.prefStep=0;render(true);
}
const handlers={
 'zen':()=>{state.zen=!state.zen;saveDraft('wd-zen',state.zen);render(true);},
 'focus-members':()=>{state.zen=false;render(true);},
 'focus-proposal':el=>{state.focusProposal=el.dataset.id;render(true);},
 'context-open':()=>{state.contextOpen=true;state.contextSide='right';render(true);},
 'suggestions-open':()=>{state.contextOpen=true;state.contextSide='left';render(true);},
 'organize-suggestions':async()=>{await post(roomPath('/ai'),{kind:'agent',text:'请先整合大家在左侧卡片公开提交的提议，合并相似方向，说明差异和资料缺口，提出可核对的候选草稿。未全员确认需求时先整理，不要伪造校核结果。'});await refresh(true);},
 'context-close':()=>{state.contextOpen=false;render(true);$(state.contextSide==='left'?'[data-action="suggestions-open"]':'[data-action="context-open"]')?.focus();},
 'context-tab':el=>{state.contextTab=el.dataset.tab;render(true);},
 'knowledge-discard':async()=>{state.knowledgeDraft=null;deleteDraft(`wd-knowledge:${state.room.id}:${state.room.me.id}`);state.dirtyForms.delete('knowledge-form');await refresh(true);render(true);},
 'context-to-preferences':()=>navigate(`/r/${state.room.code}?view=preferences&stage=result`),
 'resolve-date':el=>resolveFormDate(el.closest('form')),
 'menu':()=>{state.menu=!state.menu;$('.sidebar')?.classList.toggle('open',state.menu);const backdrop=$('.sidebar-backdrop');if(backdrop)backdrop.hidden=!state.menu;$('.mobile-menu')?.setAttribute('aria-expanded',String(state.menu));},
 'account-logout':async()=>{await post('/api/auth/logout');stream?.close();state.bootstrap=null;state.room=null;state.messages=[];state.prefDraft=null;state.creationDraft={};deleteDraft('wd-create');navigate('/');},
 'refresh':()=>refresh(true),
 'toggle-agent':el=>mutate('agent_toggle',{enabled:el.dataset.enabled==='true'}),
 'run-agent':async()=>{await post(roomPath('/ai'),{kind:'agent',text:'请结合本次共同目标、公开提议和全体已确认需求继续整理。已有可比候选时调用实际校核，解释群体取舍；仍有缺项时指出具体资料，不重复访谈成员。'});state.room.agent_pending=true;await refresh(true);},
 'apply-agent-draft':()=>mutate('agent_draft').then(()=>toast('已采纳为待核对候选；请在房间设置核对事实')),
 'plan-new':()=>{state.planRevision=state.room.revision;dialog('手动编排活动行程',manualPlanForm(state.room));},
 'plan-edit':el=>{state.planRevision=state.room.revision;dialog('编辑活动行程',manualPlanForm(state.room,state.room.manual_plans.find(p=>p.id===el.dataset.id)));},
 'plan-remove':el=>confirmAction('移除自定义行程','相关方案将按最新信息重新评价。',()=>mutate('plans',{plans:state.room.manual_plans.filter(p=>p.id!==el.dataset.id)})),

 'interview-answer':el=>{const turn=latestInterview(state)?.metadata.interview;if(!turn)throw new Error('问题已变化，请刷新后继续');const answer=el.dataset.choice==='skip'?'这项暂未确定，请不要替我设置条件':turn[el.dataset.choice];return askInterview(`针对问题「${turn.question}」，我的回答是：${answer}`);},
 'interview-next':()=>askInterview('请基于已知信息开始一轮简短卡片，只问会影响选择的关键差异；不要重复已有问题。','continue'),
 'interview-focus':()=>{const form=$('#interview-form');const detail=form?.closest('details');if(detail)detail.open=true;$('textarea',form)?.focus();},
 'interview-summary':()=>askInterview('请先把已有回答整合成需求表，保留未知项，停止继续追问。','finish'),
 'explain-comparison':async()=>{await post(roomPath('/ai'),{kind:'explain',text:'请详细比较当前有效方案，解释与我需求的匹配、复杂取舍、未量化要求和资料缺项，并给出下一步。'});state.room.ai_pending=true;render(true);},
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
 'apply-draft':el=>{const row=state.messages.find(m=>m.id===Number(el.dataset.id));if(!row?.metadata.draft)return;if(row.metadata.preference_version!==state.room.me.preference_version)throw new Error('这份 AI 草稿基于旧版个人条件，请重新提取或手动调整');state.prefStep=1;state.prefDraft={source_message_id:row.id,preference:row.metadata.draft,preference_version:row.metadata.preference_version,step:1};saveDraft(draftKey(),state.prefDraft);state.dirtyForms.delete('preference-form');if(state.tab==='preferences')render(false);else navigate(`/r/${state.room.code}?view=preferences`);toast('草稿已填入，请逐项核对再确认');},
 'discard-pref':()=>{state.prefDraft=null;deleteDraft(draftKey());state.dirtyForms.delete('preference-form');render(false);},
 'add-resource':()=>resourceDialog(),
 'edit-resource':el=>resourceDialog(state.room.resources.find(r=>r.id===el.dataset.id)),
 'delete-resource':el=>confirmAction('移除这个候选活动','相关候选方案会失效，并按最新资源重新分析。',()=>mutate('resources',{resources:state.room.resources.filter(r=>r.id!==el.dataset.id)})),
 'display':()=>window.open(`/display/${encodeURIComponent(state.room.share_token)}`,'_blank','noopener'),
 'print':()=>window.print(),
 'delete-room':()=>deleteCurrentRoom(),
 'finish':()=>dialog('结束并留下记录',`<form id="finish-form" class="stack">${select('结束原因','outcome','CANCELLED',[['CANCELLED','主动结束本次决策'],['NO_CONSENSUS','有方案，但未形成共识'],['NO_FEASIBLE_PROPOSAL','当前范围内没有可行方案'],['INSUFFICIENT_DATA','信息不足，无法判断']])}${textarea('给这次讨论留一句说明','explanation','','rows="3" maxlength="1000" required')}<button type="submit" class="button danger">确认结束</button></form>`),
};

async function submit(form) {
 const d=formData(form);
 switch(formId(form)){
  case 'account-form':{
   const error=$('[data-account-error]',form);error.hidden=true;
   try{
    await post('/api/auth/'+form.dataset.mode,{username:d.username.trim(),password:d.password});
    state.bootstrap=await api('/api/bootstrap');state.room=null;state.messages=[];state.prefDraft=null;
    navigate(accountNext(state.authNext));
   }catch(problem){error.textContent=problem.message;error.hidden=false;}
   break;
  }
  case 'join-home':case 'join-direct':{
   let code=formId(form)==='join-home'?d.code.trim():state.code;
   if(code.includes('/r/'))code=code.split('/r/')[1].split(/[?#/]/)[0];
   if(!state.bootstrap.account){navigate('/login?next='+encodeURIComponent('/r/'+code));break;}
   const room=await post(`/api/join/${encodeURIComponent(code)}`,{username:d.username});navigate(`/r/${room.code}`);break;
  }
  case 'scenario-ai':{
   const raw=d.text.trim(),version=routeVersion;
   if(!raw)throw new Error('先说一下这次想决定什么。');
   state.creationDraft.raw=raw;state.creationDraft.error='';saveDraft('wd-create',state.creationDraft);
   try{
    const result=await post('/api/scenario',{text:raw,kind:'scenario'});
    if(version!==routeVersion)return;
    if(state.creationDraft.raw.trim()!==raw){toast('描述已经修改，请按最新想法重新整理。');return;}
    state.creationDraft={...state.creationDraft,...result,source:raw};saveDraft('wd-create',state.creationDraft);state.dirtyForms.clear();render(true);
   }catch(error){if(version!==routeVersion)return;state.creationDraft.error=error.message+'。原话已保留，可以直接创建空间。';saveDraft('wd-create',state.creationDraft);render(true);}
   break;
  }
  case 'create-room':{
   if(d.date_expression?.trim()&&form.elements.date.dataset.expression!==d.date_expression.trim()){const resolved=await resolveFormDate(form);if(!resolved)return;d.date=resolved.date;}
   const room=await post('/api/rooms',{username:d.username,scenario:buildCreationScenario(state.creationDraft),rules:readRules(d),demo:false});
   if(state.creationDraft.resources?.length&&state.creationDraft.source===state.creationDraft.raw){
    try{await post(`/api/rooms/${room.id}/actions`,{revision:room.revision,action:'resources',payload:{resources:state.creationDraft.resources}});}catch(error){toast(`房间已创建，候选草稿未保存：${error.message}`,true);}
   }
   deleteDraft('wd-create');state.creationDraft={};navigate(`/r/${room.code}`);break;
  }
  case 'plan-form':{const steps=[];for(let i=0;i<5;i++){if(d[`resource_${i}`]){const start=minutes(d[`start_${i}`]);if(start==null||start<0||start>=1440)throw new Error('请填写有效的活动开始时间');steps.push({resource_id:d[`resource_${i}`],start});}}const plan={id:d.id,title:d.title,description:d.description,steps};await mutate('plans',{plans:d.id?state.room.manual_plans.map(p=>p.id===d.id?plan:p):[...state.room.manual_plans,plan]},state.planRevision);$('#dialog').close();toast('已保存行程，将按全体最新条件重新评价');break;}
  case 'interview-form':await askInterview(d.text.trim()||'请开始了解我的想法，并自主判断最有价值的下一问。');break;
  case 'preference-form':{
   if(form.dataset.locked==='true'||form.dataset.saving==='true')return;
   const step=Number(form.dataset.prefStep||0);
   if(step!==1){goToPreferenceStep(1);return;}
   const feedback=updatePreferenceFeedback(form);
   if(!feedback.ready){goToPreferenceStep(1);return;}
   const preference=readPreference(form),roomId=state.room.id,key=draftKey(),draft=state.prefDraft;
   state.savingPreferences.add(roomId);form.dataset.saving='true';$('.pref-fields',form).disabled=true;updatePreferenceFeedback(form);
   try{
    await mutate('preference',{preference,preference_version:state.prefDraft?.preference_version??state.room.me.preference_version});
    if(state.room?.id===roomId&&state.prefDraft===draft){state.prefDraft=null;deleteDraft(key);}
    toast('你的条件已确认，已保存新的个人版本');
   }finally{
    state.savingPreferences.delete(roomId);if(state.room?.id===roomId)render(true);
   }
   break;
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
   const attributes={};for(const line of (d.attributes||'').split('\n').map(s=>s.trim()).filter(Boolean)){const match=line.match(/^(.+?)\s*[=：:]\s*(是|否|true|false|有|无)$/);if(!match)throw new Error('属性请按“名称=是”或“名称=否”填写，无法判断时留空');attributes[match[1].trim()]=['是','true','有'].includes(match[2]);}
   const resource={kind:d.kind||'activity',description:d.description||'',steps:(d.steps||'').split('\n').map(s=>s.trim()).filter(Boolean),attributes,id:d.id,name:d.name.trim(),category:d.category.trim(),location:d.location.trim(),cost:number(d.cost),cost_upper:number(d.cost_upper),fixed_cost:number(d.fixed_cost),start:minutes(d.start),end:minutes(d.end),duration:number(d.duration),source:d.source,source_url:d.source_url.trim(),confirmed:form.elements.confirmed.checked,verified:form.elements.verified.checked};
   const resources=d.id?state.room.resources.map(r=>r.id===d.id?resource:r):[...state.room.resources,resource];
   await mutate('resources',{resources},state.resourceRevision);$('#dialog').close();toast('备选方案已保存，会按全体最新条件继续整理');break;
  }
  case 'knowledge-form':await saveRoomContext('knowledge',{text:d.text,knowledge_version:Number(d.knowledge_version)});toast('前置知识已更新，将用于本次共同决策');break;
  case 'suggestion-form':await saveRoomContext('supplement',{kind:'suggestion',visibility:'shared',title:d.title,text:d.text});toast('提议已公开保存，将结合共同目标继续整理。');break;
  case 'supplement-form':await saveRoomContext('supplement',{title:d.title,text:d.text,visibility:d.visibility});toast(state.room.state==='VOTING'?'补充已记录，本轮投票不受影响':'补充已保存，将'+(d.visibility==='shared'?'用于共同决策':'整理为待确认的需求草稿'));break;
  case 'room-settings':if(d.date_expression?.trim()&&form.elements.date.dataset.expression!==d.date_expression.trim()){const resolved=await resolveFormDate(form);if(!resolved)return;d.date=resolved.date;}await mutate('settings',{scenario:readScenario(d),rules:readRules(d,state.room.rules)},state.formRevisions[formId(form)]);toast('场景与规则已更新');break;
  case 'room-provider':{
   await api(roomPath('/provider'),{method:'PUT',body:{revision:state.formRevisions[formId(form)]??state.room.revision,provider_id:d.provider_id,provider:d.mode==='custom'?readProvider(form):null}});
   state.provider=null;state.dirtyForms.delete(formId(form));delete state.formRevisions[formId(form)];await refresh(false);toast('接口配置已保存');break;
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
const pendingForms=new Set();
document.addEventListener('submit',async event=>{
 if(!(event.target instanceof HTMLFormElement))return;event.preventDefault();
 const pendingKey=`${state.room?.id||state.route}:${formId(event.target)}`;
 if(pendingForms.has(pendingKey))return;pendingForms.add(pendingKey);
 const button=event.submitter,old=button?.innerHTML;if(button){button.disabled=true;button.innerHTML='<span class="spinner"></span> 正在处理';}
 try{await submit(event.target);}catch(error){toast(error.message,true);}finally{pendingForms.delete(pendingKey);if(button){button.disabled=false;button.innerHTML=old;}if(formId(event.target)==='preference-form')updatePreferenceFeedback(event.target);}
});
document.addEventListener('input',event=>{
 const form=event.target.form;if(!form)return;
 if(event.target.name==='date'&&form.elements.date_expression){form.elements.date_expression.value='';delete event.target.dataset.expression;}
 state.dirtyForms.add(formId(form));
 if(state.room)state.formRevisions[formId(form)]??=state.room.revision;
 if(formId(form)==='preference-form'){
   state.prefDraft={source_message_id:state.prefDraft?.source_message_id??latestInterview(state)?.id??0,preference:readPreference(form),preference_version:state.prefDraft?.preference_version??state.room.me.preference_version,step:state.prefStep||0};saveDraft(draftKey(),state.prefDraft);
   const badge=$('[data-pref-badge]');if(badge){badge.textContent='草稿 · 待你确认';badge.classList.remove('good');}
 }else if(formId(form)==='interview-form'){state.interviewRaw=form.elements.text.value;saveDraft(`wd-interview:${state.room.id}:${state.room.me.id}`,state.interviewRaw);}
 else if(formId(form)==='chat-form'){state.chatRaw=form.elements.text.value;saveDraft(chatKey(),state.chatRaw);}
 else if(formId(form)==='vote-form'){state.voteSession??=state.room.vote.id;}
 else if(formId(form)==='fairness-sim'){state.simFairness=Number(event.target.value)/100;setText('#fairness-label',`${event.target.value}%`,form);}
 else if(formId(form)==='create-room'){
   const d=formData(form),name=event.target.name;
   state.creationDraft.username=d.username;state.creationDraft.date_expression=d.date_expression||'';
   state.creationDraft.settings={...state.creationDraft.settings,...Object.fromEntries(['max_members','threshold','fairness','max_rounds','vote_seconds'].map(key=>[key,d[key]]))};
   if(['title','description','city','date','reference_budget'].includes(name))state.creationDraft.manual={...state.creationDraft.manual,[name]:d[name]};
   saveDraft('wd-create',state.creationDraft);
 }
 else if(formId(form)==='knowledge-form'){state.knowledgeDraft={text:form.elements.text.value,knowledge_version:Number(form.elements.knowledge_version.value)};saveDraft(`wd-knowledge:${state.room.id}:${state.room.me.id}`,state.knowledgeDraft);}
 else if(formId(form)==='suggestion-form'){state.suggestionDraft=formData(form);saveDraft(`wd-suggestion:${state.room.id}:${state.room.me.id}`,state.suggestionDraft);}
 else if(formId(form)==='supplement-form'){state.contextDraft=formData(form);saveDraft(`wd-context:${state.room.id}:${state.room.me.id}`,state.contextDraft);}
 else if(formId(form)==='scenario-ai'){state.creationDraft.raw=event.target.value;state.creationDraft.error='';const review=$('[data-scenario-review]');if(review)review.hidden=state.creationDraft.source!==state.creationDraft.raw;const feedback=$('[data-creation-feedback]');if(feedback)feedback.hidden=true;saveDraft('wd-create',state.creationDraft);}
});
document.addEventListener('change',event=>{
 const form=event.target.form;
 if(formId(form)==='room-provider'&&event.target.name==='mode')$('#custom-provider-fields').hidden=event.target.value!=='custom';
 if(formId(form)==='fairness-sim')render(true);
 if(formId(form)==='resource-form'&&event.target.name==='kind'){$('[data-activity-fields]',form).hidden=event.target.value==='decision';}
});
document.addEventListener('toggle',event=>{if(event.target.id==='preference-ai')state.prefAiOpen=event.target.open;},true);
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&state.menu)handlers.menu();});
document.addEventListener('cancel',event=>{if(event.target.id==='context-drawer'){event.preventDefault();handlers['context-close']();}},true);
let contextSwipe=null;
document.addEventListener('pointerdown',event=>{
 if(event.button!==0||event.target.closest('input,textarea,select,button,a,[data-interview-card]'))return;
 if(state.route!=='room'||state.room?.me.status!=='approved')return;
 const close=state.contextOpen,side=close?state.contextSide:event.clientX<=24?'left':event.clientX>=innerWidth-24?'right':null;
 if(side&&(!close||event.target.closest('[data-context-handle]')))contextSwipe={x:event.clientX,y:event.clientY,close,side};
});
document.addEventListener('pointerup',event=>{
 if(!contextSwipe)return;const {x,y,close,side}=contextSwipe;contextSwipe=null;
 const dx=event.clientX-x,dy=event.clientY-y,direction=side==='left'?1:-1;
 if(Math.abs(dx)>60&&Math.abs(dx)>Math.abs(dy)*1.3&&dx*direction*(close?-1:1)>0)handlers[close?'context-close':side==='left'?'suggestions-open':'context-open']();
});
document.addEventListener('pointercancel',()=>{contextSwipe=null;});
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
 try{const d=await api(`/api/display/${encodeURIComponent(token)}`);if(version!==routeVersion)return;$('#app').innerHTML=`<main id="main" class="showcase"><div class="between">${logo}${themeControl}<span class="badge">只读投屏 · 自动更新</span></div><h1>${esc(d.scenario.title)}</h1><p class="muted">${esc(d.scenario.city)} · ${esc(d.scenario.date)} · ${labels[d.state]||d.state}</p><div class="three-columns"><div class="card metric"><div class="metric-label">有效参与</div><div class="metric-value">${d.member_count} 人</div></div><div class="card metric"><div class="metric-label">已确认需求</div><div class="metric-value">${d.ready_count} 人</div></div><div class="card metric"><div class="metric-label">正式投票轮次</div><div class="metric-value">${d.vote?.round||d.round||'—'}</div></div></div><div class="proposal-grid">${d.proposals.map(p=>`<div class="card proposal"><h2>${esc(p.title)}</h2><div class="proposal-score"><strong>${score(p.evaluation.score)}</strong><small>群体预测分 · 覆盖 ${p.evaluation.coverage.join('/')}</small></div>${badge(p.evaluation.status)}<p class="hint" style="margin-top:18px">${money(p.evaluation.cost)} / 人 · ${p.evaluation.kind==='decision'?'通用备选':time(p.evaluation.start)+' – '+time(p.evaluation.end)}</p></div>`).join('')}</div>${d.vote?`<div class="card" style="margin-top:25px"><div class="between"><h2>投票进度 ${d.vote.submitted} / ${d.vote.total}</h2>${badge(d.vote.status)}</div><p class="hint" style="margin-top:10px">至少 ${d.vote.required} 人明确接受 · 截止 ${dateTime(d.vote.deadline)}</p></div>`:''}<p class="hint" style="margin-top:30px">投屏只展示汇总信息，不展示成员的私密条件、消息与理由。</p></main>`;}catch(error){if(version===routeVersion)$('#app').innerHTML=`<div class="waiting">${empty('投屏暂不可用',error.message)}</div>`;}}
void route();

document.addEventListener('pointerdown',event=>{for(const menu of document.querySelectorAll('.focus-space-menu[open]'))if(!menu.contains(event.target))menu.open=false;});
