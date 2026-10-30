# RK3588 SSH 简化操作

电脑已配置原生 SSH 别名 `rk3588`，用已有密钥登录 `cat`。
当前连接地址来自电脑的 `~/.ssh/config`；不用在每次会话中重复输入密码、IP 和用户。
板上任务默认工作目录为 `~/orbslam3_cpu_baseline`。

## 高频命令

新开 PowerShell 后直接执行（PowerShell 7 和 Windows PowerShell 5.1 均已配置）：

```powershell
rk check
rk exec 'uname -a; free -h' -Name environment
rk exec 'bash scripts/build_orbslam3.sh' -Name orb-build
rk status <job_id>
rk wait <job_id> -Seconds 30
rk log <job_id> -Lines 20
rk log <job_id> -Match 'error:|fatal|segmentation|traceback' -Lines 20
rk list
```

`exec` 默认等待最多 30 秒。短命令通常直接返回最终结果；超时仍在运行的任务会返回
job_id 和 STARTING/RUNNING。此时继续 `wait/status`，不重新提交同一条命令。
每次等待最多 60 秒。状态检查默认只返回任务编号、状态、退出码、日志路径和最后 4 条日志。
`list` 最多显示 8 个任务，优先显示未结束或 LOST 的任务，再显示最近结束的任务。

明确希望后台运行时：

```powershell
rk start 'bash scripts/build_orbslam3.sh' -Name orb-build
rk status <job_id>
```

SSH 断开或客户端等待到期不会终止任务，重新连接后可用相同编号查看。
后台作业需要板子保持开机；板子重启或 worker 消失且无最终退出码时显示 LOST，不能视为完成。
stdin 关闭，命令不能交互输入密码或回答安装问题；使用已有免密 SSH、`sudo -n` 和必要的非交互参数。

人手交互登录和传文件仍使用原生工具：

```powershell
ssh rk3588
scp .\file.yaml rk3588:~/orbslam3_cpu_baseline/runtime/
scp rk3588:~/orbslam3_cpu_baseline/reports/a1/acceptance.csv .\
```

`rk shell` 也可打开交互终端。Codex 查询和批任务使用其他动作，不使用交互 shell。

## 输出和完成判定

全部 stdout/stderr 保存在板上：

```text
~/orbslam3_cpu_baseline/runtime/ssh_jobs/<job_id>/output.log
~/orbslam3_cpu_baseline/runtime/ssh_jobs/<job_id>/state.json
~/orbslam3_cpu_baseline/runtime/ssh_jobs/<job_id>/worker.log
```

`output.log` 是完整原始输出；`worker.log` 是监督进程异常诊断。
查看日志默认最多 20 条、约 4,000 个摘录字符；长行截断为 400 字符，ANSI 控制序列和
回车进度条只在显示摘要时处理。完整文件保持不变。`-MaxChars` 可显式调整，最大 12,000。
状态摘要只扫描最后 64 KiB；`log` 默认扫描最后 1 MiB，并注明实际扫描范围。
`-Match` 是 Python 正则，只在扫描范围内筛选，未找到不能证明整份日志没有错误。
需要时使用 `-ScanBytes` 扩大范围，最多 16 MiB，或下载完整日志在电脑上定向检索。

只有 `status=SUCCEEDED exit_code=0` 才表示 shell 命令成功，还需要检查该任务的验收文件。
失败的 `exec/wait/status` 保留真实失败状态，并返回原命令的正退出码；异常负退出码映射为 1，
LOST 返回 3。查看失败日志的 `log` 本身可以成功返回，不改变作业失败状态。
STARTING/RUNNING 的查询退出码 0 只表示查询成功，不能称作实验成功。
同样，`list` 和 `check` 成功不代表所列任务完成。

命令通过 UTF-8 JSON + base64 传输，PowerShell 不拼接命令正文到远端 shell 中。
在 PowerShell 中用单引号包住远端命令，防止 `$变量` 和反引号先在本机展开。
板上任务提供项目的 LD_LIBRARY_PATH/CMAKE_PREFIX_PATH，完整命令和状态保存在本次任务目录。
不要把密码或密钥文本写进任务命令或日志。

## 安装、配置和复现

实现为 Windows PowerShell 客户端 + 板上 Python 3.8 标准库监督进程，
不用额外安装 SSH 插件、tmux 或 Python 第三方包，也不创建自动运行的服务。
复用现有原生 SSH 别名；脚本始终设置 BatchMode，认证失败就退出，不反复尝试密码。

```powershell
.\rk3588\orbslam3_cpu_baseline\scripts\setup_ssh_workflow.ps1
```

此脚本验证现有别名、上传 remote_job.py、更新忽略的 local_board.json、
在两种 PowerShell 的用户 AllHosts profile 中加入一个托管 `rk` 函数。
它保留已有 profile 内容，修改已有文件前备份到主项目 `.work/ssh_setup/`，
重复安装不重复追加函数。已经打开的终端可加载对应 profile，或直接调用入口：

```powershell
. $PROFILE.CurrentUserAllHosts
.\rk3588\orbslam3_cpu_baseline\scripts\rk.ps1 check
```

本机覆盖使用 `local_board.json` 的 `sshAlias/remoteRoot`；模板为 `local_board.example.json`。
板 IP/用户/IdentityFile 在原生 `~/.ssh/config` 管理，私钥与本机配置均不提交。
如果 DHCP 地址变化，更新该别名的 HostName；本次没有修改路由器或声称已验证 DHCP 保留。
移除两种 profile 中 `BEGIN/END PLD RK3588 WORKFLOW` 块即可撤销短命令。
已有 board.ps1 的上传/下载/直接命令接口仍兼容，配置 alias 后也会复用它。

真实 SSH 协议验收可重跑，输出在 `reports/ssh_workflow/acceptance.csv`：

```powershell
. .\scripts\project_env.ps1
& $ProjectPython .\rk3588\orbslam3_cpu_baseline\scripts\test_ssh_workflow.py
```

测试只运行小型 shell 任务，覆盖中文/引号、万行日志的完整保留与摘要、失败退出码、
断开连接后继续运行、等待到期的状态，以及非法任务路径；不启动 ORB 实验。
SSH 修改保留在 `tooling/ssh-workflow` 分支。A1 报告是历史验收快照，实验阶段按用户最新授权推进。
