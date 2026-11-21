// Presentation layer for the published illustrative provider. Every plotted value
// comes from the response for the selected household, term and comparison date.
const money = n => new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP',maximumFractionDigits:0}).format(n);
const compact = n => Math.abs(n)>=1000 ? '£'+Number((n/1000).toFixed(1)).toLocaleString('en-GB')+'k' : money(n);
const percent = n => Number((Number(n)*100).toFixed(2))+'%';
const ink='#233c34', sage='#a6b99b', coral='#cd6746', rule='#bec7b9';

export function reviewCharts(React) {
  const h=React.createElement;
  const label=(x,y,content,anchor='middle',extra={})=>h('text',{x,y,textAnchor:anchor,fill:ink,...extra},content);
  const line=(x1,y1,x2,y2,extra={})=>h('line',{x1,y1,x2,y2,stroke:rule,...extra});
  const svg=(height,title,...children)=>h('svg',{viewBox:'0 0 350 '+height,role:'img','aria-label':title,className:'bp-report-chart'},...children);
  function scale(values, includeZero) {
    let low=Math.min(...values), high=Math.max(...values);
    if(includeZero){low=Math.min(0,low); high=Math.max(0,high);}
    if(low===high) {high+=Math.max(1,Math.abs(low)*.03);if(!includeZero)low-=Math.max(1,Math.abs(low)*.03);}
    const rough=(high-low)/3,base=10**Math.floor(Math.log10(rough));
    const step=[1,2,2.5,5,10].find(n=>n>=rough/base)*base;
    low=Math.floor(low/step)*step;high=Math.ceil(high/step)*step;
    const ticks=Array.from({length:1+Math.round((high-low)/step)},(_,i)=>low+i*step);
    return {low,high,ticks,map:(v,a,b)=>a+(v-low)*(b-a)/(high-low)};
  }
  function grid(s,y){return s.ticks.map(v=>h('g',{key:v},line(65,y(v),333,y(v)),label(59,y(v)+5,compact(v),'end')));}
  function Growth({d,current,growth,onGrowth}){
    const id=React.useId(),rate=growth??d.growth, paired=d.other_deposit!=null;
    const amounts=[current?.selected_position,...paired?[current?.other_position]:[]];
    const all=d.points.flatMap(p=>[Number(p.selected),...paired?[Number(p.other)]:[]]);
    const s=scale(all,true), y=v=>s.map(v,160,22);
    return h('div',{className:'bp-growth'},
      h('label',{htmlFor:id},h('strong',null,percent(rate)), ' a year'),
      h('input',{id,type:'range','aria-label':'Annual investment growth',min:d.low,max:d.high,step:.001,value:rate,onChange:e=>onGrowth(e.target.value)}),
      h('div',{className:'bp-range-ends'},h('span',null,percent(d.low)),h('span',null,percent(d.high))),
      d.crossings.length>0&&h('small',null,'Same outcome at '+d.crossings.map(p=>percent(p.growth)).join(' and ')),
      h('h3',null,'Position after '+d.objective_month/12+' years'),
      svg(205,'Position at the selected investment growth rate',...grid(s,y),...amounts.map((amount,i)=>{
        const cx=paired?(i?266:139):200,dpt=i?d.other_deposit:d.deposit;
        return h('g',{key:i},amount!=null&&h('rect',{x:cx-37,y:Math.min(y(0),y(amount)),width:74,height:Math.abs(y(0)-y(amount)),fill:i?'#d1dbc8':sage}),
          amount!=null&&label(cx,y(amount)-6,compact(Number(amount)),'middle',{fontWeight:650}),label(cx,184,money(dpt)),label(cx,202,'deposit'));
      })),
      h('p',{className:'bp-outcome','aria-live':'polite'}, !current?'Updating comparison…':!paired?'One funded deposit at this term':Number(current.difference)===0?'Both deposits finish level':money(Number(current.difference)>0?d.deposit:d.other_deposit)+' deposit ahead by '+money(Math.abs(Number(current.difference)))));
  }
  function Timeline({d}){
    const keys=['opening_equity','principal','cash','day_one','monthly'];
    const fills=[coral,ink,'#eee6ce',sage,'#d3dfca'];
    const months=d.timeline,last=months.at(-1);
    const sums=months.map(row=>keys.reduce((arr,k)=>[...arr,arr.at(-1)+Number(row[k])],[0]));
    const s=scale(sums.flat(),true),x=m=>65+268*m/d.objective_month,y=v=>s.map(v,170,16);
    const point=(j,k)=>x(months[j].month)+','+y(sums[j][k]);
    return h('div',null,h('h3',null,'Home equity, cash and investments'),
      svg(208,'Position from purchase to year '+d.objective_month/12,...grid(s,y),
        ...keys.map((k,i)=>h('polygon',{key:k,points:[...months.map((r,j)=>point(j,i+1)),...months.map((r,j)=>point(j,i)).reverse()].join(' '),fill:fills[i],stroke:ink,strokeWidth:.65})),
        label(65,196,'Purchase','start'),label(199,196,'Year '+d.objective_month/24),label(333,196,'Year '+d.objective_month/12,'end')),
      h('dl',{className:'bp-ledger'},...keys.map((k,i)=>h('div',{key:k},h('dt',null,h('i',{style:{background:fills[i]}}),['Opening equity','Mortgage repaid','Cash','Day-one investments','Monthly investing'][i]),h('dd',null,compact(Number(last[k])))))));
  }
  function Curve({data,onInfo}){
    const {selected,term_highest:lead,curve,domain}=data, pts=curve.segments.flatMap(v=>v.points);
    if(!pts.length)return h('p',{role:'status'},selected?.reason||'No funded deposits at this term.');
    const s=scale(pts.map(p=>Number(p.position)),false),x=v=>Number(domain.high)>Number(domain.low)?65+268*(v-domain.low)/(domain.high-domain.low):199,y=v=>s.map(v,170,20);
    const edge=curve.step?.at?.deposit,ok=selected?.status==='funded';
    const mid=edge!=null&&x(edge)>132&&x(edge)<267?edge:null;
    return h('div',null,h('h3',null,'Position after '+data.objective_month/12+' years'),
      svg(226,'Position by opening deposit. Shading marks unavailable ranges.',
        ...(curve.gaps||[]).map((v,i)=>h('rect',{key:'gap'+i,x:x(v.low),width:Math.max(1,x(v.high)-x(v.low)),y:16,height:154,fill:'#e6e1d6'},h('title',null,v.reason))),
        ...grid(s,y),...curve.segments.map((v,i)=>v.points.length===1?h('circle',{key:i,cx:x(v.points[0].deposit),cy:y(v.points[0].position),r:4,fill:ink}):h('polyline',{key:i,points:v.points.map(p=>x(p.deposit)+','+y(p.position)).join(' '),fill:'none',stroke:ink,strokeWidth:3})),
        lead&&h('path',{'data-marker':'highest',d:'M'+x(lead.deposit)+' '+(y(lead.position)-6)+'l6 6 -6 6 -6 -6Z',fill:ink}),
        ok&&h('circle',{'data-marker':'you',cx:x(selected.deposit),cy:y(selected.position),r:8,fill:'none',stroke:coral,strokeWidth:3}),
        label(65,194,compact(Number(domain.low)),'start'),mid!=null&&label(x(mid),194,money(mid)),label(333,194,compact(Number(domain.high)),'end'),label(199,218,'Opening deposit')),
      h('div',{className:'bp-key'},h('span',null,'◇ Highest evaluated'),h('span',null,'◯ Your choice')),
      (curve.gaps||[]).length>0&&h('small',null,'Shaded areas: '+[...new Set(curve.gaps.map(g=>g.status==='over_budget'?'over budget':g.status==='unknown'?'rate unknown':'unavailable'))].join(' or ')),!ok&&h('p',null,selected?.reason),h('button',{className:'phd-text-action',onClick:onInfo},'Comparison details'));
  }
  return {Growth,Timeline,Curve};
}
