"""Offline SDK reference ONLY. Live control uses tt_quorum_actions.py.

TT (not EP) text-action adapter, following DJI RoboMaster-SDK.

Reference: ff6646e115ab125af3207a4ed3df42cc76c795b2, flight.py / action.py.
The SDK sends five ReXX01..05 copies and dispatches recognized text responses
to pending copies in insertion order. It does NOT require an echoed XX label.
The final copy is the action returned by Flight.takeoff/land/stop.

No sockets here. No automatic action timeout, retries after the initial group,
hard-coded aircraft response labels, or application heartbeat.
This preserves the SDK's weak response correlation, not a delivery guarantee.
"""
from dataclasses import dataclass, field
import random
import re


def recognized_reply(reply):
    """Equivalent to DJI TextAction.found_action for the TT text protocol."""
    return (reply in ('ok', 'error', 'out of range', 'error No valid marker')
            or re.match(r'Re\d{4} ok', reply) is not None)


def reply_state(reply):
    """Equivalent state transitions to TextAction._update_action_state."""
    if reply == 'ok' or re.match(r'Re\d{4} ok', reply):
        return 'ok'
    if reply == 'error':
        return 'error'
    return 'pending'  # The official implementation logs other responses.


@dataclass
class Action:
    name: str
    label: int
    started: float
    sequence: int
    copies: list = field(default_factory=lambda: ['pending'] * 5)
    replies: list = field(default_factory=list)

    @property
    def packets(self):
        return tuple(f'Re{self.label:02d}{i:02d} {self.name}' for i in range(1, 6))

    @property
    def status(self):
        # Flight.takeoff(...).wait_for_completed() waits for the returned LAST copy.
        return self.copies[-1]


class FlightActions:
    """Small equivalent of the TT Flight/TextAction dispatch path.

    No interpretation of Re0101 as a fixed takeoff ID. Late/duplicate UDP
    responses remain ambiguous, just as in the SDK; logs retain actual replies.
    """
    def __init__(self, first_label=None):
        self.first_label = random.randrange(100) if first_label is None else first_label
        self.history = []
        self.latest = {}

    def request(self, name, now):
        if name not in ('takeoff', 'land', 'stop'):
            raise ValueError('Not a TT flight action used by this controller')
        label = (self.first_label + len(self.history)) % 100
        if any(a.label == label and 'pending' in a.copies for a in self.history):
            raise RuntimeError('TT SDK action target is still pending')
        action = Action(name, label, now, len(self.history))
        self.history.append(action)
        self.latest[name] = action
        return action.packets

    def state(self, name):
        action = self.latest.get(name)
        return action.status if action else 'not_sent'

    def receive(self, reply):
        if not recognized_reply(reply):
            return None
        # ActionDispatcher visits _in_progress in insertion order and consumes
        # one matching TextAction per datagram, regardless of the received ID.
        for action in self.history:
            for index, state in enumerate(action.copies):
                if state != 'pending':
                    continue
                action.copies[index] = reply_state(reply)
                action.replies.append(reply)
                return dict(action=action.name, label=action.label,
                            sequence=action.sequence, copy=index + 1, reply=reply,
                            status=action.status, copies=list(action.copies))
        return None

    def snapshot(self):
        return {name: dict(label=a.label, sequence=a.sequence, status=a.status,
                           copies=list(a.copies), replies=list(a.replies))
                for name, a in self.latest.items()}
