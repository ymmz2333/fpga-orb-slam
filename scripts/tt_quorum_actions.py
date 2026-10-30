"""User-requested TT 3-of-5 action acknowledgement policy (not SDK FIFO).

Numbered takeoff/land packets retain the official format. Replies are counted
by distinct copy ID within one observed response group, even when TT rewrites
the outgoing group. Bare stop acknowledgements never count toward takeoff.
No networking, automatic retries, or physical-flight assertions live here.
"""
from dataclasses import dataclass, field
import random
import re
import time

ACK_QUORUM = 3
DEFAULT_TAKEOFF_TIMEOUT = 12.0


@dataclass
class QuorumAction:
    name: str
    label: int
    started: float
    sequence: int
    response_group: int | None = None
    copies: list = field(default_factory=lambda: ['pending'] * 5)
    replies: list = field(default_factory=list)
    retired: bool = False
    timed_out: bool = False
    association_uncertain: bool = False

    @property
    def packets(self):
        return tuple(f'Re{self.label:02d}0{i} {self.name}' for i in range(1, 6))

    @property
    def success_count(self):
        return self.copies.count('ok')

    @property
    def status(self):
        if self.timed_out:
            return 'timeout'
        if self.association_uncertain:
            return 'unconfirmed'
        if self.success_count >= ACK_QUORUM:
            return 'ok'
        return 'superseded' if self.retired else 'pending'


class QuorumFlightActions:
    def __init__(self, first_label=None, takeoff_timeout=DEFAULT_TAKEOFF_TIMEOUT):
        self.first_label = random.randrange(100) if first_label is None else first_label
        self.takeoff_timeout = takeoff_timeout
        self.history, self.latest, self.owners = [], {}, {}
        self.active = None

    def request(self, name, now):
        if name not in ('takeoff', 'land'):
            raise ValueError('Quorum tracking is only for takeoff/land; stop is unnumbered')
        uncertain = False
        if self.active is not None:
            previous = self.active
            # If a cancelled action never identified its reply group, a later
            # unknown group cannot safely be labelled as the new land action.
            uncertain = (previous.association_uncertain or
                         (previous.response_group is None and previous.status != 'ok'))
            previous.retired = True
        action = QuorumAction(name, (self.first_label + len(self.history)) % 100,
                              now, len(self.history), association_uncertain=uncertain)
        self.history.append(action)
        self.latest[name] = self.active = action
        return action.packets

    def expire(self, now):
        action = self.active
        if (action is not None and action.name == 'takeoff' and action.status != 'ok'
                and now >= action.started + self.takeoff_timeout):
            action.timed_out = True

    def receive(self, reply, now=None):
        now = time.perf_counter() if now is None else now
        self.expire(now)
        match = re.fullmatch(r'Re([0-9]{2})0([1-5]) (ok|error)', reply)
        if match is None:
            return None  # Bare ok/error (e.g. stop) has no unique copy identity.
        group, copy_id, outcome = int(match[1]), int(match[2]), match[3]
        owner = self.owners.get(group)
        action = owner or self.active
        if action is None:
            return None
        decision = 'accepted'
        if action is not self.active or action.retired or action.timed_out:
            decision = 'late_retired'
        elif action.association_uncertain:
            decision = 'ambiguous_previous_action'
        elif action.response_group is not None and group != action.response_group:
            decision = 'different_group'
        else:
            action.response_group = group
            self.owners[group] = action
            if action.copies[copy_id - 1] != 'pending':
                decision = 'duplicate_or_conflicting_copy'
            else:
                action.copies[copy_id - 1] = outcome
        if len(action.replies) < 32:
            action.replies.append(reply)
        return dict(action=action.name, label=action.label, sequence=action.sequence,
                    copy=copy_id, response_group=group, reply=reply, decision=decision,
                    status=action.status, success_count=action.success_count,
                    required=ACK_QUORUM, copies=list(action.copies))

    def state(self, name):
        action = self.latest.get(name)
        return action.status if action else 'not_sent'

    def snapshot(self):
        return {name: dict(label=a.label, sequence=a.sequence, status=a.status,
                           response_group=a.response_group, copies=list(a.copies),
                           success_count=a.success_count, required=ACK_QUORUM,
                           replies=list(a.replies), association_uncertain=a.association_uncertain)
                for name, a in self.latest.items()}
