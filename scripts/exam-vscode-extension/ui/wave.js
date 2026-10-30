/* Local VCD reader and compact digital waveform viewer. No remote services. */
(function(){
  function parseVcd(text){
    const end=text.indexOf('$enddefinitions');
    if(end<0)throw Error('VCD 缺少信号定义。');
    const boundary=text.indexOf('$end',end+15)+4;
    const header=text.slice(0,boundary);
    const unit=(header.match(/\$timescale\s+(\d+)\s*(s|ms|us|ns|ps|fs)\s+\$end/)||[]);
    const scale=Number(unit[1]||1)*({s:1e9,ms:1e6,us:1e3,ns:1,ps:1e-3,fs:1e-6}[unit[2]]||1);
    const scopes=[],signals=[],ids=new Map();
    for(const block of header.matchAll(/\$(scope|upscope|var)\s+([\s\S]*?)\$end/g)){
      const parts=block[2].trim().split(/\s+/);
      if(block[1]==='scope')scopes.push(parts[1]);
      else if(block[1]==='upscope')scopes.pop();
      else{
        const [,width,id,name,...range]=parts;
        if(!ids.has(id))ids.set(id,[]);
        signals.push({name:[...scopes,name].join('.')+(range.length?' '+range.join(' '):''),width:Number(width),events:ids.get(id)});
      }
    }
    let time=0;
    const tokens=text.slice(boundary).trim().split(/\s+/);
    for(let i=0;i<tokens.length;i++){
      const token=tokens[i];
      if(token[0]==='#')time=Number(token.slice(1));
      else if(/^[01xz]/i.test(token)){
        const list=ids.get(token.slice(1));if(list)list.push([time,token[0].toLowerCase()]);
      }else if(/^[br]/i.test(token)){
        const list=ids.get(tokens[++i]);if(list)list.push([time,token.slice(1).toLowerCase()]);
      }
    }
    return {signals,end:Math.max(1,time),scale};
  }
  function valueAt(events,time){
    let low=0,high=events.length;
    while(low<high){const mid=(low+high)>>1;if(events[mid][0]<=time)low=mid+1;else high=mid;}
    return low?events[low-1][1]:'x';
  }
  function display(value,width){
    if(/[xz]/i.test(value))return value;
    if(width===1)return value;
    try{return '0x'+BigInt('0b'+value).toString(16);}catch(_){return value;}
  }
  window.ExamWave={parseVcd,valueAt};
  if(typeof document==='undefined')return;
  const $=id=>document.getElementById(id);
  let data=null,selected=new Set(),start=0,span=1,cursor=null;
  const canvas=$('waveCanvas'),ctx=canvas.getContext('2d');
  function stamp(t){return Number((t*(data?.scale||1)).toPrecision(6))+' ns';}
  function list(){
    const query=$('signalSearch').value.toLowerCase();$('signals').replaceChildren();
    if(!data)return;
    data.signals.forEach((s,i)=>{
      if(!s.name.toLowerCase().includes(query))return;
      const label=document.createElement('label'),input=document.createElement('input'),name=document.createElement('span');
      input.type='checkbox';input.checked=selected.has(i);input.onchange=()=>{input.checked?selected.add(i):selected.delete(i);draw();};
      name.textContent=s.name;label.title=s.name;label.append(input,name);$('signals').append(label);
    });
  }
  function draw(){
    const width=Math.max(300,$('waveScroll').clientWidth),height=Math.max(140,36+selected.size*32);
    const ratio=window.devicePixelRatio||1;
    canvas.width=width*ratio;canvas.height=height*ratio;canvas.style.height=height+'px';ctx.scale(ratio,ratio);
    ctx.fillStyle='#fff';ctx.fillRect(0,0,width,height);ctx.font='11px Consolas, monospace';
    if(!data){ctx.fillStyle='#8394a8';ctx.fillText('点击 Run 后，这里会显示真实仿真波形。',20,40);return;}
    const labelWidth=Math.min(175,width*.33),right=width-14,plot=right-labelWidth;
    for(let n=0;n<=5;n++){
      const x=labelWidth+plot*n/5;
      ctx.strokeStyle='#e8eef5';ctx.beginPath();ctx.moveTo(x,25);ctx.lineTo(x,height);ctx.stroke();
      ctx.fillStyle='#8495a9';ctx.fillText(stamp(start+span*n/5),Math.min(x+3,width-75),16);
    }
    let row=0;
    for(const index of selected){
      const signal=data.signals[index],y=31+row++*32;
      ctx.fillStyle=row%2?'#f8fafc':'#fff';ctx.fillRect(0,y,width,32);
      ctx.fillStyle='#4c637c';
      let short=signal.name.replace(/^[^.]+\./,'');
      if(short.length>22)short='…'+short.slice(-21);
      ctx.fillText(short,8,y+12);
      const value=valueAt(signal.events,cursor??start);
      ctx.fillStyle='#94a2b3';ctx.fillText(display(value,signal.width),8,y+26);
      const visible=signal.events.filter(e=>e[0]>start&&e[0]<start+span);
      const events=[[start,valueAt(signal.events,start)],...visible,[start+span,null]];
      for(let j=0;j<events.length-1;j++){
        const [time,v]=events[j],x=labelWidth+(time-start)/span*plot,x2=labelWidth+(events[j+1][0]-start)/span*plot;
        ctx.strokeStyle=/[xz]/.test(v)?'#d26c50':'#21987c';ctx.lineWidth=1.4;ctx.beginPath();
        if(signal.width===1){
          const yy=v==='1'?y+7:v==='0'?y+25:y+16;
          ctx.moveTo(x,yy);ctx.lineTo(x2,yy);
          if(j<events.length-2){const nv=events[j+1][1];ctx.lineTo(x2,nv==='1'?y+7:nv==='0'?y+25:y+16);}
        }else{
          const edge=Math.min(3,(x2-x)/3);
          ctx.moveTo(x,y+16);ctx.lineTo(x+edge,y+7);ctx.lineTo(x2-edge,y+7);ctx.lineTo(x2,y+16);ctx.lineTo(x2-edge,y+25);ctx.lineTo(x+edge,y+25);ctx.closePath();
          if(x2-x>30){ctx.save();ctx.beginPath();ctx.rect(x+5,y+3,Math.max(0,x2-x-10),27);ctx.clip();ctx.fillStyle=ctx.strokeStyle;ctx.fillText(display(v,signal.width),x+7,y+20);ctx.restore();}
        }
        ctx.stroke();
      }
    }
    if(!selected.size){ctx.fillStyle='#8394a8';ctx.fillText('在左侧勾选要看的信号。',labelWidth,60);}
    if(cursor!==null){const x=labelWidth+(cursor-start)/span*plot;if(x>=labelWidth&&x<=right){ctx.strokeStyle='#e6a03c';ctx.beginPath();ctx.moveTo(x,25);ctx.lineTo(x,height);ctx.stroke();}}
    $('timeLabel').textContent=cursor===null?stamp(start)+' → '+stamp(start+span):'光标 '+stamp(cursor);
  }
  $('signalSearch').oninput=list;
  $('zoomIn').onclick=()=>{if(!data)return;span=Math.max(1,span/2);start=Math.min(start,data.end-span);draw();};
  $('zoomOut').onclick=()=>{if(!data)return;span=Math.min(data.end,span*2);start=Math.min(start,data.end-span);draw();};
  $('fit').onclick=()=>{if(!data)return;start=0;span=data.end;$('pan').value=0;cursor=null;draw();};
  $('pan').oninput=()=>{if(!data)return;start=(data.end-span)*Number($('pan').value)/1000;draw();};
  canvas.onclick=e=>{if(!data)return;const width=$('waveScroll').clientWidth,labelWidth=Math.min(175,width*.33);cursor=start+Math.max(0,Math.min(1,(e.offsetX-labelWidth)/(width-14-labelWidth)))*span;draw();};
  new ResizeObserver(draw).observe($('waveScroll'));
  window.ExamWave.load=text=>{
    data=text?parseVcd(text):null;selected=new Set();start=0;cursor=null;span=data?.end||1;
    if(data){const minDepth=Math.min(...data.signals.map(s=>s.name.split('.').length));data.signals.forEach((s,i)=>{if(s.name.split('.').length===minDepth&&selected.size<10)selected.add(i);});}
    $('signalSearch').value='';$('pan').value=0;list();draw();
  };
  window.ExamWave.redraw=draw;
})();
