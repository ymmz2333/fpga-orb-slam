"""Exact preview for the KV260 BGR24 -> OpenCV gray input contract."""


def run_bgr_preview(source):
    import av
    import cv2
    import zlib
    container=None;next_index=0
    try:
        container=av.open(source.path);frames=iter(container.decode(video=0))
        while not source.stop.is_set():
            source.changed.wait(.2);source.changed.clear()
            with source.lock:request=source.request;source.request=None
            if request is None:continue
            index,token=request
            with source.lock:
                if source.result and source.result[0]==token:continue
            if index<next_index:
                container.close();container=av.open(source.path);frames=iter(container.decode(video=0));next_index=0
            frame=None
            while next_index<=index and not source.stop.is_set():
                frame=next(frames);next_index+=1
            if source.stop.is_set():return
            image=frame.to_ndarray(format='bgr24')
            if image.shape!=(720,960,3):raise ValueError('Original 960x720 BGR24 frame required')
            # This is the producer's exact gray conversion. FFmpeg gray output
            # has different rounding/range semantics on some colored pixels.
            crc=zlib.crc32(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY).tobytes())
            with source.lock:source.result=(token,image,crc)
    except Exception as error:source.error='KV260 exact BGR preview failed: '+str(error)
    finally:
        if container is not None:container.close()
