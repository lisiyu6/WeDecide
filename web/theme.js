/* Runs before the stylesheet so the first paint already uses the chosen theme. */
(()=>{
 const choices=['system','light','dark'],names={system:'自动',light:'浅色',dark:'深色'};
 const paths={system:'M4 4h16v12H4zM8 20h8m-4-4v4',light:'M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z',dark:'M20 15.2A8.4 8.4 0 0 1 8.8 4a8.4 8.4 0 1 0 11.2 11.2Z'};
 let preference='system';try{const saved=localStorage.getItem('wd-theme');if(choices.includes(saved))preference=saved;}catch{}
 const media=matchMedia('(prefers-color-scheme: dark)');
 function syncControls(){
  for(const control of document.querySelectorAll('[data-theme-toggle]')){
   const next=choices[(choices.indexOf(preference)+1)%choices.length],label=control.querySelector('[data-theme-label]');
   control.setAttribute('aria-label',`颜色主题：${names[preference]}，点击切换为${names[next]}`);control.title=`当前${names[preference]}，点击切换为${names[next]}`;
   if(label&&label.textContent!==names[preference])label.textContent=names[preference];
   control.querySelector('path')?.setAttribute('d',paths[preference]);
  }
 }
 function apply(){
  const actual=preference==='system'?(media.matches?'dark':'light'):preference;
  document.documentElement.dataset.theme=actual;document.documentElement.dataset.themePreference=preference;
  document.documentElement.style.colorScheme=actual;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content',actual==='dark'?'#141b18':'#f6f7f2');
  syncControls();
 }
 apply();media.addEventListener('change',()=>{if(preference==='system')apply();});
 window.addEventListener('storage',event=>{if(event.key==='wd-theme'){preference=choices.includes(event.newValue)?event.newValue:'system';apply();}});
 document.addEventListener('click',event=>{
  if(!event.target.closest('[data-theme-toggle]'))return;
  preference=choices[(choices.indexOf(preference)+1)%choices.length];try{localStorage.setItem('wd-theme',preference);}catch{}apply();
 });
 const observe=()=>{syncControls();new MutationObserver(syncControls).observe(document.body,{childList:true,subtree:true});};
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',observe,{once:true});else observe();
 window.addEventListener('beforeprint',()=>{document.documentElement.dataset.theme='light';document.documentElement.style.colorScheme='light';});
 window.addEventListener('afterprint',apply);
})();
