"""Offline TT SDK/input contract. No aircraft sockets, ARP, or real flight.

Old custom-gate tests were superseded by the user's 2026-09-03 contract change,
not relabelled as passing. Pre-change sources/tests are retained in .work.
"""
from dataclasses import replace
import json
import multiprocessing as mp
from pathlib import Path
import queue
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tt_controller_core import (Controller, Health, Keys, LB, RB, Pad, ZERO, SETUP, axis,
                                encode_command, DEFAULT_RC_LIMIT, DEFAULT_SIGNS, DEFAULT_XY_EXPO,
                                DEFAULT_CENTER_STOP_DELAY)
from tt_sdk_actions import FlightActions, recognized_reply, reply_state
from tt_quorum_actions import QuorumFlightActions, DEFAULT_TAKEOFF_TIMEOUT


class ImmediateQueue(queue.Queue):
    def cancel_join_thread(self):
        pass


class PolicyTests(unittest.TestCase):
    def setUp(self):
        # Retain the old configurable fixture for unchanged flight-lifecycle tests.
        # New default mapping is checked independently in MappingTests.
        self.c = Controller(limit=30, signs=(-1, 1, 1, 1))
        self.t = 100.
        self.pad = Pad(True)
        self.health = Health(0, 0, 0, 0, 0, 80)
        self.sent = []

    def step(self, *, pad=None, keys=Keys(), health=None, focused=True, gui_age=0,
             close=False, takeoff_status='pending', land_status='pending'):
        self.t += .05
        out = self.c.tick(self.t, pad or self.pad, keys, health or self.health,
                          focused=focused, gui_age=gui_age, close=close,
                          takeoff_status=takeoff_status, land_status=land_status)
        for value in out:
            encode_command(value, takeoff_enabled=self.c.mode == 'TAKING_OFF',
                           motion_enabled=self.c.mode == 'FLYING', rc_limit=self.c.limit)
        self.sent.extend(out)
        return out

    def ticks(self, count, **kwargs):
        return [v for _ in range(count) for v in self.step(**kwargs)]

    def takeoff(self):
        self.step()  # Released controls, NOT a software-enable key.
        self.ticks(23, pad=replace(self.pad, lt=255, rt=255))
        self.assertEqual(self.c.mode, 'TAKING_OFF')

    def flying(self):
        self.takeoff()
        self.step(takeoff_status='ok')
        self.assertEqual(self.c.mode, 'FLYING')

    def test_startup_does_not_fly_without_gesture(self):
        self.ticks(100)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.c.mode, 'READY')

    def test_startup_held_triggers_require_release_then_new_gesture(self):
        self.ticks(100, pad=replace(self.pad, lt=255, rt=255))
        self.assertEqual(self.sent, [])
        self.takeoff()
        self.assertEqual(self.sent.count('takeoff'), 1)

    def test_takeoff_without_u_and_hold_is_single_shot(self):
        self.takeoff()
        self.ticks(100, pad=replace(self.pad, lt=255, rt=255))
        self.assertEqual(self.sent, ['takeoff'])

    def test_partial_combo_and_short_hold_do_not_trigger(self):
        self.step()
        self.ticks(50, pad=replace(self.pad, lt=255))
        self.ticks(12, pad=replace(self.pad, lt=255, rt=255))
        self.step()
        self.ticks(12, pad=replace(self.pad, lt=255, rt=255))
        self.assertEqual(self.sent, [])

    def test_no_height_battery_video_or_stick_center_gate_on_takeoff(self):
        self.step(health=Health())
        self.ticks(23, pad=replace(self.pad, lt=255, rt=255, rx=32767),
                   health=Health(battery=5, height=float('nan')))
        self.assertEqual(self.sent, ['takeoff'])

    def test_sdk_ack_immediately_enables_rc_without_dwell_or_height(self):
        self.takeoff()
        out = self.step(takeoff_status='ok', pad=replace(self.pad, ry=32767),
                        health=Health())
        self.assertEqual(out, ['rc 0 30 0 0'])
        self.assertEqual(self.c.mode, 'FLYING')

    def test_missing_reply_waits_then_lands_once_at_requested_deadline(self):
        self.takeoff()
        self.t = self.c.takeoff_at + 11.8
        self.step(health=Health(), focused=False, gui_age=10)
        self.assertEqual(self.sent, ['takeoff'])
        self.t = self.c.takeoff_at + 12
        self.ticks(1000, health=Health(), focused=False, gui_age=10)
        self.assertEqual(self.c.mode, 'LANDING')
        self.assertEqual(self.sent, ['takeoff','land'])

    def test_video_focus_gui_battery_and_stalls_do_not_interrupt_rc(self):
        self.flying()
        self.t += 10
        out = self.ticks(150, focused=False, gui_age=100,
                         health=Health(battery=3),
                         pad=replace(self.pad, rx=32767))
        self.assertTrue(out)
        self.assertEqual(set(out), {'rc -30 0 0 0'})
        self.assertEqual(self.c.mode, 'FLYING')
        self.assertNotIn('land', self.sent)
        self.assertNotIn('stop', self.sent)

    def test_disconnected_pad_produces_zero_input_not_autoland(self):
        self.flying()
        out = self.ticks(150, pad=Pad(False, rx=32767))
        self.assertEqual(set(out), {ZERO})
        self.assertNotIn('land', self.sent)
        self.assertNotIn('stop', self.sent)

    def test_h_and_u_are_operator_controls_without_ack_or_neutral_gate(self):
        self.flying()
        self.assertEqual(self.step(keys=Keys(hover=True)), ['stop'])
        self.assertEqual(self.step(pad=replace(self.pad, rx=32767)), [ZERO])
        self.assertEqual(self.step(keys=Keys(enable=True),
                                   pad=replace(self.pad, rx=32767)), ['rc -30 0 0 0'])

    def test_keyboard_only_in_foreground_xbox_land_in_background(self):
        self.step(keys=Keys(hover=True, land=True, enable=True), focused=False)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.step(focused=False, pad=replace(self.pad, buttons=LB|RB)), ['land'])

    def test_land_wins_over_all_other_inputs(self):
        self.flying()
        self.assertEqual(self.step(keys=Keys(enable=True, hover=True, land=True),
                                   pad=replace(self.pad, lt=255, rt=255, buttons=LB|RB)), ['land'])
        self.assertEqual(self.c.mode, 'LANDING')

    def test_held_land_no_repeated_group_or_rc_during_landing(self):
        self.flying()
        self.step(pad=replace(self.pad, buttons=LB|RB))
        self.assertEqual(self.ticks(100, pad=replace(self.pad, buttons=LB|RB, rx=32767)), [])
        self.assertEqual(self.sent.count('land'), 1)

    def test_land_completion_allows_next_flight_without_restart(self):
        self.flying()
        self.step(keys=Keys(land=True))
        self.step(land_status='ok', health=Health())  # No physical-height gate.
        self.assertEqual(self.c.mode, 'READY')
        self.takeoff()
        self.assertEqual(self.sent.count('takeoff'), 2)

    def test_held_takeoff_during_land_is_not_a_new_takeoff_gesture(self):
        self.flying()
        self.step(keys=Keys(land=True))
        held = replace(self.pad, lt=255, rt=255)
        self.step(pad=held, land_status='ok')
        self.ticks(50, pad=held)
        self.assertEqual(self.sent.count('takeoff'), 1)
        self.takeoff()
        self.assertEqual(self.sent.count('takeoff'), 2)

    def test_explicit_takeoff_failure_requests_land_without_rc(self):
        self.takeoff()
        self.step(takeoff_status='error')
        self.ticks(100)
        self.assertEqual(self.c.mode, 'LANDING')
        self.assertEqual(self.sent, ['takeoff','land'])

    def test_close_requests_one_land_but_ground_close_sends_nothing(self):
        self.assertEqual(self.step(close=True), [])
        self.setUp()
        self.flying()
        self.assertEqual(self.step(close=True), ['land'])
        self.assertEqual(self.ticks(100, close=True), [])
        self.step(close=True, land_status='ok')
        self.assertFalse(self.c.possibly_airborne)

    def test_mapping_deadzone_signs_and_full_official_range(self):
        for value in (-2122, -858, 830, -777, 0):
            self.assertEqual(axis(value), 0)
        self.assertEqual(axis(-32768, limit=30), -30)
        self.assertEqual(axis(32767, limit=30), 30)
        self.assertEqual(self.c.mapped(Pad(True, 32767, 32767, 32767, 32767)), (-30, 30, 30, 30))
        self.assertEqual(Controller(100).mapped(Pad(True, 32767, 32767, 32767, 32767)), (100,100,100,100))
        self.assertEqual(Controller(limit=30, signs=(1,1,1,1)).mapped(Pad(True, rx=32767)), (30,0,0,0))


class MappingTests(unittest.TestCase):
    def test_each_default_axis_reaches_both_operator_cap_endpoints(self):
        controller = Controller()
        self.assertEqual(controller.limit, 30)
        self.assertEqual(controller.signs, (1, 1, 1, 1))
        for index, field in enumerate(('rx', 'ry', 'ly', 'lx')):
            for raw, channel in ((-32768, -30), (0, 0), (32767, 30)):
                with self.subTest(field=field, raw=raw):
                    expected = [0, 0, 0, 0]
                    expected[index] = channel
                    mapped = controller.mapped(replace(Pad(True), **{field: raw}))
                    self.assertEqual(mapped, tuple(expected))
                    command = 'rc ' + ' '.join(map(str, mapped))
                    self.assertEqual(encode_command(command, motion_enabled=True), command.encode())

    def test_right_stick_left_is_negative_roll_after_takeoff_ack(self):
        controller = Controller()
        controller.mode = 'TAKING_OFF'
        controller.possibly_airborne = True
        for raw, expected in ((-32768, 'rc -30 0 0 0'), (32767, 'rc 30 0 0 0')):
            self.assertEqual(controller.tick(1, Pad(True, rx=raw), Keys(), Health(),
                                              focused=True, takeoff_status='ok'), [expected])

    def test_full_input_domain_is_monotonic_bounded_and_keeps_deadzone(self):
        values = [axis(raw) for raw in range(-32768, 32768)]
        self.assertEqual((min(values), max(values)), (-30, 30))
        self.assertTrue(all(a <= b for a, b in zip(values, values[1:])))
        self.assertTrue(all(axis(raw) == 0 for raw in range(-4915, 4916)))
        self.assertEqual(axis(-99999), -30)
        self.assertEqual(axis(99999), 30)

    def test_explicit_custom_limits_and_signs_still_work(self):
        for limit in (1, 15, 30, 100):
            self.assertEqual(Controller(limit, (-1, 1, 1, 1)).mapped(Pad(True, rx=32767)),
                             (-limit, 0, 0, 0))

    def test_python_cli_and_powershell_defaults_agree(self):
        from tt_xbox_station import build_parser
        args = build_parser().parse_args([])
        self.assertFalse(args.live)
        self.assertEqual(args.rc_limit, DEFAULT_RC_LIMIT)
        self.assertEqual(tuple(args.signs), DEFAULT_SIGNS)
        self.assertEqual(args.xy_expo, DEFAULT_XY_EXPO)
        self.assertEqual(args.center_stop_delay, DEFAULT_CENTER_STOP_DELAY)
        launcher = Path(__file__).with_name('run_tt_xbox.ps1').read_text(encoding='utf-8')
        for name, value in zip(('RcLimit','RollSign','PitchSign','VerticalSign','YawSign'),
                               (DEFAULT_RC_LIMIT, *DEFAULT_SIGNS)):
            match = re.search(r'\[int\]\$' + name + r'\s*=\s*(-?\d+)', launcher)
            self.assertIsNotNone(match, name)
            self.assertEqual(int(match[1]), value, name)
        match = re.search(r'\[double\]\$XYExpo\s*=\s*([\d.]+)', launcher)
        self.assertIsNotNone(match)
        self.assertEqual(float(match[1]), DEFAULT_XY_EXPO)
        match = re.search(r'\[double\]\$CenterStopDelay\s*=\s*([\d.]+)', launcher)
        self.assertIsNotNone(match)
        self.assertEqual(float(match[1]), DEFAULT_CENTER_STOP_DELAY)
        custom = build_parser().parse_args(['--rc-limit','15','--signs','-1','1','1','1'])
        self.assertEqual((custom.rc_limit, tuple(custom.signs)), (15, (-1, 1, 1, 1)))


class SDKTransactionTests(unittest.TestCase):
    """Preserved SDK FIFO reference only, NOT the current live-flight policy."""
    def test_five_packets_match_official_and_labels_wrap(self):
        actions = FlightActions(first_label=99)
        self.assertEqual(actions.request('takeoff', 0), tuple(f'Re990{i} takeoff' for i in range(1,6)))
        self.assertEqual(actions.request('land', 1), tuple(f'Re000{i} land' for i in range(1,6)))

    def test_recorded_rewritten_ids_complete_takeoff_and_land(self):
        # Actual session: .work/tt-xbox/20260903T215831_855748/events.jsonl
        actions = FlightActions(first_label=82)
        actions.request('takeoff', 0)
        for i in range(1,6):
            self.assertIsNotNone(actions.receive(f'Re010{i} ok'))
            self.assertEqual(actions.state('takeoff'), 'ok' if i == 5 else 'pending')
        actions.request('land', 10)
        for i in range(1,6):
            actions.receive(f'Re020{i} ok')
        self.assertEqual(actions.state('land'), 'ok')
        self.assertEqual(actions.snapshot()['takeoff']['replies'][0], 'Re0101 ok')
        self.assertEqual(actions.snapshot()['land']['replies'][-1], 'Re0205 ok')

    def test_reply_labels_are_not_hardcoded_to_01_or_02(self):
        for response_group in (0, 7, 42, 82, 99):
            actions = FlightActions(first_label=33)
            actions.request('takeoff', 0)
            for i in range(1,6):
                actions.receive(f'Re{response_group:02d}{i:02d} ok')
            self.assertEqual(actions.state('takeoff'), 'ok')

    def test_bare_replies_supported_like_official_sdk(self):
        actions = FlightActions(42)
        actions.request('takeoff', 0)
        for _ in range(5):
            actions.receive('ok')
        self.assertEqual(actions.state('takeoff'), 'ok')

    def test_returned_final_copy_semantics_and_no_automatic_timeout(self):
        actions = FlightActions(42)
        actions.request('takeoff', 0)
        for _ in range(4):
            actions.receive('ok')
        self.assertEqual(actions.state('takeoff'), 'pending')
        actions.receive('error')
        self.assertEqual(actions.state('takeoff'), 'error')
        self.assertFalse(hasattr(actions, 'expire'))

    def test_other_official_responses_are_reported_not_reclassified(self):
        self.assertTrue(recognized_reply('out of range'))
        self.assertTrue(recognized_reply('error No valid marker'))
        self.assertEqual(reply_state('out of range'), 'pending')
        for reply in ('bat:80;', 'Re123 ok', 'garbage', 'Re0101 error'):
            self.assertFalse(recognized_reply(reply))

    def test_sdk_fifo_behavior_including_weak_duplicate_correlation(self):
        actions = FlightActions(82)
        actions.request('takeoff', 0)
        actions.request('land', 1)
        # SDK semantics: even identical successful datagrams consume pending copies.
        # This is deliberately not claimed to deduplicate or authenticate an action.
        for _ in range(5):
            actions.receive('Re0101 ok')
        self.assertEqual(actions.state('takeoff'), 'ok')
        self.assertEqual(actions.state('land'), 'pending')
        for _ in range(5):
            actions.receive('Re0201 ok')
        self.assertEqual(actions.state('land'), 'ok')
        self.assertIsNone(actions.receive('ok'))

    def test_next_flight_supported_and_no_unsolicited_packet_generation(self):
        actions = FlightActions(42)
        for name in ('takeoff','land','takeoff','stop','land'):
            packets = actions.request(name, 0)
            self.assertEqual(len(packets), 5)
            for _ in range(5):
                actions.receive('ok')
            self.assertEqual(actions.state(name), 'ok')
        with self.assertRaises(ValueError):
            actions.request('motoron', 0)

    def test_label_wrap_rejects_only_still_pending_targets_like_sdk(self):
        actions = FlightActions(0)
        for _ in range(100):
            actions.request('stop', 0)
        with self.assertRaises(RuntimeError):
            actions.request('stop', 0)
        actions = FlightActions(0)
        for _ in range(105):
            actions.request('stop', 0)
            for _ in range(5):
                actions.receive('ok')


class QuorumTests(unittest.TestCase):
    def test_three_distinct_successes_not_five_required(self):
        actions = QuorumFlightActions(34)
        self.assertEqual(actions.request('takeoff', 0), tuple(f'Re340{i} takeoff' for i in range(1,6)))
        for n, reply in enumerate(('Re0101 ok','Re0103 ok','Re0104 ok','Re0105 ok'), 1):
            actions.receive(reply, 5.9)
            self.assertEqual(actions.state('takeoff'), 'ok' if n >= 3 else 'pending')
        self.assertEqual(actions.snapshot()['takeoff']['success_count'], 4)

    def test_any_three_indices_and_order_can_confirm(self):
        from itertools import combinations, permutations
        for indices in combinations(range(1,6), 3):
            for order in permutations(indices):
                actions = QuorumFlightActions(82)
                actions.request('takeoff', 0)
                for i in order:
                    actions.receive(f'Re420{i} ok', 6)
                self.assertEqual(actions.state('takeoff'), 'ok', order)

    def test_duplicates_other_groups_bare_and_error_do_not_inflate_count(self):
        actions = QuorumFlightActions(82)
        actions.request('takeoff', 0)
        for reply in ('Re0101 ok','Re0101 ok','Re0101 ok','Re0202 ok',
                      'ok','error','Re0102 error','Re0102 ok','Re0106 ok',
                      'Re0103 okay','Re0103 ok trailing'):
            actions.receive(reply, 1)
        self.assertEqual(actions.snapshot()['takeoff']['success_count'], 1)
        self.assertEqual(actions.state('takeoff'), 'pending')

    def test_zero_one_two_replies_timeout_without_fabricated_success(self):
        for count in range(3):
            actions = QuorumFlightActions(82)
            actions.request('takeoff', 10)
            for i in range(1, count+1):
                actions.receive(f'Re010{i} ok', 16)
            actions.expire(21.999)
            self.assertEqual(actions.state('takeoff'), 'pending')
            actions.expire(22)
            self.assertEqual(actions.state('takeoff'), 'timeout')
            actions.receive('Re0105 ok', 22.001)
            self.assertEqual(actions.state('takeoff'), 'timeout')

    def test_third_reply_at_deadline_does_not_unlock(self):
        actions = QuorumFlightActions(82)
        actions.request('takeoff', 0)
        actions.receive('Re0101 ok', 11)
        actions.receive('Re0102 ok', 11)
        actions.receive('Re0103 ok', 12)
        self.assertEqual(actions.state('takeoff'), 'timeout')
        self.assertEqual(actions.snapshot()['takeoff']['success_count'], 2)

    def test_late_takeoff_packets_cannot_complete_landing(self):
        actions = QuorumFlightActions(82)
        actions.request('takeoff', 0)
        for i in (1,2):
            actions.receive(f'Re010{i} ok', 6)
        actions.expire(12)
        actions.request('land', 12)
        for i in (3,4,5):
            actions.receive(f'Re010{i} ok', 13)
        self.assertEqual(actions.snapshot()['land']['success_count'], 0)
        for i in (1,3,5):
            actions.receive(f'Re020{i} ok', 14)
        self.assertEqual(actions.state('takeoff'), 'timeout')
        self.assertEqual(actions.state('land'), 'ok')

    def test_no_reply_group_before_cancel_keeps_landing_association_unknown(self):
        actions = QuorumFlightActions(82)
        actions.request('takeoff', 0)
        actions.expire(12)
        actions.request('land', 12)
        for group in (1,2):
            for i in (1,2,3,4,5):
                actions.receive(f'Re{group:02d}0{i} ok', 13)
        self.assertEqual(actions.state('land'), 'unconfirmed')
        self.assertEqual(actions.snapshot()['land']['success_count'], 0)

    def test_bare_stop_reply_does_not_count_as_landing_success(self):
        actions = QuorumFlightActions(82)
        actions.request('takeoff', 0)
        for i in (1,2,3):
            actions.receive(f'Re010{i} ok', 6)
        actions.request('land', 8)
        for _ in range(5):
            actions.receive('ok', 9)
        self.assertEqual(actions.state('land'), 'pending')
        with self.assertRaises(ValueError):
            actions.request('stop', 10)

    def test_takeoff_quorum_is_sealed_and_next_flight_uses_new_group(self):
        actions = QuorumFlightActions(99)
        for n, name in enumerate(('takeoff','land','takeoff')):
            actions.request(name, n*10)
            for i in (1,3,5):
                actions.receive(f'Re{n+1:02d}0{i} ok', n*10+1)
            self.assertEqual(actions.state(name), 'ok')
        actions.expire(100)
        self.assertEqual(actions.state('takeoff'), 'ok')

    def test_h_u_cannot_bypass_missing_takeoff_quorum_or_deadline(self):
        controller = Controller()
        controller.mode, controller.possibly_airborne, controller.takeoff_at = 'TAKING_OFF', True, 0
        controller.tick(1, Pad(True), Keys(), Health(), focused=True)
        self.assertEqual(controller.tick(2, Pad(True), Keys(hover=True), Health(), focused=True), ['stop'])
        self.assertEqual(controller.mode, 'TAKING_OFF')
        self.assertEqual(controller.tick(3, Pad(True,rx=32767), Keys(enable=True), Health(), focused=True), [])
        self.assertEqual(controller.tick(12, Pad(True,rx=32767), Keys(), Health(), focused=True), ['land'])
        self.assertEqual(controller.tick(13, Pad(True,rx=32767), Keys(), Health(), focused=True,
                                         takeoff_status='ok'), [])
        self.assertEqual(controller.mode, 'LANDING')

    def test_h_during_takeoff_is_preserved_after_success(self):
        controller = Controller()
        controller.mode, controller.possibly_airborne, controller.takeoff_at = 'TAKING_OFF', True, 0
        controller.tick(1, Pad(True), Keys(), Health(), focused=True)
        controller.tick(2, Pad(True), Keys(hover=True), Health(), focused=True)
        self.assertEqual(controller.tick(3, Pad(True,rx=32767), Keys(), Health(), focused=True,
                                         takeoff_status='ok'), [ZERO])
        self.assertEqual(controller.mode, 'HOVER')


class CenterBrakeTests(unittest.TestCase):
    def setUp(self):
        # Preserve the former curve as a configurable regression, not new defaults.
        self.controller = Controller(limit=100, xy_expo=2)
        self.controller.mode, self.controller.possibly_airborne = 'FLYING', True
        self.now = 0

    def tick(self, pad, **kwargs):
        self.now += .05
        return self.controller.tick(self.now, pad, Keys(), Health(), focused=True, **kwargs)

    def hold_center_for_delay(self, pad=Pad(True)):
        self.now += self.controller.center_stop_delay
        return self.tick(pad)

    def test_center_sends_zero_immediately_then_delayed_stop_and_new_input_resumes_without_u(self):
        self.assertEqual(self.tick(Pad(True,rx=32767)), ['rc 100 0 0 0'])
        self.assertEqual(self.tick(Pad(True)), [ZERO])
        self.assertEqual(self.hold_center_for_delay(), [ZERO,'stop'])
        for _ in range(30):
            self.assertEqual(self.tick(Pad(True)), [ZERO])
        self.assertEqual(self.controller.mode, 'FLYING')
        self.assertEqual(self.tick(Pad(True,rx=-32768)), ['rc -100 0 0 0'])
        self.assertEqual(self.tick(Pad(True)), [ZERO])
        self.assertEqual(self.hold_center_for_delay(), [ZERO,'stop'])

    def test_first_zero_after_takeoff_does_not_trigger_stop(self):
        self.assertEqual(self.tick(Pad(True)), [ZERO])
        self.assertEqual(self.hold_center_for_delay(), [ZERO])

    def test_soft_curve_quantization_is_not_mistaken_for_physical_center(self):
        self.tick(Pad(True,rx=32767))
        self.assertEqual(self.tick(Pad(True,rx=6500)), [ZERO])
        self.assertFalse(Pad(True,rx=6500).centered)
        self.assertEqual(self.tick(Pad(True,rx=4900)), [ZERO])
        self.assertEqual(self.hold_center_for_delay(Pad(True,rx=4900)), [ZERO,'stop'])

    def test_center_does_not_interrupt_other_intentional_axes(self):
        self.tick(Pad(True,rx=32767))
        self.assertEqual(self.tick(Pad(True,ly=32767)), ['rc 0 0 100 0'])
        self.assertEqual(self.tick(Pad(True,lx=32767)), ['rc 0 0 0 100'])
        self.assertEqual(self.tick(Pad(True)), [ZERO])
        self.assertEqual(self.hold_center_for_delay(), [ZERO,'stop'])

    def test_disconnect_is_zero_and_stop_once_not_reverse_or_land(self):
        self.tick(Pad(True,rx=32767))
        self.assertEqual(self.tick(Pad(False)), [ZERO])
        self.assertEqual(self.hold_center_for_delay(Pad(False)), [ZERO,'stop'])
        self.assertEqual(self.tick(Pad(False)), [ZERO])

    def test_manual_land_has_priority_over_center_stop(self):
        self.tick(Pad(True,rx=32767))
        self.assertEqual(self.tick(Pad(True)), [ZERO])
        self.now += self.controller.center_stop_delay
        self.assertEqual(self.tick(Pad(True,buttons=LB|RB)), ['land'])
        self.assertIsNone(self.controller.centered_since)
        self.assertEqual(self.tick(Pad(True)), [])

    def test_xy_midrange_softened_but_vertical_yaw_unchanged(self):
        mapped = self.controller.mapped(Pad(True,16384,16384,16384,16384))
        self.assertEqual(mapped, (17,17,41,41))
        self.assertEqual(self.controller.mapped(Pad(True,32767,32767,32767,32767)), (100,100,100,100))
        values = [axis(raw, limit=100, expo=2) for raw in range(-32768,32768)]
        self.assertEqual((min(values),max(values)), (-100,100))
        self.assertTrue(all(a <= b for a,b in zip(values,values[1:])))

    def test_zero_has_no_time_smoothing_and_can_disable_auto_stop(self):
        self.controller = Controller(limit=100, center_brake=False, xy_expo=1)
        self.controller.mode = 'FLYING'
        self.assertEqual(self.tick(Pad(True,rx=32767)), ['rc 100 0 0 0'])
        self.assertEqual(self.tick(Pad(True)), [ZERO])
        self.assertEqual(self.hold_center_for_delay(), [ZERO])

    def test_boundary_timer_is_cancelled_by_new_input_and_fires_once(self):
        controller = Controller()
        controller.mode = 'FLYING'
        def tick(t, pad=Pad(True)):
            return controller.tick(t, pad, Keys(), Health(), focused=True)
        tick(0, Pad(True,rx=32767))
        self.assertEqual(tick(1), [ZERO])
        self.assertEqual(tick(2.999), [ZERO])
        self.assertEqual(tick(3, Pad(True,ry=32767)), ['rc 0 30 0 0'])  # Cancel at deadline.
        self.assertEqual(tick(10), [ZERO])
        self.assertEqual(tick(11.999), [ZERO])
        self.assertEqual(tick(12), [ZERO,'stop'])
        self.assertEqual(tick(20), [ZERO])
        self.assertEqual(tick(21, Pad(True,rx=-32768)), ['rc -30 0 0 0'])
        self.assertEqual(tick(22), [ZERO])
        self.assertEqual(tick(24), [ZERO,'stop'])

    def test_each_single_active_axis_prevents_global_stop(self):
        for field in ('lx','ly','rx','ry'):
            with self.subTest(field=field):
                controller = Controller()
                controller.mode = 'FLYING'
                for t in (0, 1, 3, 10):
                    out = controller.tick(t, replace(Pad(True), **{field: 32767}),
                                          Keys(), Health(), focused=True)
                    self.assertNotIn('stop', out)
                    self.assertIsNone(controller.centered_since)

    def test_rapid_short_center_gestures_never_send_stop(self):
        controller = Controller()
        controller.mode = 'FLYING'
        for t in range(20):
            for dt, pad in ((0, Pad(True,rx=32767)), (.1, Pad(True)), (.9, Pad(True))):
                out = controller.tick(t+dt, pad, Keys(), Health(), focused=True)
                self.assertNotIn('stop', out)

    def test_h_cancels_delayed_stop_and_remains_immediate(self):
        controller = Controller()
        controller.mode, controller.possibly_airborne = 'FLYING', True
        def tick(t, keys=Keys(), pad=Pad(True)):
            return controller.tick(t, pad, keys, Health(), focused=True)
        tick(0, pad=Pad(True,rx=32767))
        tick(1)
        self.assertEqual(tick(1.1, Keys(hover=True)), ['stop'])
        tick(2)
        self.assertEqual(tick(3, Keys(enable=True)), [ZERO])
        self.assertEqual(tick(6), [ZERO])
        self.assertIsNone(controller.centered_since)

    def test_custom_three_second_delay_and_invalid_delays(self):
        controller = Controller(center_stop_delay=3)
        controller.mode = 'FLYING'
        def tick(t, pad=Pad(True)):
            return controller.tick(t, pad, Keys(), Health(), focused=True)
        tick(0, Pad(True,rx=32767))
        tick(1)
        self.assertEqual(tick(3), [ZERO])
        self.assertEqual(tick(4), [ZERO,'stop'])
        for value in (0, 11, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Controller(center_stop_delay=value)


class LinearLowLimitTests(unittest.TestCase):
    def test_default_curve_has_small_input_response_and_lower_fullscale(self):
        controller = Controller()
        self.assertEqual((controller.limit, controller.xy_expo), (30, 1))
        for fraction, expected in ((.15, 0), (.20, 2), (.30, 5), (.50, 12), (1., 30)):
            for sign in (-1, 1):
                with self.subTest(fraction=fraction, sign=sign):
                    raw = round(fraction * (32768 if sign < 0 else 32767)) * sign
                    self.assertEqual(controller.mapped(Pad(True, rx=raw, ry=raw)),
                                     (sign * expected, sign * expected, 0, 0))
        self.assertLess(controller.mapped(Pad(True, rx=32767))[0],
                        Controller(limit=100, xy_expo=2).mapped(Pad(True, rx=32767))[0])
        self.assertGreater(controller.mapped(Pad(True, rx=6553))[0],
                           Controller(limit=100, xy_expo=2).mapped(Pad(True, rx=6553))[0])

    def test_new_default_center_zero_is_immediate_and_resume_is_not_locked(self):
        controller = Controller()
        controller.mode = 'FLYING'
        def tick(t, pad):
            return controller.tick(t, pad, Keys(), Health(), focused=True)
        self.assertEqual(tick(0, Pad(True, rx=6553)), ['rc 2 0 0 0'])
        self.assertEqual(tick(.05, Pad(True)), [ZERO])
        self.assertEqual(tick(.10, Pad(True)), [ZERO])
        self.assertEqual(tick(.15, Pad(True, rx=-6554)), ['rc -2 0 0 0'])
        self.assertEqual(controller.mode, 'FLYING')


class BoundaryTests(unittest.TestCase):
    def test_timestamp_snapshot_precedes_evaluation_clock(self):
        from tt_xbox_station import sample_health, health_from_meta
        clock, heartbeat = [100.], [100.]
        values = [0.] * 14
        def racing_reader(_):
            clock[0] += .0000645
            values[1] = values[10] = values[12] = values[13] = clock[0]
            values[11], values[5] = 70, 80
            heartbeat[0] = clock[0]
            return values.copy()
        with patch('tt_xbox_station.read_meta', racing_reader), \
             patch('tt_xbox_station.time.perf_counter', lambda: clock[0]):
            now, health, gui_age = sample_health(None, heartbeat)
        self.assertTrue(health.fresh)
        self.assertEqual(gui_age, 0)
        self.assertFalse(health_from_meta(values, now - 1).fresh)
        self.assertFalse(health_from_meta(values, now + 2).fresh)
        self.assertFalse(health_from_meta(None, now).fresh)

    def test_exact_command_formats_and_input_boundary(self):
        for value in ('land','stop', ZERO, 'setbitrate 0'):
            self.assertEqual(encode_command(value), value.encode())
        self.assertEqual(encode_command('Re4201 takeoff', takeoff_enabled=True), b'Re4201 takeoff')
        self.assertEqual(encode_command('rc -100 100 0 1', motion_enabled=True, rc_limit=100), b'rc -100 100 0 1')
        for value in ('takeoff','rc 1 0 0 0','emergency','motoron','flip l',
                      'Re4200 land','Re4206 land','Re4201 motoron',
                      'rc 101 0 0 0','rc 0 0 0 nan','land\ntakeoff','rc 0 0 0 0\n'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                encode_command(value)

    def test_video_only_whitelist_and_user_requested_four_mbps(self):
        from tt_video_viewer import encode_command as video_encode
        self.assertEqual(SETUP, ('command','setresolution high','setbitrate 4','setfps high','streamon'))
        for value in ('setresolution high',*(f'setbitrate {i}' for i in range(6)),'setfps high'):
            self.assertEqual(video_encode(value), encode_command(value))
        for value in ('takeoff','land','stop',ZERO,'motoron','Re4201 land'):
            with self.assertRaises(ValueError):
                video_encode(value)

    def test_telemetry_extension_remains_displayable(self):
        from tt_video_viewer import update_telemetry
        from tt_xbox_station import health_from_meta
        ctx = mp.get_context('spawn')
        for size in (11,14):
            meta = ctx.Array('d', size)
            update_telemetry(b'bat:80;h:70;templ:85;temph:88;', meta, 100)
            self.assertEqual(meta[5], 80)
            self.assertEqual(meta[10], 100)
        meta[1] = 100
        self.assertTrue(health_from_meta(list(meta), 100.1).fresh)
        update_telemetry(b'garbage;h:nan;bat:inf;', meta, 101)
        self.assertEqual(meta[11:14], [70,100,100])

    def _worker(self, scenario='renumbered', dry=False, limit=30, signs=(-1,1,1,1), rx=32767, record_y=False):
        from tt_xbox_station import control_worker
        from tt_record_button import Y_BUTTON
        ctx = mp.get_context('spawn')
        clock = [100.]
        meta = ctx.Array('d',14)
        heartbeat = ctx.RawArray('d',[100.])
        sent, event_log = [], ImmediateQueue(10000)
        record_requests = ImmediateQueue(32)

        class FakeSocket:
            def __init__(self):
                self.replies = []
                self.takeoff = self.land = None
                self.group = 0
            def connect(self, peer):
                pass
            def setblocking(self, value):
                pass
            def close(self):
                pass
            def send(self, data):
                value = data.decode()
                sent.append((clock[0],value))
                if value in SETUP:
                    self.replies.append((clock[0], b'ok'))
                if not value.startswith('Re'):
                    return
                prefix, name = value.split(' ',1)
                if prefix[-2:] != '05':
                    return
                self.group += 1
                if name == 'takeoff':
                    self.takeoff = clock[0]
                if name == 'land':
                    self.land = clock[0]
                if scenario == 'lost' and name == 'takeoff':
                    return
                delay = 8.9 if name == 'takeoff' else 4.4 if name == 'land' else .05
                indices = (1,3,4,5) if scenario == 'four' and name == 'takeoff' else range(1,6)
                if scenario == 'two' and name == 'takeoff':
                    indices = (1,5)
                for i in indices:
                    reply = ('ok' if scenario == 'bare' else
                             f'Re{self.group:02d}{i:02d} ok')
                    self.replies.append((clock[0] + delay, reply.encode()))
                self.replies.sort()
            def recv(self, _size):
                if self.replies and self.replies[0][0] <= clock[0]:
                    return self.replies.pop(0)[1]
                raise BlockingIOError()
        sock = FakeSocket()

        class MockInput:
            def __init__(self, *_args):
                pass
            def read(self):
                t = clock[0]-100
                heartbeat[0] = clock[0]
                with meta.get_lock():
                    meta[1] = meta[10] = meta[12] = meta[13] = clock[0]
                    meta[11], meta[5] = (90 if sock.takeoff is not None else 0), 77
                # Background Xbox and stale video do not trigger app auto-land.
                pad = Pad(True, rx=rx if t >= 10.5 and not (
                    scenario == 'center' and 11.5 <= t < 12.5 or
                    scenario == 'center_long' and 11.5 <= t < 13.8) else 0,
                          lt=255 if .5 <= t < 2 else 0, rt=255 if .5 <= t < 2 else 0,
                          buttons=(LB|RB if scenario not in ('two','lost','bare') and 14 <= t < 14.2 else 0)
                                  | (Y_BUTTON if record_y and (3 <= t < 3.5 or 4 <= t < 4.5) else 0))
                keys = Keys(hover=scenario == 'hover' and 11.5 <= t < 11.7,
                            enable=scenario == 'hover' and 12.5 <= t < 12.7)
                return pad, keys, scenario == 'hover'
        def sleep(seconds):
            clock[0] += max(.001,seconds)
        args = SimpleNamespace(live=not dry, local_ip='mock',drone_ip='mock',interface=1,
                               rc_limit=limit,signs=signs,controller_index=0,
                               seconds=20,headless=dry, takeoff_timeout=12,
                               xy_expo=DEFAULT_XY_EXPO, no_center_brake=False)
        with tempfile.TemporaryDirectory() as directory:
            args.output = directory
            with patch('tt_xbox_station.WindowsInput', MockInput), \
                 patch('tt_xbox_station.signal.signal'), \
                 patch('tt_xbox_station.time.perf_counter', lambda: clock[0]), \
                 patch('tt_xbox_station.time.sleep', sleep), \
                 patch('tt_xbox_station.QuorumFlightActions', lambda **kw: QuorumFlightActions(82, **kw)), \
                 patch('tt_xbox_station.verify_peer', side_effect=AssertionError('ARP FORBIDDEN')), \
                 patch('tt_xbox_station.bind_udp',
                       side_effect=AssertionError('NETWORK FORBIDDEN') if dry else None,
                       return_value=sock):
                control_worker(args,1,meta,heartbeat,ctx.Event(),ctx.Event(),
                               ImmediateQueue(2),event_log,record_requests)
            result = json.loads((Path(directory)/'controller_exit.json').read_text())
        events = []
        while not event_log.empty():
            events.append(event_log.get_nowait())
        result['test_record_requests'] = []
        while not record_requests.empty():
            result['test_record_requests'].append(record_requests.get_nowait())
        return sent,result,events

    def test_y_records_in_background_without_changing_aircraft_commands(self):
        baseline,_,_ = self._worker()
        sent,result,events = self._worker(record_y=True)
        self.assertEqual(sent,baseline)
        self.assertEqual(result['test_record_requests'],['toggle','toggle'])
        self.assertEqual(sum(row['kind']=='record_button' for row in events),2)

    def test_fake_udp_recorded_id_mismatch_now_allows_actual_rc(self):
        sent,result,events = self._worker()
        commands = [v for _,v in sent]
        self.assertEqual(commands[:5], list(SETUP))
        self.assertEqual(commands.count('command'), 1)  # No GroundLink.
        self.assertEqual(len([v for v in commands if v.endswith(' takeoff')]), 5)
        self.assertIn('rc -30 0 0 0', commands)
        land = [(t,v) for t,v in sent if v.endswith(' land')]
        self.assertEqual(len(land), 5)
        self.assertTrue(all(114 <= t < 114.2 for t,_ in land))  # Only operator request.
        self.assertFalse(any(v.endswith(' stop') for v in commands))
        self.assertEqual(result['actions']['takeoff']['status'], 'ok')
        self.assertEqual(result['actions']['land']['status'], 'ok')
        self.assertFalse(result['possibly_airborne'])
        self.assertNotIn('error',result)
        self.assertEqual(commands[-1], 'streamoff')
        self.assertIn('FLYING', [e.get('mode') for e in events])

    def test_fake_udp_unidentified_bare_ok_cannot_satisfy_numbered_quorum(self):
        sent,result,_ = self._worker('bare')
        self.assertFalse(any(v.startswith('rc ') for _,v in sent))
        self.assertEqual(result['actions']['takeoff']['status'], 'timeout')
        self.assertEqual(result['actions']['land']['status'], 'unconfirmed')

    def test_fake_udp_default_capped_roll_in_both_directions(self):
        for raw, expected in ((-32768, 'rc -30 0 0 0'), (32767, 'rc 30 0 0 0')):
            with self.subTest(raw=raw):
                sent, result, _ = self._worker(limit=DEFAULT_RC_LIMIT, signs=DEFAULT_SIGNS, rx=raw)
                commands = [value for _, value in sent]
                self.assertIn(expected, commands)
                self.assertEqual(result['actions']['land']['status'], 'ok')
                self.assertEqual(len([v for v in commands if v.endswith(' takeoff')]), 5)
                self.assertEqual(len([v for v in commands if v.endswith(' land')]), 5)

    def test_zero_replies_generates_one_timeout_land_but_not_false_completion(self):
        sent,result,_ = self._worker('lost')
        land_times = [t for t,v in sent if v.endswith(' land')]
        self.assertTrue(land_times)
        takeoff_time = next(t for t,v in sent if v.endswith(' takeoff'))
        self.assertTrue(all(12 <= t-takeoff_time < 12.1 for t in land_times))
        self.assertEqual(len(land_times),5)
        self.assertFalse(any(v.startswith('rc ') for _,v in sent))
        self.assertEqual(result['actions']['land']['status'], 'unconfirmed')
        self.assertIn('without SDK land completion', result['error'])

    def test_recorded_four_replies_unlock_worker_and_do_not_timeout_land(self):
        sent, result, events = self._worker('four')
        self.assertIn('rc -30 0 0 0', [v for _,v in sent])
        self.assertEqual(result['actions']['takeoff']['success_count'], 4)
        self.assertEqual(result['actions']['takeoff']['status'], 'ok')
        self.assertTrue(all(114 <= t < 114.2 for t,v in sent if v.endswith(' land')))
        self.assertIn('FLYING', [e.get('mode') for e in events])

    def test_two_replies_timeout_land_is_sent_and_can_be_confirmed(self):
        sent, result, _ = self._worker('two')
        takeoff_time = next(t for t,v in sent if v.endswith(' takeoff'))
        land = [t for t,v in sent if v.endswith(' land')]
        self.assertEqual(len(land), 5)
        self.assertTrue(all(12 <= t-takeoff_time < 12.1 for t in land))
        self.assertFalse(any(v.startswith('rc ') for _,v in sent))
        self.assertEqual(result['actions']['takeoff']['status'], 'timeout')
        self.assertEqual(result['actions']['land']['status'], 'ok')
        self.assertFalse(result['possibly_airborne'])

    def test_worker_center_stop_is_one_delayed_plain_packet_without_ack(self):
        sent, result, _ = self._worker('center_long')
        stops = [(t,v) for t,v in sent if v == 'stop']
        self.assertEqual(len(stops), 1)
        self.assertTrue(113.5 <= stops[0][0] < 113.6)
        first = next(i for i, (_, value) in enumerate(sent) if value == 'stop')
        self.assertEqual([value for _, value in sent[first-1:first+1]], [ZERO, 'stop'])
        self.assertTrue(all(value == ZERO for t,value in sent if 111.5 <= t < 113.5))
        self.assertFalse(any(v.endswith(' stop') for _,v in sent))
        self.assertTrue(any(t > stops[0][0] and v == 'rc -30 0 0 0' for t,v in sent))
        self.assertEqual(result['actions']['land']['status'], 'ok')

    def test_worker_short_center_pause_does_not_send_stop(self):
        sent, result, _ = self._worker('center')
        self.assertFalse(any(value == 'stop' for _,value in sent))
        self.assertTrue(any(t >= 112.5 and value == 'rc -30 0 0 0' for t,value in sent))
        self.assertEqual(result['actions']['land']['status'], 'ok')

    def test_worker_h_single_stop_without_replies_does_not_block_u_resume(self):
        sent, result, _ = self._worker('hover')
        stops = [(t, value) for t, value in sent if value == 'stop']
        self.assertEqual(len(stops), 1)
        self.assertNotIn('stop', result['actions'])
        self.assertTrue(any(t > stops[-1][0] and value == 'rc -30 0 0 0' for t, value in sent))
        self.assertEqual(result['actions']['land']['status'], 'ok')

    def test_headless_dry_worker_has_no_network_or_flight_actions(self):
        sent,result,events = self._worker(dry=True)
        self.assertEqual(sent,[])
        self.assertFalse(result['real_network'])
        self.assertFalse(result['takeoff_used'])
        self.assertEqual(result['actions'],{})
        self.assertFalse(any(e.get('kind') == 'simulated_command' for e in events))


if __name__ == '__main__':
    unittest.main(verbosity=2)
