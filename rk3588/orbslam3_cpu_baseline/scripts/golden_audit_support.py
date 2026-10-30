"""PS-side protocol/supervision checks; no changes to G1 or SLAM algorithms."""
import csv
import json
import math
import pathlib
import re
import struct


def canonical_timestamps(path):
    values = [int(value) for value in pathlib.Path(path).read_text(encoding='utf-8-sig').split()]
    if not values or any(not 0 < value < 2**64 for value in values) or any(a >= b for a,b in zip(values,values[1:])):
        raise ValueError('Timestamp sequence must be strictly increasing integer nanoseconds')
    return values, ''.join(str(value)+'\n' for value in values).encode('ascii')


def write_timestamps(source, target):
    """Canonical working copy only; never modify source nanosecond values."""
    values,data=canonical_timestamps(source)
    target=pathlib.Path(target)
    with target.open('xb') as stream:stream.write(data)
    return values


def atomic_json(path, value):
    path = pathlib.Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temp.replace(path)


def packet(data, ns, role, width, height, levels, budget):
    """Mirror every FeatureIO::LoadPacket invariant, with expected image/settings."""
    if len(data) < 64 or len(data) > 64 + 64 * 100000 or data[:8] != b'ORBFEAT\0':
        raise ValueError('B1 magic/length')
    if struct.unpack_from('<HHHBB', data, 8) != (1, 64, 64, role, 0):
        raise ValueError('B1 layout/role')
    if struct.unpack_from('<QII', data, 16) != (ns, width, height):
        raise ValueError('B1 timestamp/image')
    count = struct.unpack_from('<I', data, 32)[0]
    if struct.unpack_from('<I', data, 36)[0] != levels or data[40:44] != struct.pack('<f', 1.2):
        raise ValueError('B1 scales')
    if struct.unpack_from('<III', data, 44) != (budget, 32, 0) or data[60:64] != b'\0' * 4:
        raise ValueError('B1 budget/format/reserved')
    mono = struct.unpack_from('<i', data, 56)[0]
    if len(data) != 64 + 64 * count or not 0 <= mono <= count:
        raise ValueError('B1 count/monoLeft')
    for offset in range(64, len(data), 64):
        x, y, octave, angle, size, response, _, reserved = struct.unpack_from('<ffifffiI', data, offset)
        if not all(math.isfinite(v) for v in (x, y, angle, size, response)):
            raise ValueError('B1 nonfinite keypoint')
        if not (0 <= x < width and 0 <= y < height and 0 <= octave < levels and 0 <= angle < 360 and size > 0 and reserved == 0):
            raise ValueError('B1 invalid keypoint')
    return count


def read_rows(path):
    with pathlib.Path(path).open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def binding(run, timestamps, corpus, levels, width, height):
    features = read_rows(run / 'FeatureTimeStats.csv')
    states = read_rows(run / 'TrackingStates.csv')
    maps = read_rows(run / 'MapStateStats.csv')
    if not (len(features) == len(states) == len(maps) <= len(timestamps)):
        raise ValueError('Diagnostic row alignment')
    for index, (row, state, m) in enumerate(zip(features, states, maps)):
        role = int(row['role'])
        if int(row['frame_index']) != index or int(state['frame_index']) != index or int(m['frame_index']) != index:
            raise ValueError('Diagnostic frame order')
        if int(row['timestamp_ns']) != timestamps[index] or role not in (0, 1) or int(row['extractor_calls']) != 0:
            raise ValueError('Injection timestamp/role/calls')
        if float(timestamps[index]) * 1e-9 != float(state['timestamp_s']):
            raise ValueError('Tracking timestamp association')
        path = corpus / ('initialization' if role else 'normal') / (str(timestamps[index]) + '.orb')
        count = packet(path.read_bytes(), timestamps[index], role, width, height, levels, 5000 if role else 1000)
        if int(row['count']) != count:
            raise ValueError('Injected point count')
    return len(states)


def classify(metadata, run):
    """Candidate hang is retained only with an intact, pre-signal backend snapshot."""
    if metadata['status'] == 'FINISHED':
        return 'COMPLETED'
    reason = metadata.get('failure_reason', '')
    if ('NO_FRAME_PROGRESS_120S' in reason or 'TOTAL_DURATION_CAP' in reason):
        stack = run / 'hang_snapshot/threads.gdb.txt'
        if not metadata.get('stack_capture_ok') or not metadata.get('snapshot_saved_before_signal_utc'):
            raise ValueError('Hang capture is incomplete')
        text = stack.read_text(errors='replace')
        if metadata.get('completed_frames', 0) <= 0 or not re.search(r'ORB_SLAM3::(?:Tracking|LocalMapping|LoopClosing|System)::', text):
            raise ValueError('Hang not attributable to running SLAM backend')
        if 'FeatureIO:' in (run / 'run.log').read_text(errors='replace'):
            raise ValueError('Feature protocol failure is blocking')
        return 'CANDIDATE_HANG_RETAINED'
    log=run/'run.log'
    if metadata.get('completed_frames')==0 and log.exists() and 'Failed to load image at:' in log.read_text(errors='replace'):
        raise ValueError('INPUT_IMAGE_LOAD_FAILED before first completed frame; inspect timestamps and exact filename')
    raise ValueError('Unclassified runtime failure: ' + (reason or 'exit=%s frames=%s'%(metadata.get('exit_code'),metadata.get('completed_frames'))))


class CompletedProgress:
    def __init__(self, now):
        self.frames, self.updated = -1, now

    def observe(self, log_tail, now):
        values = re.findall(r'GOLDEN_SEQUENCE_PROGRESS frames=(\d+)', log_tail)
        if values and int(values[-1]) > self.frames:
            self.frames, self.updated = int(values[-1]), now
        return now - self.updated >= 120
