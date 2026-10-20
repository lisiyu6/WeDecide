import {esc} from './common.js';

// Request feedback survives component replacement and prevents duplicate writes.
const requests=new Map();
let failure='';
const savedButtons=new WeakMap();

function buttonsFor(item){
 if(item.form)return [...(document.getElementById(item.form)?.querySelectorAll('[type="submit"]')||[])];
 return [...document.querySelectorAll('[data-action]')].filter(node=>node.dataset.action===item.action&&(node.dataset.id||'')===item.id);
}

function paint(){
 const root=document.getElementById('action-feedback');
 if(!root)return;
 const latest=[...requests.values()].at(-1);
 root.hidden=!latest&&!failure;
 root.classList.toggle('has-error',Boolean(failure&&!latest));
 root.innerHTML=latest?`<span class="spinner" aria-hidden="true"></span><span>${esc(latest.label)}</span>`:failure?`<span>${esc(failure)}</span><button type="button" aria-label="关闭操作提示">关闭</button>`:'';
 root.querySelector('button')?.addEventListener('click',()=>{failure='';paint();});
}

export function syncFeedback(){
 for(const item of requests.values())for(const button of buttonsFor(item)){
  if(!savedButtons.has(button))savedButtons.set(button,{html:button.innerHTML,disabled:button.disabled});
  button.disabled=true;button.setAttribute('aria-busy','true');
  button.innerHTML=`<span class="spinner" aria-hidden="true"></span> ${esc(item.buttonLabel||'正在提交…')}`;
 }
 paint();
}

export async function withFeedback(key,element,label,operation){
 if(requests.has(key))return;
 failure='';
 const item={label,action:element?.dataset.action,id:element?.dataset.id||'',form:element?.tagName==='FORM'?element.id:null};
 requests.set(key,item);syncFeedback();
 try{return await operation();}
 catch(error){failure=error.message||'操作暂未完成，请重试。';return undefined;}
 finally{
  requests.delete(key);
  for(const button of buttonsFor(item)){
   const saved=savedButtons.get(button);
   if(saved){button.innerHTML=saved.html;button.disabled=saved.disabled;savedButtons.delete(button);}
   button.removeAttribute('aria-busy');
  }
  paint();
 }
}

export const actionMessages={
 'run-agent':'正在提交共同整理请求…', 'organize-suggestions':'正在提交提议整理请求…',
 'apply-agent-draft':'正在保存已核对的候选…', 'analyze':'正在校核全体已确认需求…',
 'interview-answer':'正在提交这张卡片的回答…', 'interview-next':'正在请求下一张卡片…',
 'interview-summary':'正在请求整理需求结果…', 'explain-comparison':'正在请求方案取舍说明…',
 'select':'正在保存待投票方案…', 'approve':'正在批准成员加入…', 'reject_join':'正在处理加入申请…',
 'accept-request':'正在确认你的条件调整…', 'reject-request':'正在保存你的选择…',
 'toggle-agent':'正在更新自动整理设置…', 'resolve-date':'正在换算日期…', 'refresh':'正在同步最新进展…',
 'account-logout':'正在退出账号…', 'older-messages':'正在读取更早记录…', 'negotiate':'正在检查可选调整…',
};

export const formMessages={
 'account-form':'正在验证账号…', 'create-room':'正在创建决策空间…',
 'scenario-ai':'正在把你的想法整理为共同目标…', 'preference-form':'正在确认你的需求并交给共同决策…',
 'interview-form':'正在提交你的想法…', 'interview-value-form':'正在提交这题的具体信息…',
 'suggestion-form':'正在保存公开提议…', 'supplement-form':'正在保存补充信息…',
 'knowledge-form':'正在保存前置知识…', 'agent-review-form':'正在保存核对结果并继续计算…',
 'vote-form':'正在提交本轮正式表态…', 'resource-form':'正在保存候选事实…',
 'room-provider':'正在保存房间接口…', 'room-settings':'正在保存房间规则…',
};
