/* One visible decision card. A choice is committed only after its exit animation. */
export function installSwipe(card,signal){
 if(!card)return;
 const resize=()=>{
  const top=card.parentElement.getBoundingClientRect().top,height=window.visualViewport?.height||innerHeight,content=card.querySelector('.interview-content');
  // Give ordinary questions their natural height; only long content scrolls.
  const chrome=content?card.clientHeight-content.clientHeight:0;
  const needed=content?Math.min(content.scrollHeight,height*.55)+chrome:0;
  const available=Math.max(innerWidth<=600?300:320,height-Math.max(0,top)-120,Math.min(needed,height*.85));
  card.style.setProperty('--card-available',`${available}px`);
 };
 resize();window.addEventListener('resize',resize,{signal});window.visualViewport?.addEventListener('resize',resize,{signal});
 const opts={signal};let drag=null,busy=false,dispatching=false,animation=null,timer=null;
 const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
 const stamp=card.querySelector('[data-interview-stamp]');
 const reset=()=>{animation?.cancel();animation=null;card.style.transform='';card.style.transition='';card.classList.remove('is-dragging','choose-left','choose-right');if(stamp)stamp.style.opacity='0';};
 const pose=dx=>`translate3d(${dx}px,${-Math.abs(dx)*.045}px,0) rotate(${dx/Math.max(280,card.clientWidth)*18}deg)`;
 const commit=async choice=>{
  const button=card.querySelector(`[data-choice="${choice}"]`);if(busy||!button||button.disabled)return;
  busy=true;const direction=choice==='left'?-1:1;
  card.classList.remove('is-dragging');card.classList.add(choice==='left'?'choose-left':'choose-right');
  if(stamp){stamp.textContent=button.textContent;stamp.style.opacity='1';}
  animation=card.animate([{transform:card.style.transform||'none',opacity:1},{transform:`translate3d(${direction*(innerWidth*.65+card.clientWidth)}px,-55px,0) rotate(${direction*24}deg)`,opacity:0}],{duration:reduced()?0:280,easing:'cubic-bezier(.3,.65,.35,1)',fill:'forwards'});
  try{await animation.finished;}catch{return;}
  if(signal.aborted||!card.isConnected)return;
  dispatching=true;button.click();dispatching=false;
  if(button.hasAttribute('data-pref-table')||button.dataset.action==='interview-focus'){reset();busy=false;}
  else timer=setTimeout(()=>{if(card.isConnected){reset();busy=false;}},900);
 };
 card.setAttribute('tabindex','0');card.setAttribute('aria-label','滑动需求卡片');
 card.addEventListener('pointerdown',event=>{if(busy||event.button!==0||event.target.closest('button,input,textarea,a,select'))return;drag={id:event.pointerId,x:event.clientX,y:event.clientY,start:performance.now(),dx:0,dy:0};card.setPointerCapture(event.pointerId);card.classList.add('is-dragging');card.style.transition='none';},opts);
 card.addEventListener('pointermove',event=>{if(!drag||drag.id!==event.pointerId)return;drag.dx=event.clientX-drag.x;drag.dy=event.clientY-drag.y;if(Math.abs(drag.dx)<8||Math.abs(drag.dx)<Math.abs(drag.dy)*1.2)return;const dx=drag.dx,choice=dx>0?'right':'left';card.style.transform=pose(dx);card.classList.toggle('choose-right',dx>0);card.classList.toggle('choose-left',dx<0);if(stamp){stamp.textContent=card.querySelector(`[data-choice="${choice}"]`)?.textContent||'';stamp.style.opacity=String(Math.min(1,Math.abs(dx)/100));}},opts);
 card.addEventListener('pointerup',event=>{if(!drag||drag.id!==event.pointerId)return;const current=drag;drag=null;const distance=Math.abs(current.dx),speed=distance/Math.max(1,performance.now()-current.start),horizontal=distance>Math.abs(current.dy)*1.2;if(horizontal&&(distance>Math.min(110,card.clientWidth*.27)||(distance>35&&speed>.65)))void commit(current.dx>0?'right':'left');else{card.style.transition=reduced()?'none':'transform 320ms cubic-bezier(.18,.8,.32,1.25)';card.style.transform=pose(0);card.classList.remove('is-dragging','choose-left','choose-right');if(stamp)stamp.style.opacity='0';}},opts);
 card.addEventListener('pointercancel',()=>{drag=null;reset();},opts);
 card.addEventListener('click',event=>{const button=event.target.closest('[data-choice]');if(!button||dispatching||button.disabled)return;event.preventDefault();event.stopImmediatePropagation();void commit(button.dataset.choice);},{...opts,capture:true});
 card.addEventListener('keydown',event=>{if((event.target===card||event.target.closest('[data-choice]'))&&['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();void commit(event.key==='ArrowLeft'?'left':'right');}},opts);
 signal.addEventListener('abort',()=>{clearTimeout(timer);animation?.cancel();},{once:true});
}
