import {Clock,phase,mix} from './timeline.mjs';

// Presentation coordinates and time only. Financial labels are sealed fictional
// snapshots, never interpolated, projected, ranked or calculated in the browser.
const FIXTURES=Object.freeze({
 '40':Object.freeze({deposit:'£40,000.00',mortgage:'£360,000.00',retained:'£60,000.00',band:.10}),
 '60':Object.freeze({deposit:'£60,000.00',mortgage:'£340,000.00',retained:'£40,000.00',band:.15}),
 '80':Object.freeze({deposit:'£80,000.00',mortgage:'£320,000.00',retained:'£20,000.00',band:.20})
});
const STUDIES={
 a:{duration:28,stops:[0,5.5,10.5,14.5,18.5,23,28],label:'Frames 05–08 · Connected consequences',beats:[
  [0,'One deposit decision.','Start with £40,000.00 down and £60,000.00 outside the home.'],
  [1.5,'More deposit. Less to borrow.','Watch the same money move from savings into the house.'],
  [5,'Less debt to charge interest on.','First, hold the rate and repayment term unchanged.'],
  [7,'The threshold belongs to this house.','£320,000.00 is 80% of this £400,000.00 purchase.'],
  [9.5,'A different rate band may be available.','This is a separate pricing step, not a rate cut with every pound.'],
  [12,'Follow the change into a monthly payment.','Same term: the larger deposit can mean a smaller payment.'],
  [16,'Place it inside the same budget.','This payment slip becomes the mortgage part of a fixed monthly budget.'],
  [19,'A smaller payment leaves more room.','Compared with the smaller deposit: less goes to the mortgage, more is available.'],
  [24,'More available to save, each month.','Saving or investing that remainder is an explicit choice.']
 ]},
 b:{duration:12,stops:[0,2.5,4.5,6.5,9,12],label:'Frame 11 · Opening investment and monthly additions',beats:[
  [0,'Start with what is invested on day one.','Both examples keep £20,000.00 in cash outside these investment balances.'],
  [2.5,'Then the monthly money arrives.','The same monthly budget is assumed; the larger deposit leaves more to add.'],
  [7,'Every addition feeds the same balance.','No separate pots to add in your head. No investment returns shown.'],
  [10,'A head start, or more added later?','Different timing creates the trade-off. This study calculates no winner.']
 ]},
 c:{duration:6,stops:[0,3,6],label:'Frames 13–14 · Same state, now in your hands',beats:[
  [0,'Keep your choice. Take the controls.','Choose an illustrative deposit below, then play the handover.'],
  [1,'The familiar objects make room.','The house, retained money and comparison date keep their meanings.'],
  [4.5,'You are holding the same instrument.','Change the deposit or date. The illustration follows; analysis is still uncalculated.']
 ]}
};
const $=id=>document.getElementById(id), NS='http://www.w3.org/2000/svg';
const state={study:'a',deposit:'40',years:'10',mobile:matchMedia('(max-width:750px)').matches};
let clock=new Clock(28),lastBeat=-1,raf=0;
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
const colors={green:'#233c34',coral:'#df795b',rust:'#9c4d33',paper:'#f6f2e9',sage:'#d7dfcf'};

function node(tag,id,attrs={},text='',parent=$('art')){
 parent??=$('art');
 const e=document.createElementNS(NS,tag);if(id)e.id=id;
 for(const [key,value] of Object.entries(attrs))e.setAttribute(key,String(value));
 if(text)e.textContent=text;parent.append(e);return e;
}
const group=(id,parent)=>node('g',id,{},'',parent);
const box=(id,parent,fill=colors.green)=>node('rect',id,{fill,rx:2},'',parent);
const text=(id,parent,content='',size=24,fill=colors.green)=>node('text',id,{'font-size':size,fill},content,parent);
const line=(id,parent,color=colors.green,width=2)=>node('path',id,{fill:'none',stroke:color,'stroke-width':width,'stroke-linecap':'round','stroke-linejoin':'round'},'',parent);
function attrs(id,values){const e=$(id);for(const [k,v] of Object.entries(values))e.setAttribute(k,String(v));}
function label(id,x,y,content,extra={}){attrs(id,{x,y,...extra});if($(id).textContent!==content)$(id).textContent=content;}
function geometry(id,x,y,width,height,extra={}){attrs(id,{x,y,width,height,...extra});}
function opacity(id,value){attrs(id,{opacity:Math.max(0,Math.min(1,value))});}
function makeHouse(prefix){
 const g=group(prefix+'house');line(prefix+'roof',g,colors.green,3.5);box(prefix+'debt',g);box(prefix+'deposit',g,colors.coral);
 const labels=group(prefix+'labels',g);text(prefix+'mortgage-label',labels,'Mortgage',24,colors.paper).classList.add('paper');text(prefix+'mortgage-value',labels,'',30,colors.paper).classList.add('paper');
 text(prefix+'deposit-label',labels,'Deposit',23);text(prefix+'deposit-value',labels,'',28,colors.rust).classList.add('rust');
 return g;
}
function drawHouse(prefix,x,y,w,h,fraction,scale,fixture){
 attrs(prefix+'house',{transform:`translate(${x} ${y}) scale(${scale})`});attrs(prefix+'roof',{d:`M-12 0L${w/2} -62L${w+12} 0`});
 geometry(prefix+'debt',0,0,w,h*(1-fraction));geometry(prefix+'deposit',0,h*(1-fraction),w,h*fraction);
 label(prefix+'mortgage-label',w/2,58,'Mortgage',{'text-anchor':'middle'});label(prefix+'mortgage-value',w/2,96,fixture.mortgage,{'text-anchor':'middle','font-weight':600});
 label(prefix+'deposit-label',0,h+35,'Deposit');label(prefix+'deposit-value',0,h+70,fixture.deposit,{'font-weight':600});
}
function makeEnvelope(prefix){const g=group(prefix+'envelope');box(prefix+'savings',g,colors.paper);line(prefix+'flap',g);box(prefix+'savings-fill',g,colors.coral);text(prefix+'savings-value',g,'',26);text(prefix+'savings-label',g,'Retained savings',22);return g;}
function drawEnvelope(prefix,x,y,w,h,fillHeight,fixture,scale=1){attrs(prefix+'envelope',{transform:`translate(${x} ${y}) scale(${scale})`});geometry(prefix+'savings',0,0,w,h,{stroke:colors.green,'stroke-width':2});geometry(prefix+'savings-fill',1,h-fillHeight,w-2,fillHeight-1,{opacity:.45});attrs(prefix+'flap',{d:`M0 0L${w/2} 32L${w} 0`});label(prefix+'savings-value',w/2,h-20,fixture.retained,{'text-anchor':'middle','font-weight':600});label(prefix+'savings-label',w/2,h+35,'Retained savings',{'text-anchor':'middle'});}

function buildA(){
 makeHouse('a-');makeEnvelope('a-');text('a-price',null,'',25);line('a-transfer',null,colors.coral,16);
 const interest=group('a-interest');line('a-interest-link',interest,colors.rust,2);box('a-interest-fill',interest,'url(#hatch)');text('a-interest-label',interest,'Interest',23).classList.add('rust');text('a-interest-context',interest,'',22).classList.add('rust');
 const threshold=group('a-threshold');line('a-threshold-line',threshold,colors.rust,2);text('a-ratio',threshold,'80%',24).classList.add('rust');const tag=group('a-tag',threshold);box('a-band-bg',tag,colors.paper);text('a-band',tag,'',22);
 text('a-mini-context',null,'Same mortgage',25);
 const budget=group('a-budget');line('a-budget-bracket',budget);text('a-budget-label',budget,'Same monthly budget',27);box('a-before',budget,'none');
 box('a-surplus',null,colors.coral);text('a-surplus-label',null,'Available',24);
 line('a-payment-connector',null,colors.green,2);box('a-payment');text('a-payment-label',null,'One monthly payment',24,colors.paper).classList.add('paper');
 const destination=group('a-destination');box('a-destination-outline',destination,'none');text('a-destination-label',destination,'Save or invest',25);box('a-monthly-tab',null,colors.coral);text('a-flow-note',null,'Monthly flow · schematic, not to scale',21).classList.add('rust');
}
function renderA(t){
 const m=state.mobile, transfer=phase(t,2,5),reframe=phase(t,14,16.5),retire=phase(t,11.5,12.5),rate=phase(t,9.5,10.5),repayment=phase(t,20,23);
 const snapshot=transfer<1?FIXTURES['40']:FIXTURES['80'];const hx=m?70:170,hy=m?135:145,hw=m?235:280,hh=m?230:260;
 const sx=m?255:735,sy=m?460:245,sw=m?185:205,sh=105;
 drawHouse('a-',mix(hx,m?45:65,reframe),mix(hy,m?100:90,reframe),hw,hh,mix(.1,.2,transfer),mix(1,.48,reframe),snapshot);
 opacity('a-labels',1-retire);opacity('a-price',1-retire);label('a-price',hx,m?48:48,'£400,000.00 home');
 drawEnvelope('a-',sx,sy,sw,sh,mix(60,20,transfer),snapshot);opacity('a-envelope',1-retire);
 // Exact example labels settle together; no invented in-flight monetary values.
 opacity('a-mortgage-value',transfer>0&&transfer<1?0:1);opacity('a-deposit-value',transfer>0&&transfer<1?0:1);opacity('a-savings-value',transfer>0&&transfer<1?0:1);
 const td=m?`M${sx} ${sy+70}C20 ${sy+70} 25 ${hy+hh-25} ${hx} ${hy+hh-25}`:`M${sx} ${sy+65}C610 310 600 390 450 390`;
 attrs('a-transfer',{d:td,pathLength:1,'stroke-dasharray':'.18 .82','stroke-dashoffset':-transfer*.82});opacity('a-transfer',(transfer>0&&transfer<1?1:0)*(1-reframe));
 const debtHeight=hh*(1-mix(.1,.2,transfer)),ix=hx+hw+25,iy=hy;
 opacity('a-interest',phase(t,.5,1.5)*(1-retire));geometry('a-interest-fill',ix,iy,m?30:45,debtHeight,{stroke:colors.rust,'stroke-width':1.5});
 attrs('a-interest-link',{d:`M${hx+hw+4} ${iy+6}H${ix-5}M${hx+hw+4} ${iy+debtHeight-6}H${ix-5}`});
 label('a-interest-label',m?ix-15:ix+70,m?iy-20:iy+80,'Interest');label('a-interest-context',m?35:ix+70,m?650:iy+116,rate<1?'Same rate & term':'Rate may improve');
 const reveal=phase(t,7,8);opacity('a-threshold',reveal*(1-retire));attrs('a-threshold-line',{d:`M${hx-25} ${hy+hh*.8}H${hx+hw}`, 'stroke-dasharray':'5 5'});label('a-ratio',hx-10,hy+hh*.8-12,'80%',{'text-anchor':'end'});
 const bx=m?35:120,by=m?620:hy+hh+106,bw=m?410:420;
 geometry('a-band-bg',bx,by,bw,48,{fill:rate>=.5?colors.green:colors.paper,stroke:colors.green});label('a-band',bx+bw/2,by+31,rate<.5?'Fictional 80% boundary':'A better rate may be available',{'text-anchor':'middle',style:`fill:${rate>=.5?colors.paper:colors.green}`});attrs('a-tag',{transform:`translate(${bx+bw/2} ${by+24}) scale(${Math.abs(1-2*rate)} 1) translate(${-bx-bw/2} ${-by-24})`});
 if(m)opacity('a-interest-context',1-reveal);
 opacity('a-mini-context',phase(t,16.5,17.5));label('a-mini-context',m?205:255,m?150:145,'Same mortgage');
 const arrive=phase(t,12.5,14),move=phase(t,14.5,18),budgetReveal=phase(t,18,19.5);
 const bx2=m?40:150,by2=m?365:335,bw2=m?400:700;
 const px=mix(mix(hx+hw,m?85:545,arrive),bx2,move),py=mix(mix(hy+100,m?465:285,arrive),by2,move),pw=mix((m?310:290)*arrive,bw2*.82,move)-bw2*.20*repayment,ph=mix(62,78,move);
 const edgeX=mix(hx,m?45:65,reframe)+hw*mix(1,.48,reframe),edgeY=mix(hy,m?100:90,reframe)+hh*.42*mix(1,.48,reframe);
 attrs('a-payment-connector',{d:m?`M${edgeX} ${edgeY}C${edgeX+55} ${edgeY} ${edgeX+65} ${py-35} ${px+pw/2} ${py}`:`M${edgeX} ${edgeY}Q${edgeX+45} ${edgeY} ${px} ${py+ph/2}`});opacity('a-payment-connector',arrive*(1-phase(t,16,18)));
 geometry('a-payment',px,py,pw,ph,{rx:mix(8,0,move)});opacity('a-payment',arrive);label('a-payment-label',px+pw/2,py+ph/2+8,move<.8?'One monthly payment':m?'Mortgage':'Mortgage payment',{'text-anchor':'middle','font-size':m?23:25});opacity('a-payment-label',arrive);
 opacity('a-budget',budgetReveal);attrs('a-budget-bracket',{d:`M${bx2} ${by2-15}V${by2-36}H${bx2+bw2}V${by2-15}`,pathLength:1,'stroke-dasharray':1,'stroke-dashoffset':1-budgetReveal});label('a-budget-label',bx2,by2-58,'Same monthly budget');
 geometry('a-before',bx2,by2,bw2*.82,78,{stroke:colors.green,'stroke-dasharray':'5 5','stroke-width':1.5,opacity:repayment});
 geometry('a-surplus',bx2+pw,by2,bw2-pw,78);opacity('a-surplus',budgetReveal);label('a-surplus-label',bx2+pw+(bw2-pw)/2,by2+47,'Available',{'text-anchor':'middle','font-size':m?20:24});opacity('a-surplus-label',budgetReveal);
 const emit=phase(t,24,26),dx=m?140:615,dy=m?570:490;
 geometry('a-destination-outline',dx-40,dy-10,m?240:230,65,{stroke:colors.rust,'stroke-width':2});label('a-destination-label',dx+(m?80:75),dy+33,'Save or invest',{'text-anchor':'middle'});opacity('a-destination',phase(t,23.5,24.3));
 geometry('a-monthly-tab',mix(bx2+bw2-60,dx+45,emit),mix(by2+85,dy+10,emit),45,18);opacity('a-monthly-tab',(emit>0&&emit<1)?1:0);
 label('a-flow-note',m?35:150,m?675:555,'Monthly flow · schematic, not to scale');opacity('a-flow-note',budgetReveal);
}
function buildB(){
 text('b-reserve',null,'',22);text('b-date',null,'',27);
 for(const key of ['a','b']){const prefix=`b-${key}-`;text(prefix+'title',null,'',27);text(prefix+'initial',null,'',23);line(prefix+'rail');const g=group(prefix+'balance');box(prefix+'outline',g,colors.paper);box(prefix+'opening',g,colors.coral);for(let i=0;i<3;i++)box(prefix+'layer'+i,g,colors.coral);text(prefix+'caption',g,'One balance',21);box(prefix+'packet',null,colors.coral);text(prefix+'monthly',null,'',22);}
 text('b-note',null,'Contribution timing only · no returns or outcome totals',21).classList.add('rust');
}
function renderB(t){
 const m=state.mobile,initial=phase(t,.5,2),travel=phase(t,2.7,9),x=mix(m?75:410,m?315:835,travel),cw=m?125:150,ch=98;
 label('b-reserve',m?30:60,m?35:35,'Same £20,000.00 cash reserve in both');
 const month=t<3?'Purchase day':t<5?'Month 1':t<7?'Month 2':'Month 3';label('b-date',m?240:850,m?650:550,month,{'text-anchor':'middle'});
 for(const [i,key] of ['a','b'].entries()){
  const p=`b-${key}-`,y=m?(i?405:145):(i?340:130),titleY=m?y-60:y+16;
  label(p+'title',m?30:60,titleY,i?'Smaller deposit':'Larger deposit',{'font-weight':600});
  label(p+'initial',m?30:60,titleY+34,i?'£40,000.00 initially':'£0.00 initially');
  attrs(p+'rail',{d:`M${m?55:340} ${y+ch+25}H${m?430:930}`,stroke:'#a6b99b'});
  attrs(p+'balance',{transform:`translate(${x-cw/2} ${y})`});geometry(p+'outline',0,0,cw,ch,{stroke:colors.green,'stroke-width':2,rx:5});
  const base=i?35*initial:0;geometry(p+'opening',2,ch-base-2,cw-4,base,{opacity:.7});
  let bottom=ch-base-2;
  for(let j=0;j<3;j++){const arrival=phase(t,3+j*2,4+j*2),layer=(i?9:17)*arrival;bottom-=layer;geometry(p+'layer'+j,2,bottom,cw-4,layer,{opacity:.8});}
  label(p+'caption',cw/2,30,'One balance',{'text-anchor':'middle','font-size':m?19:21});
  const j=Math.min(2,Math.max(0,Math.floor((t-3)/2))),drop=phase(t,3+j*2,4+j*2),show=t>=3&&t<9&&drop<1;
  geometry(p+'packet',x-(i?15:23),mix(y-50,y+ch-base-12,drop),i?30:46,i?12:20);opacity(p+'packet',show?1:0);
  label(p+'monthly',m?30:300,y+ch+63,i?'Less added each month':'More added each month');opacity(p+'monthly',phase(t,2.5,3));
 }
 label('b-note',m?30:60,m?690:575,m?'Schematic balances · no winner calculated':'Contribution timing only · no returns or outcome totals');
}
function buildC(){makeHouse('c-');makeEnvelope('c-');text('c-price',null,'',24);line('c-time');node('circle','c-date-dot',{r:10,fill:colors.coral});text('c-date-label',null,'',25);text('c-opening',null,'',25);text('c-debt-name',null,'Mortgage',21);text('c-money-name',null,'Retained',21);text('c-debt-summary',null,'',24);text('c-money-summary',null,'',24);const a=group('c-analysis');box('c-analysis-box',a,'none');text('c-analysis-title',a,'',27);text('c-analysis-line1',a,'',22);text('c-analysis-line2',a,'',22);text('c-analysis-line3',a,'',20).classList.add('rust');}
function renderC(t){
 const m=state.mobile,q=phase(t,1,4.5),f=FIXTURES[state.deposit],s=mix(1,m?.65:.72,q);
 drawHouse('c-',mix(m?65:220,m?35:75,q),mix(m?130:135,m?105:150,q),m?225:265,m?210:235,f.band,s,f);
 drawEnvelope('c-',mix(m?245:700,m?265:365,q),mix(m?420:255,m?150:190,q),m?185:210,100,state.deposit==='40'?60:state.deposit==='60'?40:20,f,mix(1,m?.9:1,q));
 const oldLabels=1-phase(t,1,2),newLabels=phase(t,4.3,5);
 opacity('c-labels',m?oldLabels:1);opacity('c-savings-label',m?oldLabels:1);opacity('c-savings-value',m?oldLabels:1);
 label('c-price',m?40:90,45,'£400,000.00 home');label('c-opening',m?40:90,m?334:410,'Your starting allocation');opacity('c-opening',newLabels);
 label('c-debt-name',35,260,'Mortgage');label('c-money-name',265,260,'Retained');opacity('c-debt-name',m?newLabels:0);opacity('c-money-name',m?newLabels:0);
 label('c-debt-summary',35,289,f.mortgage);opacity('c-debt-summary',m?newLabels:0);label('c-money-summary',265,289,f.retained);opacity('c-money-summary',m?newLabels:0);
 const tx=m?40:mix(200,75,q),ty=m?mix(480,370,q):mix(440,485,q),tw=m?400:mix(650,480,q),marker={'5':.18,'10':.42,'20':.8}[state.years];
 attrs('c-time',{d:`M${tx} ${ty}H${tx+tw}`, 'stroke-width':3});attrs('c-date-dot',{cx:tx+tw*marker,cy:ty});label('c-date-label',tx,ty+40,`Compare after ${state.years} years`);
 opacity('c-analysis',newLabels);geometry('c-analysis-box',m?30:650,m?590:300,m?420:320,m?103:240,{stroke:'#a6b99b','stroke-dasharray':'6 7'});
 label('c-analysis-title',m?50:675,m?625:345,m?'Room for the next question':'The next question',{'font-size':m?24:27});label('c-analysis-line1',m?50:675,m?660:390,m?'Results are not calculated.':'How do these choices');label('c-analysis-line2',675,423,'compare over time?');opacity('c-analysis-line2',m?0:1);label('c-analysis-line3',675,505,'Results are not calculated.');opacity('c-analysis-line3',m?0:1);
 const W=m?480:1000,H=m?710:590,cx=m?30:mix(420,660,q),cy=m?mix(590,460,q):mix(490,150,q),cw=m?420:mix(500,310,q);
 Object.assign($('choices').style,{left:`${cx/W*100}%`,top:`${cy/H*100}%`,width:`${cw/W*100}%`,right:'auto',bottom:'auto',gridTemplateColumns:'1fr 1fr'});
}

function build(){
 $('art').replaceChildren();$('canvas').setAttribute('viewBox',state.mobile?'0 0 480 710':'0 0 1000 590');
 ({a:buildA,b:buildB,c:buildC})[state.study]();$('choices').hidden=state.study!=='c';lastBeat=-1;render();
}
function render(){
 ({a:renderA,b:renderB,c:renderC})[state.study](clock.time);
 const spec=STUDIES[state.study],idx=spec.beats.findLastIndex(b=>clock.time>=b[0]);
 if(lastBeat!==idx){const b=spec.beats[idx];$('study-title').textContent=b[1];$('stage-line').textContent=b[2];$('svg-title').textContent=b[1];lastBeat=idx;}
 $('beat-label').textContent=spec.label;$('time-label').textContent=`${clock.time.toFixed(1)} / ${spec.duration} s`;$('scrub').value=String(clock.time);$('scrub').max=String(spec.duration);$('play').textContent=reduced.matches?'Next key state':clock.playing?'Pause':'Play study';
 $('canvas').dataset.time=clock.time.toFixed(3);$('canvas').dataset.study=state.study;$('canvas').dataset.playing=String(clock.playing);$('canvas').dataset.deposit=state.deposit;$('canvas').dataset.years=state.years;
 $('back').disabled=clock.time===0;$('next').disabled=clock.time===spec.duration;
 $('qualification').textContent=state.study==='b'?'Contribution-only illustration. Schematic fills and additions are not monetary scales, forecasts or a winner. Investments can lose value.':state.study==='c'?'Starting allocation only. Date selection does not generate results. Three fixed fictional deposit examples; no backend.':'Interest, rate changes and monthly amounts are conceptual, not calculated or to scale. Buying costs are already set aside.';
 const f=FIXTURES[state.deposit];
 const description=state.study==='a'?(clock.time<2?'Opening deposit £40,000.00; mortgage £360,000.00; retained savings £60,000.00.':clock.time<5?'Transferring the illustrative deposit from £40,000.00 to £80,000.00; mortgage and retained savings decrease together.':'Larger deposit £80,000.00; mortgage £320,000.00; retained savings £20,000.00. The mortgage is 80% of the £400,000.00 price.')+' Interest is attached outside the house. A fictional band may improve pricing. The same monthly-payment slip becomes part of a fixed budget; compared with the smaller deposit it leaves more available to save. Cost and payment geometry is schematic.':state.study==='b'?'Larger deposit: £0.00 invested initially, conceptually more added monthly. Smaller deposit: £40,000.00 invested initially, conceptually less added monthly. Both retain £20,000.00 cash. Opening and monthly contributions enter one investment balance per strategy. Fill is schematic, with no returns, totals or winner.':`Your starting allocation: deposit ${f.deposit}, mortgage ${f.mortgage}, retained savings ${f.retained}. Selected comparison date ${state.years} years. These selections persist through the handover. No future result has been calculated.`;
 $('svg-description').textContent=description;
}
function loop(now){clock.tick(now);render();if(clock.playing)raf=requestAnimationFrame(loop);}
function stop(){cancelAnimationFrame(raf);clock.pause();render();}
function play(replay=false){cancelAnimationFrame(raf);if(reduced.matches){seek(nextStop());return;}if(replay)clock.replay(performance.now());else clock.play(performance.now());raf=requestAnimationFrame(loop);render();}
function seek(t){cancelAnimationFrame(raf);clock.seek(t);render();$('announcement').textContent=$('study-title').textContent+' '+$('svg-description').textContent;}
function nextStop(){return STUDIES[state.study].stops.find(s=>s>clock.time+.01)??clock.duration;}
function setStudy(key,time=0){if(!STUDIES[key])return;cancelAnimationFrame(raf);state.study=key;clock=new Clock(STUDIES[key].duration);clock.seek(time);document.querySelectorAll('button[data-study]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.study===key)));build();}
document.querySelectorAll('button[data-study]').forEach(b=>b.addEventListener('click',()=>setStudy(b.dataset.study)));
$('play').addEventListener('click',()=>clock.playing?stop():play());$('replay').addEventListener('click',()=>{if(reduced.matches)seek(0);else play(true);});
$('next').addEventListener('click',()=>seek(nextStop()));$('back').addEventListener('click',()=>seek([...STUDIES[state.study].stops].reverse().find(s=>s<clock.time-.01)??0));$('scrub').addEventListener('input',e=>seek(Number(e.target.value)));
$('deposit-choice').addEventListener('change',e=>{stop();state.deposit=e.target.value;render();});$('date-choice').addEventListener('change',e=>{stop();state.years=e.target.value;render();});
$('choices').addEventListener('pointerdown',stop);$('choices').addEventListener('focusin',stop);
document.addEventListener('visibilitychange',()=>{if(document.hidden&&clock.playing)stop();});
function motionPreference(){if(reduced.matches)stop();$('play').textContent=reduced.matches?'Next key state':'Play study';$('motion-note').textContent=reduced.matches?'Reduced motion: use Next/Previous or the timeline. Play advances to the next still state.':'No autoplay. Pause, replay, or drag the timeline to inspect a transformation.';}
reduced.addEventListener('change',motionPreference);
matchMedia('(max-width:750px)').addEventListener('change',e=>{stop();state.mobile=e.matches;build();});
document.querySelectorAll('[data-still]').forEach(b=>b.addEventListener('click',()=>{setStudy(b.dataset.still,Number(b.dataset.time));$('motion').scrollIntoView();$('play').focus({preventScroll:true});}));
const params=new URLSearchParams(location.search);if(params.has('focus')){document.body.classList.add('focus');$('study-title').setAttribute('role','heading');$('study-title').setAttribute('aria-level','1');}setStudy(params.get('study')||'a');motionPreference();
fetch('review.json').then(r=>r.ok?r.json():null).then(m=>{if(m)$('source').textContent=`Source: ${m.source_branch} at ${m.source_commit}. Publication branch: ${m.publication_branch}.`;}).catch(()=>{});
