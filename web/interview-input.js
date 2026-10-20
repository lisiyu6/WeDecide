/* Agent-selected input branches. Opening one is local; only actual values reply. */
export function latestInterview(state){if(!state.room?.me)return undefined;return [...state.messages].reverse().find(row=>row.role==='assistant'&&row.kind==='interview'&&row.metadata.interview&&row.metadata.preference_version===state.room.me.preference_version);}
const numeric={budget_max:['人均费用上限','元/人',0,1000000,.01],budget_target:['理想人均费用','元/人',0,1000000,.01],max_duration:['最长总时长','分钟',15,1440,1],budget_weight:['费用重要程度','',1,5,1],time_weight:['时间重要程度','',1,5,1],activity_weight:['类别重要程度','',1,5,1]};
const clocks={available_start:'最早能参加的时间',available_end:'最晚需要结束的时间',preferred_start:'希望开始的时间',preferred_end:'希望结束的时间'};
export function branchInputSpec(turn,choice){
 const q=turn?.metadata.interview;if(!q||q.ready||!['left','right'].includes(choice))return null;
 // New cards are dispatched by the server. Legacy cards asking the member to
 // write something must also open a control instead of submitting a promise.
 if(q.input_cards?.[choice])return q.input_cards[choice];
 const call=q.tool_calls?.find(c=>c.tool==='request_input'&&c.choice===choice);
 const label=q[choice]||'';
 if(!call&&(/暂|待定|之后|再补|跳过|不填写|不输入/.test(label)||!/(填写|输入|补充具体|我.{0,6}(补充|说明|写下|提供))/.test(label)))return null;
 const field=call?.field||(q.targets?.length===1?q.targets[0]:'');
 if(numeric[field]){const [name,unit,min,max,step]=numeric[field];return {kind:'number',field,label:call?.label||name,unit,min,max,step,placeholder:call?.placeholder||''};}
 if(clocks[field])return {kind:'time',field,label:call?.label||clocks[field],unit:'',allow_midnight_end:field.endsWith('end'),placeholder:call?.placeholder||''};
 return {kind:'text',field,label:call?.label||'补充你的具体想法',unit:'',max_length:1000,placeholder:call?.placeholder||''};
}
function sameSource(state,input,turn){return Boolean(input&&turn&&input.source_message_id===turn.id&&input.preference_version===state.room.me.preference_version&&input.room_id===state.room.id&&input.member_id===state.room.me.id);}
export function currentInterviewInput(state){
 const input=state.interviewInput,turn=latestInterview(state);
 if(!input?.active||!sameSource(state,input,turn))return null;
 const spec=branchInputSpec(turn,input.choice);return spec?{...input,spec,turn}:null;
}
export function chooseInterviewAnswer(state,choice){
 const turn=latestInterview(state),q=turn?.metadata.interview;
 if(!q||q.ready)throw new Error('问题已变化，请刷新后继续');
 if(choice==='skip')return {text:`针对问题「${q.question}」，我的回答是：这项暂未确定，请不要替我设置条件`};
 if(!['left','right'].includes(choice))throw new Error('请选择当前卡片中的选项');
 const spec=branchInputSpec(turn,choice);
 if(spec){const previous=state.interviewInput;return {input:{source_message_id:turn.id,preference_version:state.room.me.preference_version,room_id:state.room.id,member_id:state.room.me.id,choice,active:true,value:sameSource(state,previous,turn)&&previous.choice===choice?previous.value||'':''}};}
 return {text:`针对问题「${q.question}」，我的回答是：${q[choice]}`};
}
export function interviewInputAnswer(state,raw){
 const input=currentInterviewInput(state);if(!input)throw new Error('问题已变化，请返回当前卡片重新选择');
 const {spec,turn,choice}=input;let value=String(raw??'').trim();
 if(!value)throw new Error('请填写具体内容，或返回卡片选择暂未确定');
 if(spec.kind==='number'){
  const n=Number(value),min=spec.min??0,max=spec.max??1000000,step=spec.step??.01;
  if(!Number.isFinite(n)||n<min||n>max||Math.abs(n/step-Math.round(n/step))>1e-6)throw new Error(`${spec.unit==='元/人'?'金额':spec.label}请填写 ${min}–${max}${step===1?' 的整数':'，最多两位小数'}`);
  value=String(n);
 }else if(spec.kind==='time'){
  const end=spec.allow_midnight_end??spec.field?.endsWith('end');
  if(!/^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(value)&&!(end&&value==='24:00'))throw new Error('时间请按 HH:MM 填写，结束时间支持 24:00');
  if(end&&value==='00:00')throw new Error('结束时间如指当天结束，请填写 24:00');
 }else if(value.length>(spec.max_length||1000))throw new Error('补充内容最多填写 1000 字');
 return `针对问题「${turn.metadata.interview.question}」，我选择：${turn.metadata.interview[choice]}。\n${spec.label}：${value}${spec.unit?' '+spec.unit:''}`;
}
