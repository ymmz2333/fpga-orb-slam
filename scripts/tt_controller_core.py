"""Computer/PS Xbox input adapter for the official TT text action lifecycle.

Aircraft stabilization and battery/link failsafes belong to TT firmware.
Video, height, battery, window focus and GUI timing are display information,
not flight permission gates. Takeoff below 3/5 at the user-requested deadline
requests landing. Sustained centered sticks request one delayed stop, not reverse RC.
"""
from dataclasses import dataclass
import math
import re
from tt_quorum_actions import DEFAULT_TAKEOFF_TIMEOUT
from tt_video_config import video_settings

LB, RB = 0x0100, 0x0200
DEFAULT_RC_LIMIT = 30  # Operator cap; the TT protocol still allows +/-100 (not cm/s).
DEFAULT_SIGNS = (1, 1, 1, 1)  # RX, RY, LY, LX; roll corrected from user flight observation.
DEFAULT_XY_EXPO = 1.0
DEFAULT_CENTER_STOP_DELAY = 2.0
ZERO = 'rc 0 0 0 0'
SETUP = ('command', *video_settings(), 'streamon')
SAFE = frozenset((*SETUP, *(f'setbitrate {i}' for i in range(6)), 'streamoff', 'battery?', 'stop', 'land'))


def encode_command(value, *, takeoff_enabled=False, motion_enabled=False, rc_limit=DEFAULT_RC_LIMIT):
    """Exact transport formats; input UI permission is not an aircraft policy."""
    numbered = re.fullmatch(r'Re[0-9]{2}0[1-5] (takeoff|land|stop)', value)
    if numbered:
        encode_command(numbered[1], takeoff_enabled=takeoff_enabled,
                       motion_enabled=motion_enabled, rc_limit=rc_limit)
        return value.encode('ascii')
    if value in SAFE or (value == 'takeoff' and takeoff_enabled):
        return value.encode('ascii')
    if re.fullmatch(r'rc -?\d{1,3} -?\d{1,3} -?\d{1,3} -?\d{1,3}', value):
        channels = tuple(int(v) for v in value.split()[1:])
        if (all(abs(v) <= rc_limit <= 100 for v in channels)
                and (motion_enabled or not any(channels))):
            return value.encode('ascii')
    raise ValueError('Invalid or unrequested flight-station command: ' + repr(value))


@dataclass(frozen=True)
class Pad:
    connected: bool = False
    lx: int = 0
    ly: int = 0
    rx: int = 0
    ry: int = 0
    lt: int = 0
    rt: int = 0
    buttons: int = 0

    @property
    def landing(self):
        return self.buttons & (LB | RB) == LB | RB

    @property
    def released(self):
        return self.lt < 30 and self.rt < 30

    @property
    def centered(self):
        return (not self.connected or all(abs(v) <= .15 * (32768 if v < 0 else 32767)
                                          for v in (self.lx, self.ly, self.rx, self.ry)))


@dataclass(frozen=True)
class Health:
    video_age: float = math.inf
    state_age: float = math.inf
    height_age: float = math.inf
    battery_age: float = math.inf
    height: float = math.nan
    battery: float = math.nan

    @property
    def fresh(self):
        """Display/diagnostics only; never used to gate flight."""
        return (all(0 <= v <= 1.5 for v in
                    (self.video_age, self.state_age, self.height_age, self.battery_age))
                and math.isfinite(self.height) and -20 <= self.height <= 3000
                and math.isfinite(self.battery) and 0 <= self.battery <= 100)


@dataclass(frozen=True)
class Keys:
    enable: bool = False  # U resumes the operator-requested H hover.
    hover: bool = False
    land: bool = False


def axis(value, limit=DEFAULT_RC_LIMIT, deadzone=.15, expo=1.):
    normalized = max(-1., min(1., value / (32768. if value < 0 else 32767.)))
    if abs(normalized) <= deadzone:
        return 0
    magnitude = ((abs(normalized) - deadzone) / (1 - deadzone)) ** expo
    return round(math.copysign(magnitude, normalized) * limit)


class Controller:
    """READY -> TAKING_OFF -> FLYING -> LANDING -> READY.

    TT action completion is SDK text-response completion, NOT independently
    verified physical state. H/U and the button hold are explicit UI behavior.
    """
    def __init__(self, limit=DEFAULT_RC_LIMIT, signs=DEFAULT_SIGNS, *,
                 takeoff_timeout=DEFAULT_TAKEOFF_TIMEOUT, xy_expo=DEFAULT_XY_EXPO,
                 center_brake=True, center_stop_delay=DEFAULT_CENTER_STOP_DELAY):
        if not 1 <= limit <= 100 or len(signs) != 4 or any(x not in (-1, 1) for x in signs):
            raise ValueError('RC limit must be 1..100 and four signs must be +/-1')
        self.limit, self.signs = limit, signs
        if not 1 <= takeoff_timeout <= 14 or not 1 <= xy_expo <= 3:
            raise ValueError('Takeoff timeout must be 1..14 seconds; XY exponent 1..3')
        self.takeoff_timeout, self.xy_expo = takeoff_timeout, xy_expo
        if not math.isfinite(center_stop_delay) or not 1 <= center_stop_delay <= 10:
            raise ValueError('Center stop delay must be finite and 1..10 seconds')
        self.center_stop_delay = center_stop_delay
        self.center_brake = center_brake
        self.clear_center_stop()
        self.takeoff_hover_requested = False
        self.mode = 'READY'
        self.reason = 'LT+RT for 1s: takeoff; LB+RB / L: land'
        self.possibly_airborne = False
        self.takeoff_used = self.landing_used = False  # Diagnostics only.
        self.takeoff_at = None
        self.hold_since = None
        self.trigger_ready = False
        self.previous_keys = Keys()
        self.previous_focus = False
        self.previous_land = False
        self.close_requested = False
        self.rc = (0, 0, 0, 0)

    def mapped(self, pad):
        if not pad.connected:
            return (0, 0, 0, 0)  # There is no current stick input.
        return tuple(axis(v, self.limit, expo=self.xy_expo if i < 2 else 1.) * s
                     for i, (v, s) in enumerate(zip((pad.rx, pad.ry, pad.ly, pad.lx), self.signs)))

    def clear_center_stop(self):
        self.stick_was_active = False
        self.centered_since = None
        self.center_stop_sent = False

    def begin_land(self, reason):
        self.mode, self.reason = 'LANDING', reason
        self.landing_used = True
        self.possibly_airborne = True
        self.hold_since = None
        self.trigger_ready = False
        self.clear_center_stop()
        return ['land']

    def tick(self, now, pad, keys, health, *, focused, gui_age=0., close=False,
             takeoff_status='not_sent', land_status='not_sent'):
        self.rc = (0, 0, 0, 0)
        # Letters are UI shortcuts in this window. Xbox continues in background.
        enable_edge = (focused and self.previous_focus and keys.enable
                       and not self.previous_keys.enable)
        hover_edge = (focused and self.previous_focus and keys.hover
                      and not self.previous_keys.hover)
        keyboard_land_edge = (focused and self.previous_focus and keys.land
                              and not self.previous_keys.land)
        pad_land = pad.connected and pad.landing
        land_edge = keyboard_land_edge or (pad_land and not self.previous_land)
        self.previous_keys, self.previous_focus = keys, focused
        self.previous_land = pad_land

        if self.mode == 'TAKING_OFF':
            if takeoff_status == 'ok':
                self.mode = 'HOVER' if self.takeoff_hover_requested else 'FLYING'
                self.reason = ('Takeoff 3/5 OK; H hover active, U resumes' if self.takeoff_hover_requested
                               else 'Takeoff 3/5 OK; sticks active')
        elif self.mode == 'LANDING':
            if land_status == 'ok':
                self.mode, self.reason = 'READY', 'TT land completed; visually verify ground/motors'
                self.possibly_airborne = False
                self.trigger_ready = False  # A held combo is not a new takeoff gesture.
            elif land_status == 'error':
                self.mode, self.reason = 'ACTION_ERROR', 'TT reported land error; operator action required'

        if close and not self.close_requested:
            self.close_requested = True
            if self.possibly_airborne and self.mode != 'LANDING':
                return self.begin_land('Window close: operator-requested land')
        if close:
            return []
        if land_edge:
            return self.begin_land('LB+RB / L: operator-requested land')

        if self.mode == 'TAKING_OFF' and (takeoff_status in ('timeout', 'error') or
                (self.takeoff_at is not None and now - self.takeoff_at >= self.takeoff_timeout)):
            return self.begin_land(f'Takeoff below 3/5 at {self.takeoff_timeout:g}s: landing requested')

        # H is an explicit hover request; U explicitly resumes RC, without new gates.
        if hover_edge and self.mode != 'LANDING':
            self.clear_center_stop()
            if self.mode == 'TAKING_OFF':
                self.takeoff_hover_requested = True
                self.reason = 'H: stop requested; still waiting for takeoff 3/5'
            else:
                self.mode = 'HOVER' if self.possibly_airborne else 'READY'
                self.reason = 'H: hover requested; U resumes sticks'
            return ['stop']
        if enable_edge and self.mode == 'HOVER':
            self.mode, self.reason = 'FLYING', 'U: sticks resumed'

        if pad.connected and pad.released:
            self.trigger_ready = True
        combo = pad.connected and pad.lt >= 217 and pad.rt >= 217
        if not combo:
            self.hold_since = None
        if self.mode == 'READY' and self.trigger_ready and combo:
            if self.hold_since is None:
                self.hold_since = now
            if now - self.hold_since >= 1:
                self.mode = 'TAKING_OFF'
                self.reason = f'Waiting for takeoff 3/5 OK; below 3 => land at {self.takeoff_timeout:g}s'
                self.possibly_airborne = self.takeoff_used = True
                self.takeoff_at = now
                self.takeoff_hover_requested = False
                self.clear_center_stop()
                self.trigger_ready = False
                self.hold_since = None
                return ['takeoff']
        if self.mode == 'FLYING':
            self.rc = self.mapped(pad)
            # Zero RC immediately, then one stop only after ALL four raw axes stay
            # centered for the delay. New input cancels the timer immediately.
            # Quantized zero outside the raw deadzone is still intentional input.
            active = not pad.centered
            if active:
                self.centered_since = None
                self.center_stop_sent = False
            elif self.stick_was_active:
                self.centered_since = now
                self.center_stop_sent = False
            self.stick_was_active = active
            brake = (self.center_brake and self.centered_since is not None
                     and not self.center_stop_sent
                     and now - self.centered_since >= self.center_stop_delay)
            if brake:
                self.center_stop_sent = True
                self.reason = f'Sticks centered for {self.center_stop_delay:g}s: one stop; new input resumes'
                return [ZERO, 'stop']
            self.reason = 'Takeoff 3/5 OK; sticks active'
            return ['rc ' + ' '.join(str(v) for v in self.rc)]
        if self.mode == 'HOVER':
            return [ZERO]
        return []

    def snapshot(self):
        return dict(mode=self.mode, reason=self.reason, rc=list(self.rc),
                    motion_enabled=self.mode == 'FLYING',
                    possibly_airborne=self.possibly_airborne,
                    landing_used=self.landing_used, takeoff_used=self.takeoff_used,
                    takeoff_timeout=self.takeoff_timeout, xy_expo=self.xy_expo,
                    center_brake=self.center_brake,
                    center_stop_delay=self.center_stop_delay,
                    center_stop_pending=self.center_brake and self.centered_since is not None
                                        and not self.center_stop_sent,
                    rc_limit=self.limit, signs=list(self.signs))
