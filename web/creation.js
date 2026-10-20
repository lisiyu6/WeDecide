import {number} from './common.js';
export function creationValues(draft={}){
 const current=draft.source==null||draft.source===draft.raw;
 return {...(current?draft.scenario||{}:{}),...draft.manual};
}
export function buildCreationScenario(draft={}){
 const s=creationValues(draft),raw=(draft.raw||'').trim(),title=(s.title||'').trim()||raw.split('\n')[0].slice(0,60);
 if(!title)throw new Error('先说说这次想一起决定什么，或者填写决策名称。');
 const extra=(s.description||'').trim();
 const description=raw&&!extra.includes(raw)?[raw,extra].filter(Boolean).join('\n\n'):extra||raw;
 if(description.length>2000)throw new Error('想法和补充说明合计最多 2000 字，请精简后创建。');
 return {title,description,city:(s.city||'').trim(),date:s.date||'',reference_budget:number(s.reference_budget)};
}
