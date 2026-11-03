"""Create a real GLES2 pbuffer and verify GPU pixel output, with no display changes."""
from __future__ import annotations

import argparse
import ctypes as C
import json
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--library', required=True, help='Explicit platform EGL/GLES library, e.g. the installed Mali headless library')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    record = {'status': 'FAILED', 'scope': 'GLES2 pbuffer hardware smoke; not desktop-window or point-cloud acceptance', 'library': a.library}
    lib = C.CDLL(a.library, mode=C.RTLD_GLOBAL)
    P, I, U = C.c_void_p, C.c_int, C.c_uint
    def bind(name, result, args):
        f = getattr(lib, name); f.restype = result; f.argtypes = args; return f
    get_display = bind('eglGetDisplay', P, [P])
    initialize = bind('eglInitialize', U, [P, C.POINTER(I), C.POINTER(I)])
    choose = bind('eglChooseConfig', U, [P, C.POINTER(I), C.POINTER(P), I, C.POINTER(I)])
    bind_api = bind('eglBindAPI', U, [U])
    surface_create = bind('eglCreatePbufferSurface', P, [P, P, C.POINTER(I)])
    context_create = bind('eglCreateContext', P, [P, P, P, C.POINTER(I)])
    make_current = bind('eglMakeCurrent', U, [P, P, P, P])
    egl_error = bind('eglGetError', I, [])
    gl_string = bind('glGetString', C.c_char_p, [U])
    clear_color = bind('glClearColor', None, [C.c_float]*4)
    clear = bind('glClear', None, [U])
    finish = bind('glFinish', None, [])
    read_pixels = bind('glReadPixels', None, [I, I, I, I, U, U, P])
    gl_error = bind('glGetError', U, [])
    terminate = bind('eglTerminate', U, [P])
    display = context = surface = None
    try:
        display = get_display(None)
        major, minor = I(), I()
        if not display or not initialize(display, C.byref(major), C.byref(minor)):
            raise RuntimeError(f'eglInitialize failed: {egl_error():#x}')
        attrs = (I*13)(0x3033, 1, 0x3040, 4, 0x3024, 8, 0x3023, 8, 0x3022, 8, 0x3021, 8, 0x3038)
        config, count = P(), I()
        if not choose(display, attrs, C.byref(config), 1, C.byref(count)) or count.value != 1:
            raise RuntimeError(f'No ES2 RGBA8 pbuffer config: {egl_error():#x}')
        if not bind_api(0x30A0):
            raise RuntimeError('Could not select GLES API')
        surface = surface_create(display, config, (I*5)(0x3057, 64, 0x3056, 64, 0x3038))
        context = context_create(display, config, None, (I*3)(0x3098, 2, 0x3038))
        if not surface or not context or not make_current(display, surface, surface, context):
            raise RuntimeError(f'ES2 context creation failed: {egl_error():#x}')
        record.update(egl_version=f'{major.value}.{minor.value}', vendor=gl_string(0x1F00).decode(),
                      renderer=gl_string(0x1F01).decode(), gl_version=gl_string(0x1F02).decode())
        if any(x in record['renderer'].lower() for x in ('llvmpipe', 'softpipe', 'software')):
            raise RuntimeError('Hardware rendering required')
        clear_color(0.2, 0.5, 0.8, 1.0); clear(0x4000); finish()
        pixel = (C.c_ubyte*4)()
        read_pixels(32, 32, 1, 1, 0x1908, 0x1401, pixel)
        error = gl_error()
        record.update(pixel=list(pixel), gl_error=error)
        if error or any(abs(int(x)-y)>1 for x,y in zip(pixel, (51,128,204,255))):
            raise RuntimeError('GPU pixel readback mismatch')
        record['status'] = 'HARDWARE_GLES2_PBUFFER_PASS'
    except Exception as e:
        record['error'] = str(e)
    finally:
        if display:
            if context: make_current(display, None, None, None)
            if surface: bind('eglDestroySurface', U, [P,P])(display, surface)
            if context: bind('eglDestroyContext', U, [P,P])(display, context)
            terminate(display)
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(record))
    raise SystemExit(record['status'] != 'HARDWARE_GLES2_PBUFFER_PASS')


if __name__ == '__main__':
    main()
