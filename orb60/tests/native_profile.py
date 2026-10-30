"""Bind simulation-only probes to actual generated HLS hierarchy, without edits.

Actor busy includes both execution and blocked execution. FIFO full/empty is
availability, not automatically a stall: blocked requests are counted separately.
"""
import re


def bind_profile(rtl_by_core):
    probes, fifos, assignments = [], [], []
    is_dataflow = lambda name: re.search(r'(?:_dataflow|_reduce_banked_grid)(?:_\d+(?:_s)?)?$', name) is not None

    def probe(core, name, expression):
        index = len(probes)
        probes.append(dict(core=core, name=name, expression=expression))
        assignments.append(f'assign profile_bits[{index}]={expression};\n')
        return index

    for core, (directory, top) in enumerate(rtl_by_core):
        modules = {}
        for path in directory.glob('*.v'):
            source = path.read_text()
            match = re.search(r'^module\s+(\w+)', source, re.M)
            if match:
                modules[match[1]] = source
        todo = [(top, f'core{core}')]
        while todo:
            module, hierarchy = todo.pop()
            source = modules[module]
            for child, instance, body in re.findall(
                    r'^(\w+)\s+(\w+)\s*\(\s*\n(.*?)\n\);', source, re.M | re.S):
                if child in modules and (is_dataflow(child) or re.search(r'_consume_and_select(?:_\d+)?$',child)):
                    todo.append((child, hierarchy+'.'+instance))
            if not is_dataflow(module):
                continue
            actors = re.findall(r'^wire\s+(\w+_U\d+_ap_idle)\s*;', source, re.M)
            for wire in actors:
                if wire.startswith('start_for_'):
                    continue
                probe(core, hierarchy+'.'+wire.removesuffix('_ap_idle')+'.busy',
                      '!'+hierarchy+'.'+wire)
            # Parameters are local to each FIFO wrapper. Its four public
            # handshake ports are used; no undocumented memory cell is edited.
            pattern = r'^(\w+_fifo_w\d+_d(\d+)_\w+)\s+(\w+)\s*\(\s*\n(.*?)\n\);'
            for _, depth, instance, body in re.findall(pattern, source, re.M | re.S):
                if instance.startswith('start_for_') or re.search(r'_c\d*_U$', instance):
                    continue
                signals = dict(re.findall(r'\.(if_(?:full_n|empty_n|write|read))\((\w+)\)', body))
                if len(signals) != 4:
                    continue
                signal = lambda key: hierarchy+'.'+signals[key]
                full, empty = signal('if_full_n'), signal('if_empty_n')
                write, read = signal('if_write'), signal('if_read')
                base = hierarchy+'.'+instance
                push = probe(core, base+'.push', f'{write} && {full}')
                pop = probe(core, base+'.pop', f'{read} && {empty}')
                blocked_write = probe(core, base+'.write_blocked', f'{write} && !{full}')
                blocked_read = probe(core, base+'.read_blocked', f'{read} && !{empty}')
                fifos.append(dict(name=base, core=core, depth=int(depth), push=push, pop=pop,
                                  write_blocked=blocked_write, read_blocked=blocked_read))
    assert probes and len(probes) <= 512, f'Missing or excessive actual RTL profile probes: {len(probes)}'
    names = [x['name'] for x in probes]
    assert len(names) == len(set(names)), 'Ambiguous profile hierarchy'
    for index in range(len(probes), 512):
        assignments.append(f'assign profile_bits[{index}]=1\'b0;\n')
    header = '#define ORB60_NATIVE_PROFILE 1\n'
    header += f'constexpr unsigned PROFILE_COUNT={len(probes)},PROFILE_FIFO_COUNT={len(fifos)};\n'
    header += 'constexpr unsigned PROFILE_CORE[PROFILE_COUNT]={' + ','.join(str(x['core']) for x in probes) + '};\n'
    header += 'constexpr const char* PROFILE_NAMES[PROFILE_COUNT]={' + ','.join('"'+x['name']+'"' for x in probes) + '};\n'
    header += 'struct ProfileFifo {unsigned push,pop,depth;};\n'
    header += 'constexpr ProfileFifo PROFILE_FIFOS[PROFILE_FIFO_COUNT]={' + ','.join(
        '{%d,%d,%d}' % (x['push'],x['pop'],x['depth']) for x in fifos) + '};\n'
    return ''.join(assignments), header, dict(probes=probes, fifos=fifos,
        scope='Simulation-only: busy includes stalls; FIFO blocked requests and occupancy use actual handshakes')
