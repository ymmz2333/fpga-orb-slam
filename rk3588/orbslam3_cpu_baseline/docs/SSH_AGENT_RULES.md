## RK3588 SSH workflow

- Reuse the native key-authenticated alias `rk3588`; never ask again for the
  host/user/password already configured. Run `rk check` for a compact check.
- The PowerShell `rk` function calls
  `rk3588/orbslam3_cpu_baseline/scripts/rk.ps1`. If profiles are disabled, call
  that script directly. Configuration lives in ignored `local_board.json` and
  native SSH config; do not read or print private keys.
- Use `rk exec 'command' -Name short-name`; commands start in the board project
  root with its library environment. Quote remote command strings with single
  quotes in PowerShell. Use `rk start` only when detached execution is wanted.
- All command output stays on the board in `runtime/ssh_jobs/<job_id>/`.
  Inspect `rk status`, `rk wait ... -Seconds 30`, or bounded `rk log` excerpts.
  Do not dump whole compiler logs or repeatedly return unchanged output.
- An exec wait timeout returns a live job ID. Continue waiting/checking that
  job at intervals no longer than about 60 seconds; do not launch duplicates.
  STARTING/RUNNING is not success. Require SUCCEEDED, exit_code=0, and the
  task's actual acceptance evidence. LOST has no trustworthy exit code.
- For failures first read `rk log <id> -Match 'error:|fatal|traceback|segmentation'`
  and then only the bounded context needed. A tail with no matching lines is
  not proof that the full log contains no errors. Do not retry passwords.
- Operational details: `rk3588/orbslam3_cpu_baseline/docs/SSH_WORKFLOW.md`.
  Respect the user's latest experiment-stage approval. SSH tooling changes
  do not authorize new experiment stages.
