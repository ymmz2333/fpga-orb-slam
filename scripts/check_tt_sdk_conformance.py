"""Live wire-format checks plus retained offline SDK FIFO reference checks.

Only selected AST methods run, with in-memory transport/action doubles.
No SDK imports, examples, sockets, devices, or real flight are executed.
The live 3-of-5 policy intentionally differs from the reference dispatcher.
"""
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import random
import re
import threading
from types import SimpleNamespace

from tt_sdk_actions import FlightActions, recognized_reply, reply_state
from tt_controller_core import Controller, Pad, encode_command
from tt_quorum_actions import QuorumFlightActions

COMMIT = 'ff6646e115ab125af3207a4ed3df42cc76c795b2'
HASHES = {
    'flight.py': '7b7a37dd8077a808119c380e7c0ed47d9ea1d026deeebe8e5ee8f7534a5a71eb',
    'action.py': '2b9ff3f26d4f28fd2b40e376740c4f799b93167c4572ed4a68a36deaf4c1fc39',
}


def method(tree, cls, name):
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    node = copy.deepcopy(next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == name))
    node.decorator_list = []
    return node


def evaluate(node, namespace):
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, '<pinned DJI TT source method>', 'exec'), namespace)
    return namespace[node.name]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument('--reference', type=Path,
                        default=root / '.work' / 'tt-sdk-reference' / COMMIT)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    trees = {}
    for filename, expected in HASHES.items():
        data = (args.reference / filename).read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise RuntimeError(f'Unverified official source: {filename}: {actual}')
        trees[filename] = ast.parse(data.decode('utf-8'))
    log = SimpleNamespace(debug=lambda *a: None, info=lambda *a: None, error=lambda *a: None,
                          warning=lambda *a: None)
    namespace = dict(re=re, logger=log, ACTION_SUCCEEDED='ok', ACTION_FAILED='error')
    update = evaluate(method(trees['action.py'], 'TextAction', '_update_action_state'), namespace)
    found = evaluate(method(trees['action.py'], 'TextAction', 'found_action'), namespace)
    dispatch = evaluate(method(trees['action.py'], 'ActionDispatcher', '_on_recv'), namespace)

    parser_cases = ['ok','error','out of range','error No valid marker','unactive',
                    'Re0101 error','Re001 ok','garbage','Re0101 okay','Re0101 ok trailing']
    parser_cases += [f'Re{label:02d}{i:02d} ok' for label in (0,1,2,7,42,82,99)
                     for i in (0,1,2,3,4,5,6,99)]
    for reply in parser_cases:
        state = ['pending']
        target = SimpleNamespace(_changeto_state=lambda s: state.__setitem__(0,s))
        expected_found = found(target, SimpleNamespace(_action_state=reply))
        update(target, reply)
        assert recognized_reply(reply) == expected_found, reply
        assert reply_state(reply) == state[0], reply

    # Actual official methods, but the dispatcher/client only append Python strings.
    flight_namespace = dict(logger=log, random=random)
    flight_namespace['FlightAction'] = lambda cmd: SimpleNamespace(text_cmd=cmd)
    flight_namespace['protocol'] = SimpleNamespace(
        TextProtoDrone=lambda: SimpleNamespace(),
        TextMsg=lambda proto: SimpleNamespace(proto=proto))
    official_methods = {name: evaluate(method(trees['flight.py'], 'Flight', name), flight_namespace)
                        for name in ('takeoff','land','stop','rc')}
    # Feed the full-range input mapping into the real official rc method as well.
    controller = Controller()
    pads = [Pad(True), Pad(True, 32767, 32767, 32767, 32767),
            Pad(True, -32768, -32768, -32768, -32768)]
    pads += [Pad(connected=True, **{field: raw}) for field in ('rx','ry','ly','lx')
             for raw in (-32768, 32767)]
    rc_vectors = [(-15,30,0,7)] + [controller.mapped(pad) for pad in pads]
    packet_cases = 0
    for label in (0,42,82,99):
        sent = []
        fake_flight = SimpleNamespace(_cmd_label=label, _retry_times=5,
            _action_dispatcher=SimpleNamespace(send_action=lambda a: sent.append(a.text_cmd)),
            _client=SimpleNamespace(send_async_msg=lambda msg: sent.append(msg.proto.text_cmd)))
        ours = FlightActions(label)
        for name in ('takeoff','land','stop'):
            sent.clear()
            returned = official_methods[name](fake_flight)
            assert list(ours.request(name, 0)) == sent
            assert returned.text_cmd == sent[-1]
            packet_cases += 1
        for channels in rc_vectors:
            sent.clear()
            official_methods['rc'](fake_flight, *channels)
            command = 'rc ' + ' '.join(map(str, channels))
            assert sent == [encode_command(command, motion_enabled=True).decode('ascii')]
            packet_cases += 1

    # The following is the RETAINED REFERENCE dispatcher, no longer live policy.
    dispatch_checks = 0
    for concurrent in (False, True):
        dispatcher = SimpleNamespace(_in_progress={}, _in_progress_mutex=threading.Lock())
        class TextActionDouble:
            def __init__(self, target):
                self.target, self.state = target, 'pending'
            def found_proto(self, _proto):
                return False
            def found_action(self, proto):
                return found(self, proto)
            @property
            def is_running(self):
                return self.state == 'pending'
            def _changeto_state(self, state):
                self.state = state
                if state in ('ok','error'):
                    dispatcher._in_progress.pop(self.target)
            def update_from_push(self, proto):
                update(self, proto._action_state)
        namespace['TextAction'] = TextActionDouble
        ours = FlightActions(82)
        groups = []
        def add_group(name):
            group = [TextActionDouble(p.split()[0]) for p in ours.request(name,0)]
            groups.append(group)
            for action in group:
                dispatcher._in_progress[action.target] = action
        add_group('takeoff')
        if concurrent:
            add_group('land')
        for label in (1,2):
            if label == 2 and not concurrent:
                add_group('land')
            for i in range(1,6):
                reply = f'Re{label:02d}{i:02d} ok'
                proto = SimpleNamespace(_action_state=reply)
                dispatch(None, dispatcher, SimpleNamespace(get_proto=lambda: proto))
                ours.receive(reply)
                for idx, group in enumerate(groups):
                    assert ours.history[idx].copies == [a.state for a in group]
                dispatch_checks += 1

    live_wire_checks = 0
    for label in (0,42,82,99):
        sent = []
        fake_flight = SimpleNamespace(_cmd_label=label, _retry_times=5,
            _action_dispatcher=SimpleNamespace(send_action=lambda a: sent.append(a.text_cmd)))
        live_actions = QuorumFlightActions(label)
        for name in ('takeoff','land'):
            sent.clear()
            official_methods[name](fake_flight)
            assert list(live_actions.request(name, 0)) == sent
            live_wire_checks += 1
        sent.clear()
        official_methods['stop'](fake_flight, retry=False)
        assert sent == [encode_command('stop').decode('ascii')]
        live_wire_checks += 1

    report = dict(result='PASS', official_commit=COMMIT, source_sha256=HASHES,
                  parser_cases=len(parser_cases), packet_cases=packet_cases,
                  dispatcher_comparisons=dispatch_checks, network_used=False,
                  live_wire_comparisons=live_wire_checks,
                  dispatcher_scope='legacy offline reference only, not live control',
                  live_policy='3 distinct copy OKs; 12s takeoff deadline; separate bare stop',
                  live_policy_matches_official_fifo=False,
                  sdk_package_imported=False, real_flight_verified=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
