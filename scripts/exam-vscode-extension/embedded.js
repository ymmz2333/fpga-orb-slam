const vscode=require('vscode'),fs=require('fs'),path=require('path'),crypto=require('crypto');
const {execFile}=require('child_process');
function activatePlayground(context){
  const root=vscode.workspace.workspaceFolders?.find(f=>fs.existsSync(path.join(f.uri.fsPath,'.vscode','exam-workspace')))?.uri.fsPath;if(!root)return;
  vscode.commands.executeCommand('setContext','verilogExam',true);
  const scripts=path.resolve(root,'..','scripts');
  let panel,folder=path.join(root,'examples','smoke'),tbName,epoch=0,busy=false,queue=Promise.resolve(),latestComplete=0;
  let checkSerial=0,checkTimer;
  const versions=new Map(),post=m=>panel?.webview.postMessage(m);
  const projectDiagnostics=vscode.languages.createDiagnosticCollection('verilog-exam');context.subscriptions.push(projectDiagnostics);
  const presets={clock_divider_checkpoint_tb:'clock_divider.v',counter_checkpoint_tb:'counter.v',traffic_fsm_checkpoint_tb:'traffic_fsm.v',traffic_light_tb:'traffic_light_top.v'};
  const names=()=>fs.readdirSync(folder).filter(n=>/\.(v|sv|tb)$/i.test(n));
  const content=n=>fs.readFileSync(path.join(folder,n),'utf8');
  const hasModule=n=>/\bmodule\b/.test(content(n).replace(/\/\/[^\n]*/g,''));
  const findTb=()=>names().find(n=>/tb|testbench/i.test(n)&&hasModule(n))||names().find(n=>/\$finish|\balways\s*#/.test(content(n)))||names().find(n=>/tb|testbench/i.test(n));
  function questions(){return [{id:'examples/smoke',name:'入门示例 · 可直接运行'},...fs.readdirSync(root,{withFileTypes:true}).filter(d=>d.isDirectory()&&!d.name.startsWith('.')&&d.name!=='examples').map(d=>({id:d.name,name:d.name}))];}
  function target(name){if(!/^[\w\u4e00-\u9fff.$-]+\.(v|sv|tb)$/i.test(name))throw Error('文件名不能包含路径，扩展名需为 .v / .sv / .tb。');return path.join(folder,name);}
  function snippets(){
    const ext=vscode.extensions.getExtension('mshr-h.veriloghdl');if(!ext)return [];
    try{return Object.entries(JSON.parse(fs.readFileSync(path.join(ext.extensionPath,'snippets','verilog.json'),'utf8'))).flatMap(([name,s])=>(Array.isArray(s.prefix)?s.prefix:[s.prefix]).map(prefix=>({label:prefix,detail:name,documentation:s.description||'',insertText:Array.isArray(s.body)?s.body.join('\n'):s.body,kind:'Snippet',snippet:true})));}catch(_){return [];}
  }
  async function load(){
    projectDiagnostics.clear();
    tbName=findTb();if(!tbName){tbName='testbench.tb';fs.writeFileSync(target(tbName),'// 导入老师的 TB，或在这里编写测试激励。\n');}
    if(!names().some(n=>n!==tbName&&!/tb|testbench/i.test(n)))fs.writeFileSync(target(presets[path.parse(tbName).name]||'design.v'),'// 在这里编写设计，模块名和端口与左侧 TB 一致。\n');
    const files=[];versions.clear();
    for(const name of names()){
      const doc=await vscode.workspace.openTextDocument(vscode.Uri.file(target(name)));versions.set(name,doc.version);files.push({name,text:doc.getText()});
    }
    epoch++;post({type:'load',epoch,questions:questions(),question:path.relative(root,folder).replace(/\\/g,'/'),folder,files,tb:tbName,preferred:presets[path.parse(tbName).name]||path.parse(tbName).name.replace(/_tb$/i,'')+'.v',snippets:snippets(),layout:context.workspaceState.get('examEditorLayout')});
    scheduleCheck(0);
  }
  async function sync(files,save=true){
    for(const file of files||[]){
      const doc=await vscode.workspace.openTextDocument(vscode.Uri.file(target(file.name)));
      if(versions.has(file.name)&&versions.get(file.name)!==doc.version&&doc.getText()!==file.text)throw Error(file.name+' 在另一个编辑器中发生变化。请先保存该编辑器，再用题目下拉框重新打开本题。');
      if(doc.getText()!==file.text){const edits=new vscode.WorkspaceEdit();edits.replace(doc.uri,new vscode.Range(doc.positionAt(0),doc.positionAt(doc.getText().length)),file.text);if(!await vscode.workspace.applyEdit(edits))throw Error('保存失败：'+file.name);}
      versions.set(file.name,doc.version);if(save)await doc.save();
    }
  }
  function compilerMarkers(log){
    const markers=[];
    for(const match of log.matchAll(/^(.+?\.(?:v|sv|tb)):(\d+)(?::(\d+))?:\s*(.+)$/gmi))markers.push({name:path.basename(match[1]),message:match[4],startLineNumber:Number(match[2]),startColumn:Number(match[3]||1),endLineNumber:Number(match[2]),endColumn:999,severity:/warning/i.test(match[4])?4:8});
    return markers;
  }
  function cancelCheck(){checkSerial++;clearTimeout(checkTimer);}
  function publishDiagnostics(markers){
    for(const name of names()){
      const uri=vscode.Uri.file(target(name)),doc=vscode.workspace.textDocuments.find(d=>d.uri.fsPath.toLowerCase()===uri.fsPath.toLowerCase());
      projectDiagnostics.set(uri,markers.filter(d=>d.name===name).map(d=>{
        const line=Math.max(0,Math.min((doc?.lineCount||d.startLineNumber)-1,d.startLineNumber-1));
        const end=doc?doc.lineAt(line).text.length:Math.max(1,d.endColumn-1);
        const diagnostic=new vscode.Diagnostic(new vscode.Range(line,0,line,end),d.message,d.severity===4?vscode.DiagnosticSeverity.Warning:vscode.DiagnosticSeverity.Error);
        diagnostic.source='Icarus · 本题工程';return diagnostic;
      }));
    }
  }
  function scheduleCheck(revision){
    cancelCheck();const serial=checkSerial,checkEpoch=epoch,checkFolder=folder,checkTb=tbName;
    checkTimer=setTimeout(async()=>{
      if(!panel||busy||serial!==checkSerial)return;
      const result=await runPs('exam_verilog.ps1',['-Action','check','-File',path.join(checkFolder,checkTb)]);
      if(!panel||busy||serial!==checkSerial||epoch!==checkEpoch)return;
      const markers=compilerMarkers(result.log);
      publishDiagnostics(markers);
      post({type:'markers',epoch:checkEpoch,revision,files:names().map(name=>({name,markers:markers.filter(d=>d.name===name)}))});
    },250);
  }
  function fresh(base='practice'){const clean=base.replace(/[^\w\u4e00-\u9fff-]/g,'_').slice(0,60)||'practice';let name=clean,i=1;while(fs.existsSync(path.join(root,name)))name=clean+'_'+i++;folder=path.join(root,name);fs.mkdirSync(folder);}
  function runPs(script,args){return new Promise(resolve=>execFile('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-File',path.join(scripts,script),...args],{windowsHide:true,maxBuffer:16*1024*1024},(err,stdout,stderr)=>resolve({code:err?.code||0,log:stdout+stderr})));}
  async function complete(m){
    await sync([{name:m.name,text:m.text}],false);
    const uri=vscode.Uri.file(target(m.name)),position=new vscode.Position(m.line-1,m.column-1);
    const result=await vscode.commands.executeCommand('vscode.executeCompletionItemProvider',uri,position,undefined,20);
    const items=(result?.items||[]).slice(0,200).map(item=>({label:typeof item.label==='string'?item.label:item.label.label,kind:vscode.CompletionItemKind[item.kind]||'Text',detail:item.detail||'',documentation:typeof item.documentation==='string'?item.documentation:item.documentation?.value||'',insertText:item.textEdit?.newText||item.insertText?.value||item.insertText||item.label.label||item.label,snippet:item.insertText instanceof vscode.SnippetString}));
    post({type:'response',id:m.id,items});
  }
  async function receive(m){
    if(m.type==='ready'){await load();return;}
    if(m.epoch!==epoch)return;
    if(m.type==='layout'){
      await context.workspaceState.update('examEditorLayout',{ratio:Math.max(.2,Math.min(.8,Number(m.layout?.ratio)||.5)),tbHidden:m.layout?.tbHidden===true,designHidden:m.layout?.designHidden===true});return;
    }
    try{
      if(m.type==='complete'){if(m.id!==latestComplete){post({type:'response',id:m.id,items:[]});return;}await complete(m);return;}
      if(m.type==='format'){
        await sync([{name:m.name,text:m.text}],false);
        const edits=await vscode.commands.executeCommand('vscode.executeFormatDocumentProvider',vscode.Uri.file(target(m.name)),{tabSize:4,insertSpaces:true});
        post({type:'response',id:m.id,edits:(edits||[]).map(e=>({range:{startLineNumber:e.range.start.line+1,startColumn:e.range.start.character+1,endLineNumber:e.range.end.line+1,endColumn:e.range.end.character+1},text:e.newText}))});return;
      }
      if(busy)return;
      await sync(m.files);
      if(m.type==='save'||m.type==='sync'){post({type:'saved',revision:m.revision});scheduleCheck(m.revision);return;}
      if(m.type==='compile'||m.type==='run'){
        cancelCheck();busy=true;post({type:'running',action:m.type});
        if(!hasModule(tbName))throw Error('请先导入老师的 TB，或在左侧编写 testbench。');
        const result=await runPs('exam_verilog.ps1',['-Action',m.type==='compile'?'compile':'sim','-File',target(tbName)]);
        let vcd=null;
        const manifest=path.join(folder,'.sim','latest.json');
        if(m.type==='run'&&fs.existsSync(manifest)){const wave=JSON.parse(fs.readFileSync(manifest,'utf8')).wave;if(fs.statSync(wave).size<=12*1024*1024)vcd=fs.readFileSync(wave,'utf8');else result.log+='\n波形较大，请点「完整波形」。';}
        const markers=compilerMarkers(result.log);
        publishDiagnostics(markers);
        post({type:'result',action:m.type,...result,vcd,markers});
      }
      if(m.type==='new'){fresh();await load();}
      if(m.type==='switch'){if(!questions().some(q=>q.id===m.question))throw Error('题目不存在。');folder=path.join(root,m.question);await load();}
      if(m.type==='import'){
        const selected=await vscode.window.showOpenDialog({canSelectMany:false,openLabel:'导入老师 TB',filters:{'Verilog TB / ZIP':['v','sv','tb','zip']}});if(!selected)return;
        const source=selected[0].fsPath;if(findTb()&&hasModule(findTb()))fresh(path.basename(source).replace(/\.(zip|v|sv|tb)$/i,'').replace(/-testbench$/i,''));
        if(/\.zip$/i.test(source)){const result=await runPs('exam_import.ps1',['-Zip',source,'-Destination',folder]);if(result.code)throw Error(result.log);}
        else {const dest=target(path.basename(source));if(fs.existsSync(dest)&&hasModule(path.basename(dest)))throw Error('同名文件已存在，请新建题目。');fs.copyFileSync(source,dest);}
        await load();
      }
      if(m.type==='add'){
        const name=await vscode.window.showInputBox({prompt:'新建设计文件名',value:'module2.v',validateInput:s=>/^[A-Za-z_][\w$]*\.(v|sv)$/i.test(s)?null:'例如 counter.v'});if(!name)return;
        if(fs.existsSync(target(name)))throw Error('文件已存在。');fs.writeFileSync(target(name),'`timescale 1ns/1ps\nmodule '+path.parse(name).name+' (\n    // 填写端口\n);\n\nendmodule\n');await load();post({type:'selectDesign',name});
      }
      if(m.type==='fullWave'){
        const manifest=path.join(folder,'.sim','latest.json');if(!fs.existsSync(manifest))throw Error('请先 Run 生成波形。');
        await vscode.commands.executeCommand('vscode.openWith',vscode.Uri.file(JSON.parse(fs.readFileSync(manifest,'utf8')).wave),'wavetrace.vcd',{viewColumn:vscode.ViewColumn.Beside});
      }
    }catch(err){if(m.id)post({type:'response',id:m.id,items:[],error:err.message});else post({type:'failure',text:err.message});}
    finally{busy=false;}
  }
  async function open(){
    await vscode.commands.executeCommand('workbench.action.closePanel');
    await vscode.commands.executeCommand('workbench.action.editorLayoutSingle');
    if(panel){panel.reveal();return;}
    panel=vscode.window.createWebviewPanel('verilogEmbedded','Verilog 练习台',vscode.ViewColumn.One,{enableScripts:true,retainContextWhenHidden:true,localResourceRoots:[context.extensionUri]});
    const w=panel.webview,nonce=crypto.randomBytes(16).toString('hex'),uri=n=>w.asWebviewUri(vscode.Uri.joinPath(context.extensionUri,'ui',n)).toString();
    w.html=fs.readFileSync(path.join(context.extensionPath,'ui','embedded.html'),'utf8').replaceAll('__CSP__',w.cspSource).replaceAll('__NONCE__',nonce).replace('__CSS__',uri('embedded.css')).replace('__JS__',uri('embedded-ui.js')).replace('__WAVE__',uri('wave.js')).replace('__LOADER__',uri('monaco/vs/loader.js')).replace('__MONACO__',uri('monaco'));
    w.onDidReceiveMessage(m=>{if(m.type==='complete')latestComplete=m.id;queue=queue.then(()=>receive(m)).catch(e=>post({type:'failure',text:e.message}));},undefined,context.subscriptions);
    panel.onDidDispose(()=>{cancelCheck();panel=undefined;});
  }
  context.subscriptions.push(vscode.commands.registerCommand('fpgaTaskButtons.playground',open),vscode.commands.registerCommand('fpgaTaskButtons.playgroundRun',()=>{open();post({type:'requestRun'});}));
  const bar=vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left,100);bar.text='$(play-circle) Verilog 练习台';bar.command='fpgaTaskButtons.playground';bar.show();context.subscriptions.push(bar);open();
}
module.exports={activatePlayground};
