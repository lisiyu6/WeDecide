import {esc,icon,logo} from './common.js';
const stages=[['overview','决策总览'],['preferences','表达需求'],['compare','比较方案'],['negotiate','共同协商'],['vote','正式投票'],['result','决策结果'],['settings','房间设置']];
export function focusLayout(state,content){
 const r=state.room;
 return `<div class="workspace zen focus-layout"><header class="focus-topbar"><div class="focus-brand">${logo}<span title="${esc(r.scenario.title)}">${esc(r.scenario.title)}</span></div><div class="focus-navigation"><select aria-label="切换决策阶段" data-focus-nav>${stages.map(([value,label])=>`<option value="${value}" ${state.tab===value?'selected':''}>${label}</option>`).join('')}</select><button type="button" class="button ghost small" data-action="zen" aria-label="退出禅模式">${icon('grid',15)} 完整视图</button></div></header><main id="main" class="focus-content focus-${state.tab}"><div id="room-view">${content}</div></main></div>`;
}
