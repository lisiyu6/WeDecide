import {$,$$,esc,logo,icon,api,post,toast,dialog,confirmAction,field,textarea,select,badge,dateTime,formData,empty,captureInputs,restoreInputs} from './common.js';
import {providerFields,readProvider,installProviderModels,renderProviderModels,fetchProviderModels} from './provider.js';
let config=null,rooms=[],stats={},tab='limits',editing=null,editor=null;
function login(){config=null;editor=null;editing=null;$('#app').innerHTML=`<main class="admin-login">${logo}<section class="card"><div class="eyebrow" style="margin-bottom:9px">ADMINISTRATION</div><h1>管理员控制台</h1><p class="hint" style="margin-top:12px">使用在后端 CLI 设置的密码登录。</p><form id="admin-login">${field('管理员密码','password','','password','required autocomplete="current-password" maxlength="256"')}<button class="button" style="width:100%" type="submit">进入管理控制台 ${icon('arrow',15)}</button></form><p class="hint" style="margin-top:20px">初次使用：在后端运行<br><code>python -m wedecide.cli admin-password</code></p></section></main>`;}
function render(){
 const navigation=[['limits','运行与容量'],['providers','全局 AI 接口'],['prompts','上下文提示词'],['rooms','房间管理']];
 $('#app').innerHTML=`<div class="admin-wrap"><header class="admin-header">${logo}<span class="muted">Administration · 管理员控制台</span><button class="button secondary small" data-action="logout">退出登录</button></header><div class="page-header"><div class="eyebrow">KEEP THINGS RUNNING, SIMPLY</div><h1>让每一次讨论，有序发生。</h1><p>管理运行限制、默认 AI 接口与仅在后端注入的上下文。</p></div><nav class="admin-tabs">${navigation.map(([key,label])=>`<button class="button secondary ${tab===key?'active':''}" data-action="tab" data-tab="${key}">${label}</button>`).join('')}</nav><main id="main">${({limits,providers,prompts,roomManagement}[tab==='rooms'?'roomManagement':tab])()}</main></div>`;
 if(editing&&$('#admin-provider'))$('#admin-provider').elements.namedItem('id').readOnly=true;
 renderProviderModels($('#app'));
}
function limits(){return `<form id="admin-limits" class="card stack"><h2>保持轻量，留出余量</h2><p class="hint">限制实时生效。降低上限不会踢出已加入成员；超过新上限时阻止新增。默认配置以约 500 MB 内存目标设计，未经实测，不代表硬性内存保证。</p><div class="form-grid mobile-single">${field('同时开放房间上限','max_rooms',config.max_rooms,'number','required min="1" max="128"')}${field('单房间成员人数上限','max_members',config.max_members,'number','required min="1" max="64"')}${field('同时调用 AI 数量','ai_concurrency',config.ai_concurrency,'number','required min="1" max="16"')}${field('AI 请求总队列容量','ai_queue_limit',config.ai_queue_limit,'number','required min="1" max="128"')}${field('房间无操作自动关闭 / 小时','room_idle_hours',config.room_idle_hours,'number','required min="1" max="720"')}${field('结束后保留 / 天','retention_days',config.retention_days,'number','required min="1" max="365"')}</div><div class="notice">过期房间自动关闭，结束且超过保留期限的房间与消息自动删除。调整保留期会影响已有记录，请先导出需要保留的报告。</div><div><button class="button" type="submit">保存运行设置</button></div></form>`;}
function providers(){return `<div class="stack">${editor?providerEditor():''}<div class="card"><div class="card-title"><h2>可供所有房间选择的接口</h2><button type="button" class="button secondary small" data-action="add-provider">${icon('plus',14)} 添加供应商</button></div><p class="hint">支持任意第三方完整 HTTP(S) 端点。房主也可以设置只供自己房间使用的接口和密钥。密钥不回显，额外请求头值也会隐藏。</p>${config.providers.length?config.providers.map(p=>`<div class="provider-row"><div><strong>${esc(p.name)} ${badge(p.enabled?'approved':'',p.enabled?'启用':'停用')}</strong><small>${esc(p.model||'尚未填写模型')} · ${esc(p.protocol)} · ${p.has_key?'密钥已保存':'未设置密钥'}</small></div><div class="actions"><button class="button ghost small" data-action="provider-models" data-id="${esc(p.id)}">模型列表</button><button class="button secondary small" data-action="edit-provider" data-id="${esc(p.id)}">编辑</button><button class="button ghost small" data-action="delete-provider" data-id="${esc(p.id)}">移除</button></div></div>`).join(''):empty('还没有全局供应商','添加一个兼容接口后，成员就可以使用 AI 理解与协商。')}<form id="admin-default" class="inline-form" style="margin-top:22px">${select('默认供应商（用于新房间与场景创建）','default_provider',config.default_provider,[['','不启用默认接口'],...config.providers.filter(p=>p.enabled).map(p=>[p.id,`${p.name} · ${p.model}`])])}<button class="button secondary" type="submit">保存默认值</button></form></div><div class="notice">OpenAI 兼容端点示例：https://api.example.com/v1/chat/completions；Anthropic 协议可使用 x-api-key 请求头、空鉴权前缀。自定义 JSON 模板必须包含 $messages。</div></div>`;}
function prompts(){const names={context:['全局上下文','应用于每次 AI 调用，可填写组织背景、表达风格和共同约定。'],scenario:['场景构建','补充场景理解与资料来源要求。'],preferences:['个人需求提取','补充软硬约束的理解原则。'],chat:['个人 AI 对话','补充助手的交流风格与工作边界。'],negotiate:['协商建议','补充建议顺序与协商表达。']};return `<form id="admin-prompts" class="card stack"><h2>只在后端调用时注入</h2><div class="notice">这里的内容只通过管理员接口读写，不进入普通成员页面、房间快照或聊天记录。第三方模型调用时会作为系统上下文发送给你配置的供应商。请勿把密钥或其他秘密写进提示词，模型输出不能作为保密边界。</div>${Object.entries(names).map(([key,[label,description]])=>`<div>${textarea(label,key,config.prompts[key]||'','rows="5" maxlength="12000"')}<p class="hint" style="margin-top:6px">${description}</p></div>`).join('')}<div><button class="button" type="submit">保存隐藏上下文</button></div></form>`;}
function roomManagement(){return `<div class="stack"><div class="three-columns"><div class="card metric"><div class="metric-label">近期保留房间</div><div class="metric-value">${rooms.length}</div></div><div class="card metric"><div class="metric-label">正在调用 AI</div><div class="metric-value">${stats.ai_running||0}</div></div><div class="card metric"><div class="metric-label">AI 活跃与排队总数</div><div class="metric-value">${stats.ai_queued||0}</div></div></div><div class="card"><div class="card-title"><h2>房间运行状态</h2><button class="button secondary small" data-action="refresh-rooms">刷新</button></div><div class="table-wrap"><table><thead><tr><th>名称 / 房间码</th><th>阶段</th><th>成员</th><th>最近操作</th><th>操作</th></tr></thead><tbody>${rooms.map(r=>`<tr><td>${esc(r.title)}<small class="hint" style="display:block">${esc(r.code)}</small></td><td>${badge(r.state)}</td><td>${r.members}</td><td>${dateTime(r.updated)}</td><td>${['COLLECTING','COMPARING','NEGOTIATING','VOTING'].includes(r.state)?`<button class="button ghost small" data-action="close-room" data-id="${esc(r.id)}">关闭房间</button>`:'已冻结记录'}</td></tr>`).join('')||'<tr><td colspan="5">尚无房间</td></tr>'}</tbody></table></div><p class="hint" style="margin-top:18px">最多展示最近 200 个房间。管理列表只包含运行摘要，不提供成员私聊或个人条件。</p></div></div>`;}
async function loadRooms(){stats=await api('/api/admin/rooms');rooms=stats.rooms;}
async function save(patch,closeEditor=false){
 const draft=!closeEditor&&editor?captureInputs($('#app')):null;
 if(draft)draft.values=draft.values.filter(value=>value.form==='admin-provider');
 config=await api('/api/admin/settings',{method:'PUT',body:{revision:config.revision,...patch}});
 if(closeEditor){editor=null;editing=null;}
 render();
 if(draft){restoreInputs($('#app'),draft);renderProviderModels($('#app'));}
 toast('管理设置已保存');
}
function providerEditor(){
 return `<section class="card provider-editor"><div class="card-title"><h2>${editing?'编辑全局供应商':'添加全局供应商'}</h2><button type="button" class="button ghost small" data-action="cancel-provider">取消</button></div>
 <p class="hint" style="margin-bottom:20px">先填写请求端点和密钥，再点“拉取模型”。选好模型后保存，才会写入全局配置。</p>
 <form id="admin-provider" data-model-scope="admin:${esc(editor.id)}" data-saved-provider-id="${esc(editing||'')}">
 ${providerFields(editor)}<div class="actions" style="margin-top:22px"><button class="button" type="submit">保存供应商</button><button type="button" class="button secondary" data-action="cancel-provider">取消</button></div>
 </form></section>`;
}
function editProvider(provider){
 editing=provider?.id||null;
 editor=provider||{id:'provider-'+Date.now().toString(36),name:'新的 AI 接口'};
 render();
 const form=$('#admin-provider');
 if(editing)form.elements.namedItem('id').readOnly=true;
 form.scrollIntoView({behavior:'smooth',block:'start'});
 form.elements.namedItem('name').focus({preventScroll:true});
}
installProviderModels(form=>post('/api/admin/providers/models',{
 provider:readProvider(form),saved_provider_id:form.dataset.savedProviderId||null
}));
async function start(){try{config=await api('/api/admin/settings');await loadRooms();render();}catch(error){if(error.status!==401)toast(error.message,true);login();}}
document.addEventListener('click',async event=>{
 const el=event.target.closest('[data-action]');if(!el)return;el.disabled=true;
 try{switch(el.dataset.action){
  case 'tab':editor=null;editing=null;tab=el.dataset.tab;if(tab==='rooms')await loadRooms();render();break;
  case 'logout':await post('/api/admin/logout');login();break;
  case 'add-provider':if(!editor||editing)editProvider();else $('#admin-provider').scrollIntoView({behavior:'smooth',block:'start'});break;
  case 'cancel-provider':editor=null;editing=null;render();break;
  case 'edit-provider':editProvider(config.providers.find(p=>p.id===el.dataset.id));break;
  case 'delete-provider':await confirmAction('移除这个全局接口','使用该供应商的房间将无法继续通过它调用 AI，房间专用配置不受影响。',()=>save({providers:config.providers.filter(p=>p.id!==el.dataset.id),default_provider:config.default_provider===el.dataset.id?'':config.default_provider}));break;
  case 'provider-models':editProvider(config.providers.find(p=>p.id===el.dataset.id));await fetchProviderModels($('#admin-provider'));break;
  case 'refresh-rooms':await loadRooms();render();break;
  case 'close-room':await confirmAction('关闭这个房间','当前投票会被取消，房间保存为管理员关闭。此操作不会生成成功决定。',async()=>{await post(`/api/admin/rooms/${encodeURIComponent(el.dataset.id)}/close`);await loadRooms();render();});break;
 }}catch(error){toast(error.message,true);if(error.status===401)login();}finally{el.disabled=false;}
});
document.addEventListener('submit',async event=>{
 if(!(event.target instanceof HTMLFormElement))return;
 event.preventDefault();const form=event.target,d=formData(form),button=event.submitter;if(button)button.disabled=true;
 try{switch(form.id){
  case 'admin-login':await post('/api/admin/login',{password:d.password});await start();break;
  case 'admin-limits':await save(Object.fromEntries(Object.entries(d).map(([k,v])=>[k,Number(v)])));break;
  case 'admin-default':await save({default_provider:d.default_provider});break;
  case 'admin-prompts':await save({prompts:d});break;
  case 'admin-provider':{const p=readProvider(form);if(!editing&&config.providers.some(old=>old.id===p.id))throw new Error('供应商 ID 已存在，请使用不同的 ID');await save({providers:editing?config.providers.map(old=>old.id===editing?p:old):[...config.providers,p]},true);break;}
 }}catch(error){toast(error.message,true);if(error.status===401)login();}finally{if(button)button.disabled=false;}
});
void start();
