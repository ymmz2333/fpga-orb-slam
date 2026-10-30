#!/usr/bin/env python3
"""One native Windows terminal-state popup for an already-running G1 batch."""
import argparse
import ctypes
import datetime
import json
import pathlib
import time
import winsound

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', required=True)
    parser.add_argument('--pid', required=True, type=int)
    parser.add_argument('--label',default='B3 层数决策轮')
    args = parser.parse_args()
    folder = PROJECT / 'orb_frontend_golden/decision' / (args.batch + '_coordinator')
    claim = folder / 'notification_claim.json'
    with claim.open('x', encoding='utf-8') as f:
        json.dump(dict(batch=args.batch, notifier='Windows native message box',
                       started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat()), f)
    state_path = folder / 'notification_state.json'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100000 | 0x1000, 0, args.pid)

    def save(status, **extra):
        temp = state_path.with_suffix('.tmp')
        temp.write_text(json.dumps(dict(status=status, batch=args.batch,
                        updated_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), **extra),
                        indent=2, ensure_ascii=False), encoding='utf-8')
        temp.replace(state_path)

    save('MONITORING', coordinator_pid=args.pid, poll_s=15, native_popup=True)
    try:
        while True:
            try:
                state = json.loads((folder / 'state.json').read_text(encoding='utf-8'))
            except (FileNotFoundError, json.JSONDecodeError):
                state = {}
            # The formal process may fail shortly before its Windows coordinator
            # notices it. Notification therefore also accepts its atomic final state.
            formal_path = folder.parent / args.batch / 'batch_state.json'
            if formal_path.exists():
                try:
                    formal = json.loads(formal_path.read_text(encoding='utf-8'))
                    if formal.get('status') in ('FAILED', 'FINISHED_AWAIT_LAYER_DECISION'):
                        state = formal
                except json.JSONDecodeError:
                    pass
            status = state.get('status')
            if status == 'FAILED':
                text = 'B3 流程失败，已停止。\n\n阶段：%s\n原因：%s\n\n原始日志已保留；没有自动重跑或替换失败结果。' % (state.get('phase', '未知'), state.get('error', '请运行进度命令查看'))
                break
            if status == 'FINISHED_AWAIT_LAYER_DECISION':
                text = '%s已完成，流程已停止。\n\n正式槽位：90/90；失败槽位：%s（完成不等于全部通过）。\n报告已生成，等待你选择层数；规范 v1.0 尚未更新。' % (args.label,state.get('failed_slots', '见报告'))
                break
            if not handle or kernel.WaitForSingleObject(handle, 0) == 0:
                status = 'LOST'
                text = 'B3 协调器已退出，但没有可靠的完成状态。\n\n这不能判定为成功；请运行进度命令查询。\n没有自动重启批次。'
                break
            time.sleep(15)
        save('POPUP_DISPLAYING', result=status, message=text)
        try:
            winsound.MessageBeep(winsound.MB_ICONHAND if status != 'FINISHED_AWAIT_LAYER_DECISION' else winsound.MB_ICONASTERISK)
        except RuntimeError:
            pass  # An unavailable sound device must not suppress the popup.
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        user.MessageBoxW.restype = ctypes.c_int
        icon = 0x10 if status != 'FINISHED_AWAIT_LAYER_DECISION' else 0x40
        # User explicitly requested a visible popup; only the notification is
        # visible, with no terminal window and no effect on the experiment.
        result = user.MessageBoxW(None, text, 'FPGA ORB · B3 任务通知', 0x40000 | 0x10000 | icon)
        save('ACKNOWLEDGED' if result else 'POPUP_FAILED', result=status, message=text)
    finally:
        if handle:
            kernel.CloseHandle(handle)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
