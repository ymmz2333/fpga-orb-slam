const vscode=acquireVsCodeApi(),$=id=>document.getElementById(id);
function send(type,extra={}){vscode.postMessage({type,...extra});}
function tab(which){$('log').hidden=which!=='log';$('waveView').hidden=which!=='wave';$('logTab').classList.toggle('selected',which==='log');$('waveTab').classList.toggle('selected',which==='wave');if(which==='wave')requestAnimationFrame(()=>ExamWave.redraw());}
function running(value){for(const id of ['run','new','import','add','save','question'])$(id).disabled=value;$('run').textContent=value?'运行中…':'▶ Run';$('status').textContent=value?'正在保存、编译、仿真':'Ctrl+Enter 运行';}
for(const id of ['run','new','import','add','save','fullWave'])$(id).onclick=()=>send(id);
$('question').onchange=()=>send('switch',{question:$('question').value});$('logTab').onclick=()=>tab('log');$('waveTab').onclick=()=>tab('wave');
window.addEventListener('message',event=>{
  const m=event.data;
  if(m.type==='load'){$('question').replaceChildren(...m.questions.map(q=>{const o=document.createElement('option');o.value=q.id;o.textContent=q.name;return o;}));$('question').value=m.question;}
  if(m.type==='clear'){ExamWave.load(null);$('log').textContent='点击 Run：自动保存代码、编译、仿真并显示波形。';$('verdict').textContent='左边 TB · 右边设计 · VS Code 原生补全和缩进';$('verdict').className='';tab('log');}
  if(m.type==='saved')$('status').textContent='已保存';
  if(m.type==='running'){running(true);$('log').textContent='正在运行…';$('verdict').textContent='运行中';$('verdict').className='';ExamWave.load(null);tab('log');}
  if(m.type==='result'){
    running(false);$('log').textContent=m.log;$('verdict').textContent=m.code?'运行 / 检查失败，请看日志':/COURSE_CHECKS_PASSED|SMOKE_PASSED/.test(m.log)?'TB 自检通过':'仿真结束 · 请检查波形';$('verdict').className=m.code?'bad':'ok';
    if(m.vcd){try{ExamWave.load(m.vcd);if(!m.code)tab('wave');}catch(error){$('log').textContent+='\n波形预览失败：'+error.message;}}
  }
  if(m.type==='failure'){running(false);$('log').textContent=m.text;$('verdict').textContent='请检查日志';$('verdict').className='bad';tab('log');}
});
send('ready');
