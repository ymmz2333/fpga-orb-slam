"""Quick C++ DDR-model tests with pin stubs; not an RTL verification claim."""
from pathlib import Path
import re
import shutil
import subprocess


def check(scratch, tests, output):
    stub=scratch/'pin_model_check';stub.mkdir()
    source=(scratch/'orb60_frame_top.sv').read_text()
    header='#pragma once\n#include <array>\n#include <cstdint>\nstruct Vorb60_frame_top {\n'
    for width,name,last in re.findall(r'(?:input|output) wire(?: \[(\d+):0\])? (\w+)(?: \[0:(\d+)\])?',source):
        kind='uint64_t' if width and int(width)>31 else 'uint32_t'
        if last: header+=f'std::array<{kind},{int(last)+1}> {name}{{}};\n'
        else: header+=f'{kind} {name}=0;\n'
    header+='void eval() {} void final() {}\n};\n'
    (stub/'Vorb60_frame_top.h').write_text(header)
    (stub/'verilated.h').write_text('struct Verilated { static void commandArgs(int,char**) {} };\n')
    for name in ('native_frame.cpp','ddr_time.hpp','native_ddr_model_test.cpp'):
        shutil.copyfile(tests/name,stub/name)
    shutil.copyfile(scratch/'frame_registers.hpp',stub/'frame_registers.hpp')
    compiler=shutil.which('g++');assert compiler
    with (output/'model_check.log').open('w') as log:
        subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','native_ddr_model_test.cpp','-o','model_test.exe'],
                       cwd=stub,stdout=log,stderr=subprocess.STDOUT,check=True)
        subprocess.run([str(stub/'model_test.exe')],cwd=stub,stdout=log,stderr=subprocess.STDOUT,check=True)
