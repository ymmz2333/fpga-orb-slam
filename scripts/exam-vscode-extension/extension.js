const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const {execFile} = require('child_process');
function activate(context) {
  require('./embedded').activatePlayground(context);
  const labels = {
    compile: 'FPGA: compile current file (elaborate only)',
    simulate: 'FPGA: simulate current file (auto-detect testbench)',
    wave: 'FPGA: open latest waveform in VS Code (WaveTrace)'
  };
  function root() {
    const folder = vscode.workspace.workspaceFolders?.find(f => fs.existsSync(path.join(f.uri.fsPath, '.vscode', 'exam-workspace')));
    if (!folder) throw Error('请先打开 D:\\pld\\exam_verilog 文件夹。');
    return folder.uri.fsPath;
  }
  function register(name, fn) {
    context.subscriptions.push(vscode.commands.registerCommand(name, async () => {
      try { await fn(); } catch(e) { vscode.window.showErrorMessage(String(e.message || e)); }
    }));
  }
  async function newQuestion() {
    const base = root();
    const name = await vscode.window.showInputBox({prompt:'新题目文件夹名称（例如 practice1）', validateInput:s => /^[\w\u4e00-\u9fff-]+$/.test(s) ? null : '仅使用字母、数字、中文、下划线或短横线'});
    if (!name) return;
    const folder = path.join(base,name);
    if (fs.existsSync(folder)) throw Error('文件夹已存在，请选择其他名称。');
    fs.mkdirSync(folder);
    await vscode.commands.executeCommand('revealInExplorer',vscode.Uri.file(folder));
    return folder;
  }
  async function chooseQuestion() {
    const base = root();
    const names = fs.readdirSync(base,{withFileTypes:true}).filter(d=>d.isDirectory() && !d.name.startsWith('.') && d.name!=='examples').map(d=>d.name);
    const choice = await vscode.window.showQuickPick(['＋ 新建题目',...names],{placeHolder:'选择本题文件夹'});
    if (!choice) return;
    return choice === '＋ 新建题目' ? await newQuestion() : path.join(base,choice);
  }
  register('fpgaTaskButtons.newQuestion',newQuestion);
  register('fpgaTaskButtons.newDesign',async()=>{
    const folder = await chooseQuestion(); if(!folder) return;
    const name = await vscode.window.showInputBox({prompt:'设计模块名称（例如 counter，不含 .v）',validateInput:s=>/^[A-Za-z_][\w$]*$/.test(s)?null:'请输入合法的 Verilog 模块名'});
    if(!name) return;
    const file=path.join(folder,name+'.v');
    if(fs.existsSync(file)) throw Error('文件已存在，请直接打开编辑。');
    fs.writeFileSync(file,'`timescale 1ns/1ps\nmodule '+name+' (\n    // 按题面和 TB 填写端口\n);\n\n    // 在这里编写设计\n\nendmodule\n');
    await vscode.window.showTextDocument(vscode.Uri.file(file));
  });
  register('fpgaTaskButtons.importTb',async()=>{
    const base=root();
    const zip=await vscode.window.showOpenDialog({canSelectMany:false,filters:{'老师的 TB 压缩包':['zip']},openLabel:'导入 TB'});
    if(!zip) return;
    const folder=await chooseQuestion(); if(!folder) return;
    await vscode.window.withProgress({location:vscode.ProgressLocation.Notification,title:'正在导入 TB'},()=>new Promise((resolve,reject)=>{
      execFile('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-File',path.join(base,'..','scripts','exam_import.ps1'),'-Zip',zip[0].fsPath,'-Destination',folder],{windowsHide:true},(err,out,stderr)=>err?reject(Error(stderr||out||err.message)):resolve());
    }));
    const files=fs.readdirSync(folder).filter(n=>/\.(v|sv)$/i.test(n));
    const tb=files.find(n=>/tb|testbench/i.test(n))||files[0];
    if(tb) await vscode.window.showTextDocument(vscode.Uri.file(path.join(folder,tb)));
    vscode.window.showInformationMessage('导入完成。请将设计文件放在 TB 同一文件夹。');
  });
  for(const [action,label] of Object.entries(labels)) register('fpgaTaskButtons.'+action,async()=>{
    let base; try {base=root();} catch(_) {}
    if(!base) return vscode.commands.executeCommand('workbench.action.tasks.runTask',label);
    if(!await vscode.workspace.saveAll(false)) throw Error('请先保存代码。');
    const active=vscode.window.activeTextEditor?.document.uri.fsPath;
    if(!active || !/\.(v|sv)$/i.test(active)) throw Error('请先打开本题的 Verilog 文件。');
    const task=(await vscode.tasks.fetchTasks()).find(t=>t.name===label);
    if(!task) throw Error('没有找到工作区任务，请重新打开考试文件夹。');
    let execution;
    const listener=vscode.tasks.onDidEndTaskProcess(async e=>{
      if(e.execution!==execution) return;
      listener.dispose();
      if(action!=='simulate') return;
      if(e.exitCode!==0) vscode.window.showErrorMessage('仿真或 TB 检查失败，请看终端；已有波形仍可调试。');
      const manifest=path.join(path.dirname(active),'.sim','latest.json');
      if(fs.existsSync(manifest)) {
        try {
          const wave=JSON.parse(fs.readFileSync(manifest,'utf8')).wave;
          await vscode.commands.executeCommand('vscode.openWith',vscode.Uri.file(wave),'wavetrace.vcd',{viewColumn:vscode.ViewColumn.Beside,preserveFocus:true});
        } catch(err) {vscode.window.showErrorMessage('波形打开失败：'+err.message);}
      }
    });
    context.subscriptions.push(listener);
    execution=await vscode.tasks.executeTask(task);
  });
}
module.exports={activate,deactivate(){}};
