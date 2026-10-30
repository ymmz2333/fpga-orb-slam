#!/usr/bin/env python3
"""Rebuild median/min/max CSV solely from retained measured runs.csv."""
import argparse
import csv
import pathlib
import statistics

METRICS = ['ate_rmse_m', 'total_mean_ms', 'total_median_ms', 'total_p95_ms', 'orb_median_ms', 'orb_p95_ms',
           'orb_ratio_frame_median', 'orb_ratio_sums', 'total_gt50_fraction', 'total_gt33_fraction', 'mean_soc_temp_c']
parser = argparse.ArgumentParser()
parser.add_argument('--batch', required=True)
args = parser.parse_args()
if pathlib.Path(args.batch).name != args.batch:
    raise SystemExit('Invalid batch ID')
report = pathlib.Path(__file__).resolve().parent.parent / 'reports/a2' / args.batch
with (report / 'runs.csv').open(encoding='utf-8') as stream:
    runs = [row for row in csv.DictReader(stream) if row['valid_run'] == 'True']
summary = []
for metric in METRICS:
    values = [float(row[metric]) for row in runs if row.get(metric, '') != '']
    if values:
        summary.append(dict(configuration='A2 official nonuniform resize', tracking_width=600, tracking_height=350,
                            metric=metric, valid_runs=len(values), median=statistics.median(values), min=min(values), max=max(values)))
with (report / 'summary.csv').open('w', newline='', encoding='utf-8') as stream:
    writer = csv.DictWriter(stream, fieldnames=['configuration','tracking_width','tracking_height','metric','valid_runs','median','min','max'])
    writer.writeheader()
    writer.writerows(summary)
print('A2_CSV_SUMMARY_PASS valid_runs=%d' % len(runs))
