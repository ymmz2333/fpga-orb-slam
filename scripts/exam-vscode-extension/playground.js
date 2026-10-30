const vscode=require('vscode'),fs=require('fs'),path=require('path'),crypto=require('crypto');
const {execFile}=require('child_process');
function activatePlayground(context){
  const root=vscode.workspace.workspaceFolders?.find(f=>fs.existsSync(path.join(f.uri.fsPath,'.vscode','exam-workspace')))?.uri.fsPath;
  if(!root)return;
  const scripts=path.resolve(root,'..','scripts');
  let view,folder=path.join(root,'examples','smoke'),tbPath,busy=false,lastResult;
  const presets={clock_divider_checkpoint_tb:'clock_divider.v',counter_checkpoint_tb:'counter.v',traffic_fsm_checkpoint_tb:'traffic_fsm.v',traffic_light_tb:'traffic_light_top.v'};
  vscode.commands.executeCommand('setContext','verilogExam',true);
  for(const language of ['verilog','systemverilog'])context.subscriptions.push(vscode.languages.setLanguageConfiguration(language,{
    indentationRules:{
      increaseIndentPattern:/^\s*(?!\/\/)(?:(?:module|function|task|generate|fork)\b(?!.*\bend(?:module|function|task|generate)\b).*|.*\bbegin\s*(?::\s*\w+)?\s*(?:\/\/.*)?|(?:case|casex|casez)\s*\(.*\).*)$/,
      decreaseIndentPattern:/^\s*(?:end(?:module|function|task|generate|case)?|join(?:_any|_none)?)\b/
    },
    onEnterRules:[{beforeText:/\bbegin\s*$/,afterText:/^\s*end\b/,action:{indentAction:vscode.IndentAction.IndentOutdent}}]
  }));
  const post=m=>view?.webview.postMessage(m);
  const codeFiles=()=>fs.readdirSync(folder).filter(n=>/\.(v|sv|tb)$/i.test(n));
  const realModule=file=>/\bmodule\b/.test(fs.readFileSync(file,'utf8').replace(/\/\/[^\n]*/g,''));
  function questions(){return [{id:'examples/smoke',name:'入门示例 · 可直接运行'},...fs.readdirSync(root,{withFileTypes:true}).filter(d=>d.isDirectory()&&!d.name.startsWith('.')&&d.name!=='examples').map(d=>({id:d.name,name:d.name}))];}
  function findTb(){
    const names=codeFiles();
    return names.find(n=>/tb|testbench/i.test(n)&&realModule(path.join(folder,n)))||names.find(n=>/\$finish|\balways\s*#/.test(fs.readFileSync(path.join(folder,n),'utf8')))||names.find(n=>/tb|testbench/i.test(n));
  }
  function state(){post({type:'load',questions:questions(),question:path.relative(root,folder).replace(/\\/g,'/'),folder,tb:tbPath?path.basename(tbPath):''});}
  async function openFiles(){
    let tb=findTb();
    if(!tb){tb='testbench.tb';fs.writeFileSync(path.join(folder,tb),'// 在这里粘贴老师的 testbench，或点击下方「导入 TB」。\n');}
    tbPath=path.join(folder,tb);
    const preferred=presets[path.parse(tb).name]||path.parse(tb).name.replace(/_tb$/i,'')+'.v';
    let design=codeFiles().includes(preferred)?preferred:codeFiles().find(n=>n!==tb&&!/tb|testbench/i.test(n));
    if(!design){design=presets[path.parse(tb).name]||'design.v';fs.writeFileSync(path.join(folder,design),'// 在这里编写你的设计，模块名和端口与左侧 TB 一致。\n');}
    await vscode.window.showTextDocument(vscode.Uri.file(tbPath),{viewColumn:vscode.ViewColumn.One,preview:false,preserveFocus:true});
    await vscode.window.showTextDocument(vscode.Uri.file(path.join(folder,design)),{viewColumn:vscode.ViewColumn.Two,preview:false,preserveFocus:true});
    lastResult=null;state();post({type:'clear'});
  }
  async function save(){if(!await vscode.workspace.saveAll(false))throw Error('请先保存代码。');}
  function fresh(base='practice'){
    const clean=base.replace(/[^\w\u4e00-\u9fff-]/g,'_').slice(0,60)||'practice';let name=clean,index=1;
    while(fs.existsSync(path.join(root,name)))name=clean+'_'+index++;
    folder=path.join(root,name);fs.mkdirSync(folder);
  }
  function runPs(script,args){return new Promise(resolve=>execFile('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-File',path.join(scripts,script),...args],{windowsHide:true,maxBuffer:16*1024*1024},(err,stdout,stderr)=>resolve({code:err?.code||0,log:stdout+stderr})));}
  async function run(){
    if(busy)return;
    try{
      await save();
      const active=vscode.window.activeTextEditor?.document.uri.fsPath;
      if(active&&active.toLowerCase().startsWith((root+path.sep).toLowerCase())&&/\.(v|sv|tb)$/i.test(active)){
        folder=path.dirname(active);const detected=findTb();if(detected)tbPath=path.join(folder,detected);state();
      }
      await vscode.commands.executeCommand('verilog.exam.focus');
      if(!tbPath)throw Error('请先打开练习台或导入 TB。');
      if(!realModule(tbPath))throw Error('请先导入老师的 TB，或在左侧编写 testbench。');
      busy=true;post({type:'running'});lastResult=null;
      const result=await runPs('exam_verilog.ps1',['-Action','sim','-File',tbPath]);
      let vcd=null;const manifest=path.join(folder,'.sim','latest.json');
      if(fs.existsSync(manifest)){
        const wave=JSON.parse(fs.readFileSync(manifest,'utf8')).wave;
        if(fs.statSync(wave).size<=12*1024*1024)vcd=fs.readFileSync(wave,'utf8');
        else result.log+='\n波形超过 12 MB，请用「完整波形」打开。';
      }
      lastResult={type:'result',...result,vcd};post(lastResult);
    }catch(err){post({type:'failure',text:err.message});vscode.window.showErrorMessage(err.message);}
    finally{busy=false;}
  }
  async function receive(m){
    if(m.type==='ready'){state();if(lastResult)post(lastResult);return;}
    if(busy)return;
    try{
      if(m.type==='run'){await run();return;}
      if(m.type==='save'){await save();post({type:'saved'});return;}
      if(['new','switch','import','add'].includes(m.type))await save();
      if(m.type==='new'){fresh();await openFiles();}
      if(m.type==='switch'){
        if(!questions().some(q=>q.id===m.question))throw Error('题目不存在。');folder=path.join(root,m.question);await openFiles();
      }
      if(m.type==='import'){
        const selection=await vscode.window.showOpenDialog({canSelectMany:false,openLabel:'导入老师 TB',filters:{'Verilog TB / ZIP':['v','sv','tb','zip']}});
        if(!selection)return;
        const source=selection[0].fsPath,existing=findTb();
        if(existing&&realModule(path.join(folder,existing)))fresh(path.basename(source).replace(/\.(zip|v|sv|tb)$/i,'').replace(/-testbench$/i,''));
        if(/\.zip$/i.test(source)){
          const result=await runPs('exam_import.ps1',['-Zip',source,'-Destination',folder]);if(result.code)throw Error(result.log);
        }else{
          const dest=path.join(folder,path.basename(source));
          if(fs.existsSync(dest)&&fs.readFileSync(dest,'utf8').replace(/\/\/[^\n]*/g,'').trim())throw Error('同名文件已存在，请先新建题目。');
          fs.copyFileSync(source,dest);
        }
        await openFiles();
      }
      if(m.type==='add'){
        const name=await vscode.window.showInputBox({prompt:'设计文件名',value:'module2.v',validateInput:s=>/^[A-Za-z_][\w$]*\.(v|sv)$/i.test(s)?null:'例如 counter.v'});if(!name)return;
        const target=path.join(folder,name);if(fs.existsSync(target))throw Error('文件已存在。');
        fs.writeFileSync(target,'`timescale 1ns/1ps\nmodule '+path.parse(name).name+' (\n    // 填写端口\n);\n\nendmodule\n');
        await vscode.window.showTextDocument(vscode.Uri.file(target),{viewColumn:vscode.ViewColumn.Two,preview:false});
      }
      if(m.type==='fullWave'){
        const manifest=path.join(folder,'.sim','latest.json');if(!fs.existsSync(manifest))throw Error('请先运行仿真。');
        await vscode.commands.executeCommand('vscode.openWith',vscode.Uri.file(JSON.parse(fs.readFileSync(manifest,'utf8')).wave),'wavetrace.vcd',{viewColumn:vscode.ViewColumn.Two});
      }
    }catch(err){post({type:'failure',text:err.message});}
  }
  context.subscriptions.push(vscode.window.registerWebviewViewProvider('verilog.exam',{
    resolveWebviewView(resolved){
      view=resolved;const w=view.webview;w.options={enableScripts:true,localResourceRoots:[context.extensionUri]};
      const nonce=crypto.randomBytes(16).toString('hex'),uri=name=>w.asWebviewUri(vscode.Uri.joinPath(context.extensionUri,'ui',name)).toString();
      w.html=fs.readFileSync(path.join(context.extensionPath,'ui','native-panel.html'),'utf8').replaceAll('__CSP__',w.cspSource).replaceAll('__NONCE__',nonce).replace('__CSS__',uri('native-panel.css')).replace('__JS__',uri('native-panel.js')).replace('__WAVE__',uri('wave.js'));
      w.onDidReceiveMessage(receive,undefined,context.subscriptions);
    }
  },{webviewOptions:{retainContextWhenHidden:true}}));
  async function open(){await openFiles();await vscode.commands.executeCommand('verilog.exam.focus');}
  context.subscriptions.push(vscode.commands.registerCommand('fpgaTaskButtons.playground',open),vscode.commands.registerCommand('fpgaTaskButtons.playgroundRun',run));
  const bar=vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left,100);bar.text='$(play-circle) Verilog 练习台';bar.command='fpgaTaskButtons.playground';bar.show();context.subscriptions.push(bar);
  open().catch(e=>vscode.window.showErrorMessage(e.message));
}
module.exports={activatePlayground};
