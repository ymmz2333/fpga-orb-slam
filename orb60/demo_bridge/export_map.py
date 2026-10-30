"""Create a deterministic localization view of an immutable SLAM export.

SLAM can associate the same landmark to several pyramid-level features in a
keyframe. The fixed-map locator requires one observation per (keyframe, point).
Keep the smallest reprojection error, then feature index, then source row.
Coordinates, poses and the retained FPGA descriptor bytes are never altered.
"""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil

from .map_bundle import rows


def write_rows(path, values, fields):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(values)


def prepare(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError('New destination required; preserve the original export')
    points = rows(source / 'points.csv')
    keys = rows(source / 'keyframes.csv')
    obs = rows(source / 'observations.csv')
    descriptors = (source / 'observation_descriptors.bin').read_bytes()
    if not points or not keys or not obs or len(descriptors) != 32 * len(obs):
        raise ValueError('Incomplete source export')
    pids = {int(p['point_id']) for p in points}
    kids = {int(k['keyframe_id']) for k in keys}
    if len(pids) != len(points) or len(kids) != len(keys):
        raise ValueError('Duplicate source point/keyframe IDs')
    selected = {}
    for i, o in enumerate(obs):
        pair = int(o['point_id']), int(o['keyframe_id'])
        error = float(o['error_px'])
        feature = int(o['feature_index'] if 'feature_index' in o else o['record_index'])
        if (pair[0] not in pids or pair[1] not in kids or
                int(o['descriptor_row']) != i or feature < 0 or
                not math.isfinite(error) or not 0 <= error <= 3):
            raise ValueError('Invalid source observation association/reprojection')
        rank = error, feature, i
        if pair not in selected or rank < selected[pair][0]:
            selected[pair] = rank, i
    support = defaultdict(list)
    for _, i in selected.values():
        support[int(obs[i]['point_id'])].append(i)
    # Count exported distinct keyframes, not the unfiltered SLAM observation count.
    retained = {pid for pid, indices in support.items() if len(indices) >= 3}
    if not retained:
        raise ValueError('No point has three reliable distinct keyframe observations')
    indices = sorted(i for pid in retained for i in support[pid])
    new_row = {old: new for new, old in enumerate(indices)}
    out_obs = []
    for old in indices:
        o = dict(obs[old])
        o['descriptor_row'] = new_row[old]
        o['observations'] = len(support[int(o['point_id'])])
        out_obs.append(o)
    popcount = [bin(i).count('1') for i in range(256)]
    out_points, representatives = [], bytearray()
    for point in points:
        pid = int(point['point_id'])
        if pid not in retained:
            continue
        candidates = sorted(support[pid])
        vectors = {i: descriptors[i*32:(i+1)*32] for i in candidates}
        def score(i):
            distances = sorted(sum(popcount[a ^ b] for a, b in zip(vectors[i], vectors[j]))
                               for j in candidates)
            return distances[len(distances)//2] + distances[(len(distances)-1)//2], i
        best = min(candidates, key=score)
        p = dict(point)
        p['observations'] = len(candidates)
        p['representative_observation_row'] = new_row[best]
        out_points.append(p)
        representatives.extend(vectors[best])
    destination.mkdir(parents=True)
    write_rows(destination / 'points.csv', out_points, list(out_points[0]))
    write_rows(destination / 'observations.csv', out_obs, list(out_obs[0]))
    (destination / 'observation_descriptors.bin').write_bytes(
        b''.join(descriptors[i*32:(i+1)*32] for i in indices))
    (destination / 'representative_descriptors.bin').write_bytes(representatives)
    for name in ('keyframes.csv', 'map_id.txt'):
        shutil.copyfile(source / name, destination / name)
    report = dict(policy='minimum reprojection error, feature index, source row; >=3 distinct keyframes',
                  input_points=len(points), output_points=len(out_points), keyframes=len(keys),
                  input_observations=len(obs), output_observations=len(out_obs),
                  duplicate_observations=len(obs)-len(selected),
                  insufficient_support_points=len(points)-len(out_points),
                  source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in source.iterdir() if p.is_file()})
    (destination / 'export_selection.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path)
    p.add_argument('destination', type=Path)
    a = p.parse_args()
    print(json.dumps(prepare(a.source, a.destination), indent=2))
