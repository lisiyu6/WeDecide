import {$,$$,setText,esc,icon,field,textarea,select,check,formData,formId,jsonField,number} from './common.js';

export function providerFields(provider={}) {
  return `<div data-provider-editor>
    <div class="form-grid">
      ${field('配置名称','name',provider.name || '房间专用接口','text','required maxlength="80"')}
      ${field('配置 ID','id',provider.id || 'custom','text','required pattern="(?:[A-Za-z0-9_]|-){1,48}"')}
      ${select('接口协议','protocol',provider.protocol || 'openai',[
        ['openai','OpenAI 兼容（Chat Completions）'],
        ['anthropic','Anthropic Messages'],
        ['custom','自定义 JSON HTTP']
      ])}
      ${field('模型名称（手动输入或从下方列表选择）','model',provider.model || '','text','placeholder="填写供应商提供的模型 ID" maxlength="200"')}
      ${field('API 地址（基址或完整请求 URL）','endpoint',provider.endpoint || '','url','class="mono" placeholder="https://api.example.com/v1/chat/completions" maxlength="2000"')}
      ${field(provider.has_key?'API 密钥（已保存，留空保留）':'API 密钥','api_key','','password','autocomplete="new-password" placeholder="只保存在服务端" maxlength="4096"')}
    </div>
    <div class="model-discovery">
      ${field('模型列表地址（可选，留空按请求端点推导）','models_endpoint',provider.models_endpoint || '','url','class="mono" placeholder="https://api.example.com/v1/models" maxlength="2000"')}
      <div class="actions" style="margin-top:12px">
        <button type="button" class="button secondary small" data-fetch-models>${icon('download',14)} 拉取模型</button>
        <span class="hint">可使用尚未保存的端点和密钥。</span>
      </div>
      <p class="hint model-status" data-model-status role="status" aria-live="polite"></p>
      <div class="model-picker" data-model-picker hidden>
        <label class="field"><span>筛选可用模型</span><input type="search" data-model-search placeholder="输入模型名称筛选…" autocomplete="off"></label>
        <label class="field"><span data-model-count>可用模型</span><select data-model-choice size="6" aria-label="选择模型"></select></label>
        <p class="hint">选择后会填入模型名称；保存供应商配置后生效。</p>
      </div>
    </div>
    <div class="inline-checks">
      ${check('启用此接口','enabled',provider.enabled !== false)}
      ${check('清除已保存密钥','clear_key',false)}
    </div>
    <details class="advanced">
      <summary>高级接口与请求配置</summary>
      <p class="hint">OpenAI 兼容接口支持根地址、/v1 基址或完整请求 URL；其他协议填写完整请求 URL。Anthropic 常用鉴权头为 x-api-key，前缀留空。额外请求头已有值不会返回浏览器，同名空值表示保留，删除键可移除。</p>
      <div class="form-grid">
        ${field('鉴权请求头','auth_header',provider.auth_header || 'Authorization')}
        ${field('鉴权前缀（含空格）','auth_prefix',provider.auth_prefix ?? 'Bearer ')}
        ${field('请求超时 / 秒','timeout',provider.timeout || 60,'number','min="5" max="180" required')}
        ${field('最大输出 token','max_tokens',provider.max_tokens || 2048,'number','min="128" max="8192" required')}
        ${field('温度','temperature',provider.temperature ?? .5,'number','min="0" max="2" step="0.1" required')}
        ${field('对话响应文本路径','response_path',provider.response_path || 'choices.0.message.content')}
        ${field('模型列表路径（顶层数组可留空）','models_path',provider.models_path ?? 'data','text','maxlength="200" placeholder="data 或 result.models"')}
        ${field('模型 ID 字段','model_id_field',provider.model_id_field || 'id','text','required maxlength="100" placeholder="id 或 name"')}
      </div>
      ${textarea('额外请求头 JSON','headers',JSON.stringify(provider.headers || {},null,2),'class="code-input" rows="3"')}
      ${textarea('额外请求参数 JSON','extra_body',JSON.stringify(provider.extra_body || {},null,2),'class="code-input" rows="3"')}
      ${textarea('自定义协议请求模板 JSON','request_template',JSON.stringify(provider.request_template || {},null,2),'class="code-input" rows="4"')}
      <p class="hint">自定义模板中的值可使用 "$messages"（必须）、"$conversation"、"$system"、"$model"、"$input"、"$max_tokens"、"$temperature"，均按完整值替换。例如 {"model":"$model","messages":"$messages"}。响应路径支持 data.answer 或 content.0.text。</p>
    </details>
  </div>`;
}

export function readProvider(form) {
  const d=formData(form);
  return {
    id:d.id,name:d.name,protocol:d.protocol,
    endpoint:d.endpoint.trim(),model:d.model.trim(),api_key:d.api_key,
    models_endpoint:d.models_endpoint.trim(),models_path:d.models_path.trim(),model_id_field:d.model_id_field.trim(),
    auth_header:d.auth_header,auth_prefix:d.auth_prefix,
    headers:jsonField(form,'headers'),extra_body:jsonField(form,'extra_body'),request_template:jsonField(form,'request_template'),
    response_path:d.response_path,timeout:number(d.timeout),max_tokens:number(d.max_tokens),temperature:number(d.temperature),
    enabled:form.elements.enabled.checked,clear_key:form.elements.clear_key.checked
  };
}

// Picker state contains only model IDs and status, never credentials. It survives
// the room's SSE rerenders and is bounded across recently opened provider forms.
const pickers=new Map();
let discover=null,installed=false;
const scope=form=>form.dataset.modelScope || formId(form);
const signature=form=>JSON.stringify(['protocol','endpoint','models_endpoint','models_path','model_id_field'].map(name=>form.elements.namedItem(name)?.value||''));
const currentForm=key=>$$('form[data-model-scope]').find(form=>scope(form)===key);
function picker(form) {
  const key=scope(form),fingerprint=signature(form);
  if(pickers.has(key)&&pickers.get(key).signature!==fingerprint)pickers.delete(key);
  if(!pickers.has(key)){
    if(pickers.size>=32)pickers.delete(pickers.keys().next().value);
    pickers.set(key,{models:[],filter:'',loading:false,fetched:false,error:'',signature:fingerprint});
  }
  return pickers.get(key);
}
function paintPicker(form) {
  if(!form?.querySelector('[data-provider-editor] [data-fetch-models]'))return;
  const state=picker(form),button=$('[data-fetch-models]',form);
  button.disabled=state.loading;
  button.innerHTML=state.loading?'<span class="spinner"></span> 正在拉取…':`${icon('download',14)} 拉取模型`;
  const status=setText('[data-model-status]',state.error || (state.loading?'正在从供应商读取模型列表…':state.fetched?state.models.length?`已获取 ${state.models.length} 个模型。`:'接口返回的模型列表为空，可手动填写模型名称。':''),form);
  status?.classList.toggle('model-error',Boolean(state.error));
  const panel=$('[data-model-picker]',form);
  if(!panel)return;
  panel.hidden=!state.models.length;
  if(panel.hidden)return;
  const search=$('[data-model-search]',form),options=$('[data-model-choice]',form);
  if(!search||!options)return;
  if(search.value!==state.filter)search.value=state.filter;
  const filtered=state.models.filter(id=>id.toLowerCase().includes(state.filter.toLowerCase()));
  setText('[data-model-count]',`可用模型 · ${filtered.length} / ${state.models.length}`,form);
  options.replaceChildren();
  for(const id of filtered){
    const option=document.createElement('option');option.value=id;option.textContent=id;options.append(option);
  }
  if(!filtered.length){
    const option=document.createElement('option');option.textContent='没有匹配的模型';option.disabled=true;options.append(option);
  }
  options.value=form.elements.model.value;
}
export function renderProviderModels(root=document) {
  for(const form of $$('form[data-model-scope]',root))paintPicker(form);
}
export async function fetchProviderModels(form) {
  if(!form || !discover)return;
  const state=picker(form),key=scope(form);
  if(state.loading)return;
  state.loading=true;state.error='';paintPicker(form);
  try{
    const result=await discover(form);
    if(pickers.get(key)!==state)return;
    if(!Array.isArray(result.models)||!result.models.every(id=>typeof id==='string'))throw new Error('服务器返回的模型列表格式不正确');
    state.models=[...new Set(result.models)];state.fetched=true;state.filter='';
  }catch(error){
    if(pickers.get(key)!==state)return;
    state.models=[];state.fetched=false;state.error=error.message || '模型拉取失败，请检查接口配置';
  }finally{
    state.loading=false;
    if(pickers.get(key)===state)paintPicker(currentForm(key));
  }
}
export function installProviderModels(fetcher) {
  discover=fetcher;
  if(installed)return;
  installed=true;
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-fetch-models]');
    if(!button || button.disabled)return;
    event.preventDefault();void fetchProviderModels(button.form);
  });
  document.addEventListener('input',event=>{
    const form=event.target.form;
    if(!form?.dataset.modelScope)return;
    if(event.target.matches('[data-model-search]')){
      picker(form).filter=event.target.value;paintPicker(form);return;
    }
    if(['endpoint','models_endpoint','models_path','model_id_field','api_key','auth_header','auth_prefix','headers','clear_key'].includes(event.target.name)){
      pickers.delete(scope(form));paintPicker(form);
    }
  });
  document.addEventListener('change',event=>{
    const form=event.target.form;
    if(!form?.dataset.modelScope)return;
    if(event.target.matches('[data-model-choice]')){
      const model=form.elements.model;
      if(!event.target.value)return;
      model.value=event.target.value;
      model.dispatchEvent(new Event('input',{bubbles:true}));
      model.dispatchEvent(new Event('change',{bubbles:true}));
    }else if(event.target.name==='protocol'){
      const header=form.elements.auth_header,prefix=form.elements.auth_prefix;
      if(event.target.value==='anthropic'&&header.value==='Authorization'&&prefix.value==='Bearer '){header.value='x-api-key';prefix.value='';}
      else if(event.target.value==='openai'&&header.value==='x-api-key'&&prefix.value===''){header.value='Authorization';prefix.value='Bearer ';}
      pickers.delete(scope(form));paintPicker(form);
    }
  });
}
