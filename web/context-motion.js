/* The two edge cards share one focused writing surface and pointer lifecycle. */
let gesture=null,ignoreClickUntil=0,installed=false,dismissing=null;
const motions=new WeakMap();
const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
const deck=()=>document.getElementById('context-drawer');
const stack=()=>deck()?.querySelector('.context-fan-stack');
const direction=side=>side==='left'?-1:1;
const centered={transform:'translate3d(0,0,0) rotate(0deg) scale(1)',opacity:1};

function edgePose(side,progress=0){
 const distance=(innerWidth+Math.min(660,innerWidth-44))/2+40;
 const remaining=1-Math.max(0,Math.min(1,progress)),sign=direction(side);
 return {transform:`translate3d(${sign*distance*remaining}px,${32*remaining}px,0) rotate(${sign*18*remaining}deg) scale(${1-.08*remaining})`,opacity:Math.min(1,.3+progress)};
}
function paint(node,pose){node.style.transform=pose.transform;node.style.opacity=pose.opacity;}
function animate(node,to,duration=400,from=null){
 motions.get(node)?.cancel();
 const current=from||{transform:getComputedStyle(node).transform,opacity:getComputedStyle(node).opacity};
 const motion=node.animate([current,to],{duration:reduced()?0:duration,easing:'cubic-bezier(.2,.8,.25,1)',fill:'both'});
 motions.set(node,motion);
 return motion.finished.catch(()=>{}).then(()=>{
  if(motions.get(node)!==motion)return;
  paint(node,to);motion.cancel();motions.delete(node);
 });
}
function sizeDeck(){
 const node=deck();if(!node)return;
 const viewport=window.visualViewport;
 node.style.setProperty('--context-viewport',`${viewport?.height||innerHeight}px`);
 node.style.top=`${(viewport?.offsetTop||0)+(viewport?.height||innerHeight)/2}px`;
}
export function mountContextMotion(node,{restored=false}={}){
 sizeDeck();
 const surface=node.querySelector('.context-fan-stack');
 if(gesture?.opening){node.classList.add('is-dragging');paint(surface,edgePose(gesture.side,0));}
 else if(!restored)void animate(surface,centered,460,edgePose(node.dataset.side,0));
}
export async function dismissContextCard(){
 const node=deck(),surface=stack();if(!node||!surface)return;
 if(dismissing?.node===node)return dismissing.promise;
 node.classList.add('is-leaving');
 const promise=animate(surface,edgePose(node.dataset.side),300);
 dismissing={node,promise};
 await promise;
 if(dismissing?.node===node)dismissing=null;
}
export function installContextGestures({isAvailable,onOpen,onClose}){
 if(installed)return;installed=true;
 window.addEventListener('resize',sizeDeck);
 window.visualViewport?.addEventListener('resize',sizeDeck);
 window.visualViewport?.addEventListener('scroll',sizeDeck);
 document.addEventListener('click',event=>{
  if(event.detail&&performance.now()<ignoreClickUntil){event.preventDefault();event.stopImmediatePropagation();}
 },true);
 document.addEventListener('pointerdown',event=>{
  if(!isAvailable()||event.button!==0||!event.isPrimary||gesture)return;
  const node=deck(),modal=document.querySelector('dialog[open]');
  if(modal&&modal!==node)return;
  const edge=event.target.closest('[data-context-edge]');
  if(node){
   if(!event.target.closest('[data-context-handle]')||event.target.closest('button,input,textarea,select,a'))return;
  }else if(!edge)return;
  gesture={id:event.pointerId,x:event.clientX,y:event.clientY,time:performance.now(),side:node?.dataset.side||edge.dataset.contextEdge,opening:!node,started:false,dx:0,dy:0};
 });
 document.addEventListener('pointermove',event=>{
  if(!gesture||gesture.id!==event.pointerId)return;
  const g=gesture;g.dx=event.clientX-g.x;g.dy=event.clientY-g.y;
  const horizontal=Math.abs(g.dx)>Math.abs(g.dy)*1.25;
  const distance=g.dx*direction(g.side)*(g.opening?-1:1);
  if(!g.started){
   if(!horizontal||distance<7)return;
   g.started=true;
   if(g.opening)onOpen(g.side);
   const node=deck();if(!node){gesture=null;return;}
   node.classList.add('is-dragging');
   motions.get(stack())?.cancel();
   try{node.setPointerCapture(event.pointerId);}catch{}
  }
  event.preventDefault();
  const surface=stack();if(!surface)return;
  if(g.opening)paint(surface,edgePose(g.side,Math.max(0,distance)/Math.min(300,innerWidth*.65)));
  else paint(surface,{transform:`translate3d(${direction(g.side)*Math.max(0,distance)}px,0,0) rotate(${direction(g.side)*Math.min(15,Math.max(0,distance)/18)}deg) scale(1)`,opacity:Math.max(.35,1-Math.max(0,distance)/innerWidth)});
 },{passive:false});
 const release=(event,cancelled=false)=>{
  if(!gesture||event.pointerId!==gesture.id)return;
  const g=gesture;gesture=null;
  if(!g.started)return;
  const node=deck(),surface=stack();if(!node||!surface)return;
  node.classList.remove('is-dragging');
  ignoreClickUntil=performance.now()+120;
  const distance=g.dx*direction(g.side)*(g.opening?-1:1),velocity=distance/Math.max(1,performance.now()-g.time);
  const commit=!cancelled&&(distance>Math.min(76,innerWidth*.19)||(distance>30&&velocity>.65));
  if(g.opening?commit:!commit)void animate(surface,centered,280);
  else void onClose();
 };
 document.addEventListener('pointerup',event=>release(event));
 document.addEventListener('pointercancel',event=>release(event,true));
 document.addEventListener('lostpointercapture',event=>{if(event.target===deck())release(event,true);});
 window.addEventListener('blur',()=>{if(gesture)release({pointerId:gesture.id},true);});
 let backdropStart=false;
 const outside=(event,node)=>{const r=node.getBoundingClientRect();return event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom;};
 document.addEventListener('pointerdown',event=>{const node=deck();backdropStart=Boolean(node&&event.target===node&&outside(event,node));});
 document.addEventListener('pointerup',event=>{
  const node=deck();if(backdropStart&&node&&event.target===node&&outside(event,node))void onClose();backdropStart=false;
 });
}
