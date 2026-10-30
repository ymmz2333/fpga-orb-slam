"""Computer-side TT recording controls and offline, lossless H.264 -> MP4 export.

No network or aircraft commands. Export runs outside the decoder/control processes.
MP4 uses nominal 30 fps; receive/decode timing remains in the JSONL sidecars.
"""
from datetime import datetime
from fractions import Fraction
import io
import json
from pathlib import Path
import queue
import signal
import time
from uuid import uuid4

import av
from tt_latency_recording import PacketRecorder


class RecorderSink:
    """Recording failures are reported, never allowed to stop video/control."""
    def __init__(self, reports=None):
        self.recorder = PacketRecorder()
        self.reports = reports

    def report(self, event, **fields):
        if self.reports is not None:
            self.reports.put(dict(event=event,**fields))

    def call(self, method, *args):
        try:
            return getattr(self.recorder,method)(*args)
        except (OSError, ValueError) as exc:
            directory = str(self.recorder.directory)
            for handle in self.recorder.handles:
                try:
                    handle.close()
                except OSError:
                    pass
            self.recorder = PacketRecorder()
            self.report('record_error',directory=directory,error=str(exc))

    def start(self, directory, kind='latency',metadata=None):
        self.close()
        self.recorder.directory = Path(directory)
        self.call('start',directory,kind,metadata)
        if self.recorder.handles:
            self.report('started',directory=str(self.recorder.directory),kind=kind)

    def close(self):
        if not self.recorder.handles:
            return
        directory, kind = str(self.recorder.directory), self.recorder.kind
        self.call('close')
        if str(self.recorder.directory) == directory:
            self.report('closed',directory=directory,kind=kind)

    def packet(self, *args):
        self.call('packet',*args)

    def frame(self, *args):
        self.call('frame',*args)


class PrefixedReader(io.RawIOBase):
    """Sequential input: cached SPS/PPS followed by the recorded Annex-B stream."""
    def __init__(self, prefix, source):
        super().__init__()
        self.prefix = io.BytesIO(prefix)
        self.source = source

    def readable(self):
        return True

    def readinto(self, target):
        payload = self.prefix.read(len(target))
        if len(payload) < len(target):
            payload += self.source.read(len(target) - len(payload))
        target[:len(payload)] = payload
        return len(payload)


def export_mp4(directory):
    directory = Path(directory)
    capture = json.loads((directory / 'capture.json').read_text(encoding='utf-8'))
    if not capture.get('closed') or not capture.get('packets'):
        raise ValueError('Recording must be closed and contain video packets')
    target = directory / 'video.mp4'
    if target.exists():
        raise FileExistsError(target)
    temporary = directory / 'video.partial.mp4'
    if temporary.exists():
        raise FileExistsError(temporary)
    fps = capture.get('nominal_fps', 30)
    count = 0
    try:
        with (directory / 'packets.h264').open('rb') as raw:
            prefix = (directory / 'codec_headers.h264').read_bytes()
            with io.BufferedReader(PrefixedReader(prefix, raw)) as source:
                with av.open(source, format='h264', options={'framerate': str(fps)}) as incoming:
                    video = incoming.streams.video[0]
                    # Assigning PTS=DTS is valid only for the TT low-delay stream.
                    # Do not silently produce incorrect timestamps for B-frame input.
                    if video.codec_context.has_b_frames:
                        raise ValueError('B-frame stream requires a different timestamp reconstruction')
                    with av.open(str(temporary), 'w', format='mp4') as outgoing:
                        stream = outgoing.add_stream_from_template(video)
                        for packet in incoming.demux(video):
                            if not packet.size:
                                continue
                            if count == 0 and not packet.is_keyframe:
                                continue
                            packet.pts = packet.dts = count
                            packet.duration = 1
                            packet.time_base = Fraction(1, fps)
                            packet.stream = stream
                            outgoing.mux(packet)
                            count += 1
        if count == 0:
            raise ValueError('No decodable keyframe in recording; raw packets retained')
        temporary.replace(target)
    except Exception:
        # Delete only this export's partial file; always retain original packet data.
        temporary.unlink(missing_ok=True)
        raise
    result = dict(file=str(target),packets=count,nominal_fps=fps,
                  duration_s=count/fps,reencoded=False,
                  timing='Constant nominal fps including keyframe preroll; use frames.jsonl for PC timing')
    (directory / 'playback.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def export_worker(jobs, reports):
    signal.signal(signal.SIGINT,signal.SIG_IGN)
    while True:
        directory = jobs.get()
        if directory is None:
            return
        try:
            result = export_mp4(directory)
            reports.put(dict(event='exported',directory=directory,**result))
        except Exception as exc:
            result = dict(event='export_error',directory=directory,error=str(exc))
            try:
                (Path(directory)/'export_error.json').write_text(json.dumps(result),encoding='utf-8')
            except OSError:
                pass
            reports.put(result)


class CaptureControls:
    """GUI-only coordinator. Recorder state is confirmed by receiver reports."""
    def __init__(self, ctx, commands, reports, output, kind,metadata=None):
        self.ctx, self.commands, self.reports = ctx, commands, reports
        self.output, self.kind = Path(output), kind
        self.metadata = metadata or {}
        self.active = None
        self.state = 'IDLE'
        self.message = ''
        self.clips = []
        self.jobs = ctx.Queue()
        self.exporter = None
        self.exported_directories = set()

    def toggle(self, video_available=True):
        if self.active is not None:
            self.stop()
        elif self.state not in ('STARTING','STOPPING'):
            if not video_available:
                self.message = 'No live video yet - recording not started'
                return
            directory = self.output / datetime.now().strftime(self.kind+'_%Y%m%dT%H%M%S_%f')
            directory = directory.with_name(directory.name+'_'+uuid4().hex[:8])
            self.active = str(directory)
            self.started = time.perf_counter()
            self.state = 'STARTING'
            self.commands.put(dict(action='start',directory=self.active,kind=self.kind,metadata=self.metadata))
            self.clips.append(self.active)
            print('RECORDING_START_REQUESTED '+self.active,flush=True)

    def stop(self):
        if self.active is not None and self.state != 'STOPPING':
            self.commands.put(dict(action='stop'))
            self.state = 'STOPPING'

    def poll(self):
        if self.exporter is not None and not self.exporter.is_alive() and self.exporter.exitcode:
            self.message = 'Export process failed; raw captures retained'
        while True:
            try:
                row = self.reports.get_nowait()
            except queue.Empty:
                break
            event = row['event']
            print('RECORDING '+json.dumps(row),flush=True)
            if event == 'started' and row['directory'] == self.active:
                if self.state != 'STOPPING':
                    self.state = 'RECORDING'
            elif event in ('closed','record_error'):
                if row.get('directory') == self.active:
                    self.active = None
                    self.state = 'IDLE' if event == 'closed' else 'ERROR'
                if event == 'closed' and row.get('kind') != 'latency':
                    directory = row['directory']
                    if directory not in self.exported_directories:
                        if self.exporter is None:
                            self.exporter = self.ctx.Process(target=export_worker,args=(self.jobs,self.reports))
                            self.exporter.start()
                        self.exported_directories.add(directory)
                        self.jobs.put(directory)
                    self.message = 'Saved raw video; MP4 export in background'
                elif event == 'record_error':
                    self.message = 'Recording error: '+row['error']
            elif event == 'exported':
                self.message = 'MP4 saved: '+str(Path(row['directory']).name)+'/video.mp4'
            elif event == 'export_error':
                self.message = 'MP4 export failed; see export_error.json; raw retained'

    def snapshot(self):
        return dict(recording_state=self.state,recording_directory=self.active,
                    recording_kind=self.kind,video_recordings=list(self.clips),
                    recording_message=self.message)

    def label(self):
        if self.active:
            return f'REC {self.kind} {time.perf_counter()-self.started:.1f}s [{self.state}] | R: stop'
        return 'R: record '+self.kind+' | '+self.message

    def finish(self):
        # Call after receiver join: its finally closes the current raw recording.
        self.poll()
        if self.active:
            self.state = 'ERROR'
            self.message = 'Recording closure unconfirmed; inspect raw capture before reuse'
        if self.exporter is not None:
            self.jobs.put(None)
            while self.exporter.is_alive():
                self.exporter.join(.25)
                self.poll()
            self.poll()
            if self.exporter.exitcode:
                self.message = 'Export process failed; raw captures retained'


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',help='Completed raw recording directory')
    args = parser.parse_args()
    print(json.dumps(export_mp4(args.directory),indent=2))
