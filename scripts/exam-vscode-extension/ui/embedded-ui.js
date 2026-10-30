/* Monaco editing, with VS Code's language providers bridged through the host. */
const vscode=acquireVsCodeApi(),$=id=>document.getElementById(id);
const base=$('config').dataset.monaco;
let epoch=0,models=new Map(),tbName='',designName='',snippets=[],compiled=false,busy=false,revision=0,saveTimer,rpcIndex=0;
const requests=new Map();let tbEditor,designEditor;
const diagnosticOwners=new Map(),diagnosticDecorations=new Map();
function fileDiagnostics(name){
  const unique=new Map();
  for(const group of diagnosticOwners.values())for(const marker of group.get(name)||[])unique.set([marker.startLineNumber,marker.startColumn,marker.message].join(':'),marker);
  return [...unique.values()].sort((a,b)=>b.severity-a.severity||a.startLineNumber-b.startLineNumber);
}
function normalizeMarker(model,marker){
  const line=Math.max(1,Math.min(model.getLineCount(),marker.startLineNumber||1));
  const maxColumn=model.getLineMaxColumn(line),text=model.getLineContent(line);
  let start=Math.max(1,Math.min(maxColumn,marker.startColumn||1));
  let endLine=Math.max(line,Math.min(model.getLineCount(),marker.endLineNumber||line));
  let end=Math.max(1,Math.min(model.getLineMaxColumn(endLine),marker.endColumn||maxColumn));
  // Icarus often supplies only a line number. Point at the unresolved symbol
  // when its name is present in the diagnostic instead of marking whitespace.
  const symbol=marker.message.match(/[`']([A-Za-z_$][\w$]*)['`]/)?.[1];
  const index=symbol?text.indexOf(symbol):-1;
  if(index>=0){start=index+1;end=start+symbol.length;endLine=line;}
  else if(endLine===line&&end<=start){start=Math.min(maxColumn,text.search(/\S/)+1||1);end=Math.max(start+1,maxColumn);}
  return {...marker,startLineNumber:line,startColumn:start,endLineNumber:endLine,endColumn:end};
}
function decorateDiagnostics(){
  for(const [name,model] of models){
    const byLine=new Map();
    for(const marker of fileDiagnostics(name))if(marker.severity>=4&&!byLine.has(marker.startLineNumber))byLine.set(marker.startLineNumber,marker);
    const decorations=[...byLine.values()].map(d=>({range:new monaco.Range(d.startLineNumber,1,d.startLineNumber,1),options:{isWholeLine:true,className:d.severity===8?'exam-error-line':'exam-warning-line',glyphMarginClassName:d.severity===8?'exam-error-glyph':'exam-warning-glyph',glyphMarginHoverMessage:{value:d.message},linesDecorationsClassName:d.severity===8?'exam-error-stripe':'exam-warning-stripe'}}));
    diagnosticDecorations.set(name,model.deltaDecorations(diagnosticDecorations.get(name)||[],decorations));
  }
  renderTabs();
}
let editorLayout={ratio:.5,tbHidden:false,designHidden:false},layoutLoaded=false;
function applyEditorLayout(persist=false){
  const l=editorLayout;
  l.ratio=Math.max(.2,Math.min(.8,Number(l.ratio)||.5));
  if(l.tbHidden&&l.designHidden)l.designHidden=false;
  $('editors').style.gridTemplateColumns=l.tbHidden?'42px 12px minmax(0,1fr)':l.designHidden?'minmax(0,1fr) 12px 42px':`minmax(0,${l.ratio}fr) 12px minmax(0,${1-l.ratio}fr)`;
  for(const [side,hidden,label] of [['Tb',l.tbHidden,'TB'],['Design',l.designHidden,'设计']]){
    $(side==='Tb'?'tbPane':'designPane').classList.toggle('is-collapsed',hidden);
    const button=$('toggle'+side);button.textContent=hidden?'展开 '+label:side==='Tb'?'‹ 收起':'收起 ›';
    button.setAttribute('aria-expanded',String(!hidden));button.title=(hidden?'展开':'收起')+label;
  }
  const divider=$('editorDivider'),disabled=l.tbHidden||l.designHidden;
  divider.setAttribute('aria-disabled',String(disabled));divider.tabIndex=disabled?-1:0;
  divider.setAttribute('aria-valuenow',String(Math.round(l.ratio*100)));
  divider.setAttribute('aria-valuetext',disabled?(l.tbHidden?'TB 已收起':'设计已收起'):`左侧 ${Math.round(l.ratio*100)}%，右侧 ${Math.round((1-l.ratio)*100)}%`);
  requestAnimationFrame(()=>{if(!l.tbHidden)tbEditor?.layout();if(!l.designHidden)designEditor?.layout();});
  if(persist){vscode.setState({...vscode.getState(),editorLayout:{...l}});vscode.postMessage({type:'layout',epoch,layout:{...l}});}
}
function toggleEditor(side){
  const key=side==='tb'?'tbHidden':'designHidden',other=side==='tb'?'designHidden':'tbHidden';
  editorLayout[key]=!editorLayout[key];if(editorLayout[key])editorLayout[other]=false;applyEditorLayout(true);
}
$('toggleTb').onclick=()=>toggleEditor('tb');$('toggleDesign').onclick=()=>toggleEditor('design');
let dividerPointer;
const divider=$('editorDivider');
divider.onpointerdown=e=>{
  if(e.button!==0||editorLayout.tbHidden||editorLayout.designHidden)return;
  e.preventDefault();dividerPointer=e.pointerId;divider.setPointerCapture(e.pointerId);document.body.classList.add('resizing-editors');
};
divider.onpointermove=e=>{
  if(e.pointerId!==dividerPointer)return;
  const bounds=$('editors').getBoundingClientRect();editorLayout.ratio=(e.clientX-bounds.left-6)/Math.max(1,bounds.width-12);applyEditorLayout();
};
function finishDivider(e){
  if(e.pointerId!==dividerPointer)return;
  dividerPointer=undefined;document.body.classList.remove('resizing-editors');
  if(divider.hasPointerCapture(e.pointerId))divider.releasePointerCapture(e.pointerId);applyEditorLayout(true);
}
divider.onpointerup=finishDivider;divider.onpointercancel=finishDivider;divider.onlostpointercapture=finishDivider;
divider.ondblclick=()=>{editorLayout.ratio=.5;applyEditorLayout(true);};
divider.onkeydown=e=>{
  if(editorLayout.tbHidden||editorLayout.designHidden)return;
  const step=e.shiftKey?.1:.05;
  if(e.key==='ArrowLeft')editorLayout.ratio-=step;else if(e.key==='ArrowRight')editorLayout.ratio+=step;
  else if(e.key==='Home')editorLayout.ratio=.2;else if(e.key==='End')editorLayout.ratio=.8;
  else if(e.key==='Enter')editorLayout.ratio=.5;else return;
  e.preventDefault();applyEditorLayout(true);
};
function files(){return Array.from(models,([name,model])=>({name,text:model.getValue()}));}
function send(type,extra={}){clearTimeout(saveTimer);vscode.postMessage({type,epoch,revision,files:files(),...extra});}
function request(type,model,position){
  const id=++rpcIndex,name=[...models].find(([,m])=>m===model)?.[0];
  return new Promise(resolve=>{const timer=setTimeout(()=>{requests.delete(id);resolve({items:[],edits:[]});},4000);requests.set(id,{resolve,timer});vscode.postMessage({type,epoch,id,name,text:model.getValue(),line:position?.lineNumber,column:position?.column});});
}
function tab(which){$('log').hidden=which!=='log';$('waveView').hidden=which!=='wave';$('logTab').classList.toggle('selected',which==='log');$('waveTab').classList.toggle('selected',which==='wave');if(which==='wave')requestAnimationFrame(()=>ExamWave.redraw());}
function controls(){for(const id of ['new','import','add','save','compile','question'])$(id).disabled=busy;$('run').disabled=busy||!compiled;$('run').title=compiled?'运行仿真':'请先编译通过';for(const e of [tbEditor,designEditor])e?.updateOptions({readOnly:busy});}
function renderTabs(){
  $('tbTabs').replaceChildren();$('designTabs').replaceChildren();
  for(const [name] of models){
    const isTb=name===tbName,b=document.createElement('button');b.textContent=name;b.className=isTb||name===designName?'active':'';
    const diagnostics=fileDiagnostics(name),errors=diagnostics.filter(d=>d.severity===8).length,warnings=diagnostics.filter(d=>d.severity===4).length;
    if(errors||warnings){const badge=document.createElement('span');badge.className='diagnostic-count '+(errors?'errors':'warnings');badge.textContent=String(errors||warnings);b.append(badge);b.title=`${name}：${errors} 个错误，${warnings} 个警告。F8 跳到下一处。`;}
    b.onclick=()=>{if(!isTb){designName=name;designEditor.setModel(models.get(name));renderTabs();}};$(isTb?'tbTabs':'designTabs').append(b);
  }
}
function runAction(action){
  if(busy)return;if(action==='run'&&!compiled){$('status').textContent='请先点「编译」';return;}
  busy=true;controls();$('status').textContent=action==='compile'?'编译中…':'仿真中…';$('log').textContent=action==='compile'?'正在检查语法与模块连接…':'正在运行仿真…';tab('log');ExamWave.load(null);send(action);
}
function markers(owner,groups){
  const group=new Map();
  for(const [name,model] of models){const normalized=(groups.find(f=>f.name===name)?.markers||[]).map(d=>normalizeMarker(model,d));group.set(name,normalized);monaco.editor.setModelMarkers(model,owner,normalized);}
  diagnosticOwners.set(owner,group);decorateDiagnostics();
}
$('compile').onclick=()=>runAction('compile');$('run').onclick=()=>runAction('run');
for(const id of ['new','import','add','save','fullWave'])$(id).onclick=()=>send(id);
$('question').onchange=()=>send('switch',{question:$('question').value});$('logTab').onclick=()=>tab('log');$('waveTab').onclick=()=>tab('wave');
const pendingMessages=[];let ready=false;
window.addEventListener('message',event=>{if(!ready){pendingMessages.push(event.data);return;}receive(event.data);});
function receive(m){
  if(m.type==='response'){const pending=requests.get(m.id);if(pending){clearTimeout(pending.timer);requests.delete(m.id);pending.resolve(m);}return;}
  if(m.type==='load'){
    clearTimeout(saveTimer);tbEditor.setModel(null);designEditor.setModel(null);for(const model of models.values())model.dispose();models=new Map();diagnosticOwners.clear();diagnosticDecorations.clear();epoch=m.epoch;tbName=m.tb;snippets=m.snippets;revision=0;
    for(const f of m.files){const model=monaco.editor.createModel(f.text,'verilog',monaco.Uri.parse('file:///exam/'+epoch+'/'+encodeURIComponent(f.name)));models.set(f.name,model);model.onDidChangeContent(()=>{
      revision++;compiled=false;controls();$('dirty').textContent='正在保存…';$('status').textContent='代码已改动，请重新编译';$('verdict').textContent='代码已改动 · 编译后再运行';$('verdict').className='';
      diagnosticOwners.clear();for(const current of models.values()){monaco.editor.setModelMarkers(current,'compiler',[]);monaco.editor.setModelMarkers(current,'language',[]);}decorateDiagnostics();clearTimeout(saveTimer);saveTimer=setTimeout(()=>send('sync'),700);
    });}
    designName=models.has(m.preferred)?m.preferred:m.files.find(f=>f.name!==tbName)?.name;
    tbEditor.setModel(models.get(tbName));designEditor.setModel(models.get(designName));renderTabs();
    if(!layoutLoaded){editorLayout={...editorLayout,...(vscode.getState()?.editorLayout||m.layout||{})};layoutLoaded=true;}applyEditorLayout();
    $('question').replaceChildren(...m.questions.map(q=>{const o=document.createElement('option');o.value=q.id;o.textContent=q.name;return o;}));$('question').value=m.question;
    $('location').textContent=m.folder;$('dirty').textContent='已保存';$('status').textContent='先编译，再 Run';$('verdict').textContent='先编译检查，再 Run 仿真';$('verdict').className='';$('log').textContent='已打开本题。点击「编译」检查语法和模块连接。';compiled=false;busy=false;controls();ExamWave.load(null);tab('log');
  }
  if(m.type==='selectDesign'){designName=m.name;designEditor.setModel(models.get(designName));renderTabs();designEditor.focus();}
  if(m.type==='saved'&&m.revision===revision)$('dirty').textContent='已保存';
  if(m.type==='markers'&&m.epoch===epoch&&m.revision===revision&&!compiled)markers('language',m.files);
  if(m.type==='running'){busy=true;controls();}
  if(m.type==='result'){
    busy=false;$('dirty').textContent='已保存';$('log').textContent=m.log;
    if(m.action==='compile'){compiled=!m.code;if(compiled)markers('language',[]);}
    $('status').textContent=m.code?'请检查日志':m.action==='compile'?'编译通过，可 Run':'仿真结束';
    $('verdict').textContent=m.code?'失败 · 请看日志':m.action==='compile'?'编译通过 · 尚未运行仿真':/COURSE_CHECKS_PASSED|SMOKE_PASSED/.test(m.log)?'TB 自检通过':'仿真结束 · 请检查波形';$('verdict').className=m.code?'bad':'ok';
    markers('compiler',[...models.keys()].map(name=>({name,markers:(m.markers||[]).filter(d=>d.name===name)})));
    if(m.vcd){try{ExamWave.load(m.vcd);if(!m.code)tab('wave');}catch(error){$('log').textContent+='\n波形预览失败：'+error.message;}}controls();
  }
  if(m.type==='failure'){busy=false;controls();$('log').textContent=m.text;$('status').textContent='操作未完成';$('verdict').textContent='请检查日志';$('verdict').className='bad';tab('log');}
  if(m.type==='requestRun')runAction('run');
}
window.MonacoEnvironment={getWorkerUrl(){const code='self.MonacoEnvironment={baseUrl:'+JSON.stringify(base+'/')+'};importScripts('+JSON.stringify(base+'/vs/base/worker/workerMain.js')+');';return URL.createObjectURL(new Blob([code],{type:'text/javascript'}));}};
require.config({paths:{vs:base+'/vs'}});
require(['vs/editor/editor.main'],function(){
  monaco.languages.register({id:'verilog'});
  const keywordList='module endmodule input output inout wire reg logic integer parameter localparam assign always always_ff always_comb initial begin end if else case casex casez endcase default posedge negedge or for while repeat function endfunction task endtask generate endgenerate genvar signed unsigned automatic'.split(' ');
  monaco.languages.setMonarchTokensProvider('verilog',{keywords:keywordList,tokenizer:{root:[[/\/\*/,'comment','@comment'],[/\/\/.*$/,'comment'],[/"(?:\\.|[^"\\])*"/,'string'],[/`\w+/,'keyword'],[/\$\w+/,'type.identifier'],[/\b\d+(?:'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+)?\b/,'number'],[/[a-zA-Z_][\w$]*/,{cases:{'@keywords':'keyword','@default':'identifier'}}]],comment:[[/[^/*]+/,'comment'],[/\*\//,'comment','@pop'],[/[/*]/,'comment']]}});
  monaco.languages.setLanguageConfiguration('verilog',{
    comments:{lineComment:'//',blockComment:['/*','*/']},brackets:[['{','}'],['[',']'],['(',')']],autoClosingPairs:[{open:'(',close:')'},{open:'[',close:']'},{open:'{',close:'}'},{open:'"',close:'"',notIn:['string','comment']}],
    indentationRules:{increaseIndentPattern:/^\s*(?!\/\/)(?:(?:module|function|task|generate|fork)\b(?!.*\bend(?:module|function|task|generate)\b).*|.*\bbegin\s*(?::\s*\w+)?\s*(?:\/\/.*)?|(?:case|casex|casez)\s*\(.*\).*)$/,decreaseIndentPattern:/^\s*(?:end(?:module|function|task|generate|case)?|join(?:_any|_none)?)\b/},
    onEnterRules:[{beforeText:/\bbegin\s*$/,afterText:/^\s*end\b/,action:{indentAction:monaco.languages.IndentAction.IndentOutdent}}]
  });
  monaco.languages.registerCompletionItemProvider('verilog',{triggerCharacters:['.','`','$'],async provideCompletionItems(model,position,context,token){
    const word=model.getWordUntilPosition(position),range={startLineNumber:position.lineNumber,endLineNumber:position.lineNumber,startColumn:word.startColumn,endColumn:word.endColumn};
    const native=await Promise.race([request('complete',model,position),new Promise(resolve=>setTimeout(()=>resolve({items:[]}),200))]);if(token.isCancellationRequested)return {suggestions:[]};
    const suggestions=[...snippets,...(native.items||[]),...keywordList.map(label=>({label,kind:'Keyword',insertText:label}))].map(item=>({...item,kind:monaco.languages.CompletionItemKind[item.kind]??monaco.languages.CompletionItemKind.Text,insertTextRules:item.snippet?monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet:undefined,range}));
    return {suggestions};
  }});
  monaco.languages.registerDocumentFormattingEditProvider('verilog',{async provideDocumentFormattingEdits(model){return (await request('format',model)).edits||[];}});
  const options={theme:'vs',automaticLayout:true,glyphMargin:true,renderValidationDecorations:'on',fontFamily:'Consolas, Courier New, monospace',fontSize:14,lineHeight:22,minimap:{enabled:false},scrollBeyondLastLine:false,tabSize:4,insertSpaces:true,detectIndentation:false,autoIndent:'full',quickSuggestions:{other:true,comments:false,strings:false},suggestOnTriggerCharacters:true,snippetSuggestions:'top',wordBasedSuggestions:'currentDocument',padding:{top:12},fixedOverflowWidgets:true,accessibilitySupport:'off'};
  tbEditor=monaco.editor.create($('tbEditor'),options);designEditor=monaco.editor.create($('designEditor'),options);
  for(const editor of [tbEditor,designEditor]){
    editor.addCommand(monaco.KeyMod.CtrlCmd|monaco.KeyCode.KeyS,()=>send('save'));
    editor.addCommand(monaco.KeyMod.CtrlCmd|monaco.KeyMod.Shift|monaco.KeyCode.KeyB,()=>runAction('compile'));
    editor.addCommand(monaco.KeyMod.CtrlCmd|monaco.KeyCode.Enter,()=>runAction('run'));
  }
  ready=true;for(const m of pendingMessages)receive(m);send('ready');
},function(error){$('log').textContent='编辑器加载失败：'+error.message;$('status').textContent='加载失败';});
