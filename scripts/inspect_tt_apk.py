"""Read-only APK/DEX structure audit; never loads Android/native app code.

Computer/PS diagnostic software. Standard library only. Output is a JSON report,
not an extracted/repacked/modified application. No drone networking exists here.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import zipfile
import zlib

LIMIT = 128 * 1024 * 1024


class Dex:
    def __init__(self, data):
        self.data = data
        if not data.startswith(b'dex\n') or len(data) < 112:
            raise ValueError('Not a standard DEX file')
        if self.u32(40) != 0x12345678:
            raise ValueError('Unexpected DEX endianness')
        string_count, string_offset = self.pair(56)
        self.strings = []
        for i in range(string_count):
            offset = self.u32(string_offset + 4*i)
            _, offset = self.uleb(offset)
            end = data.index(b'\0', offset)
            self.strings.append(data[offset:end].decode('utf-8', 'replace'))
        type_count, type_offset = self.pair(64)
        self.types = [self.strings[self.u32(type_offset+4*i)] for i in range(type_count)]
        proto_count, proto_offset = self.pair(72)
        self.protos = []
        for i in range(proto_count):
            _, ret, parameters = struct.unpack_from('<III', data, proto_offset+12*i)
            args = [] if not parameters else [self.types[x] for x in struct.unpack_from(
                '<' + 'H'*self.u32(parameters), data, parameters+4)]
            self.protos.append('(' + ''.join(args) + ')' + self.types[ret])
        method_count, method_offset = self.pair(88)
        self.methods = []
        for i in range(method_count):
            cls, proto, name = struct.unpack_from('<HHI', data, method_offset+8*i)
            self.methods.append((self.types[cls], self.strings[name], self.protos[proto]))

    def u32(self, offset):
        return struct.unpack_from('<I', self.data, offset)[0]

    def pair(self, offset):
        return struct.unpack_from('<II', self.data, offset)

    def uleb(self, offset):
        value = 0
        for shift in range(0, 35, 7):
            part = self.data[offset]
            offset += 1
            value |= (part & 127) << shift
            if part < 128:
                return value, offset
        raise ValueError('Malformed ULEB128')

    def audit(self):
        rows = []
        class_count, class_offset = self.pair(96)
        for i in range(class_count):
            fields = struct.unpack_from('<8I', self.data, class_offset+32*i)
            classname, offset = self.types[fields[0]], fields[6]
            if not offset or not classname.startswith('Lcom/ryzerobotics/tello/gcs/'):
                continue
            counts = []
            for _ in range(4):
                count, offset = self.uleb(offset)
                counts.append(count)
            for _ in range(counts[0] + counts[1]):
                _, offset = self.uleb(offset)
                _, offset = self.uleb(offset)
            for count in counts[2:]:
                index = 0
                for _ in range(count):
                    delta, offset = self.uleb(offset)
                    flags, offset = self.uleb(offset)
                    code_offset, offset = self.uleb(offset)
                    index += delta
                    if not code_offset:
                        continue
                    cls, name, proto = self.methods[index]
                    registers, ins, outs, tries, debug, units = struct.unpack_from(
                        '<4H2I', self.data, code_offset)
                    code = self.data[code_offset+16:code_offset+16+units*2]
                    if len(code) != units*2:
                        raise ValueError('Truncated DEX code item')
                    if code[:2] == b'\x0e\0':
                        stub = 'return-void' if not any(code[2:]) else 'return-first-other-data'
                    elif code[:4] in (b'\x12\0\x0f\0', b'\x12\0\x11\0'):
                        stub = 'return-zero-or-null' if not any(code[4:]) else 'zero-return-first-other-data'
                    elif code[:6] == b'\x16\0\0\0\x10\0':
                        stub = 'return-wide-zero' if not any(code[6:]) else 'wide-return-first-other-data'
                    else:
                        stub = 'other'
                    rows.append(dict(class_name=cls, method=name, prototype=proto,
                        code_offset=code_offset, code_offset_hex=hex(code_offset),
                        registers=registers, incoming_registers=ins, outgoing_registers=outs,
                        tries=tries, debug_offset=debug, debug_in_file=debug == 0 or debug < len(self.data),
                        instruction_units=units, first_16_bytes=code[:16].hex(' '),
                        nonzero_bytes=sum(x != 0 for x in code), pattern=stub))
        return dict(magic=self.data[:8].decode('ascii', 'replace'),
            actual_size=len(self.data), declared_size=self.u32(32),
            sha256=hashlib.sha256(self.data).hexdigest(),
            header_sha1_matches=hashlib.sha1(self.data[32:]).digest() == self.data[12:32],
            header_adler32_matches=zlib.adler32(self.data[12:]) == self.u32(8),
            gcs_methods_with_code=len(rows), patterns=dict(Counter(r['pattern'] for r in rows)),
            invalid_debug_offsets=sum(not r['debug_in_file'] for r in rows), methods=rows)


def inspect(apk):
    if apk.stat().st_size > LIMIT:
        raise ValueError('APK exceeds diagnostic size bound')
    with apk.open('rb') as source:
        apk_sha256 = hashlib.file_digest(source, 'sha256').hexdigest()
    report = dict(apk_name=apk.name, apk_size=apk.stat().st_size,
                  apk_sha256=apk_sha256,
                  static_only=True, application_executed=False, drone_commands_sent=False)
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        report['archive_entries'] = len(names)
        selected = [n for n in names if n.startswith(('assets/ijm', 'assets/ijiami', 'assets/asr/'))
                    or n in ('assets/af.bin','assets/signed.bin')]
        report['protection_assets'] = []
        for name in selected:
            info = archive.getinfo(name)
            if info.file_size > LIMIT:
                raise ValueError('Asset exceeds diagnostic size bound')
            with archive.open(name) as stream:
                prefix = stream.read(32)
            report['protection_assets'].append(dict(name=name, size=info.file_size,
                prefix_hex=prefix.hex(' '), crc32=f'{info.CRC:08x}'))
        report['dex'] = []
        for name in names:
            if name.startswith('classes') and name.endswith('.dex') and '/' not in name:
                if archive.getinfo(name).file_size > LIMIT:
                    raise ValueError('DEX exceeds diagnostic size bound')
                report['dex'].append(dict(entry=name, **Dex(archive.read(name)).audit()))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.apk.resolve() == args.output.resolve():
        parser.error('Output must not overwrite the APK')
    report = inspect(args.apk)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
    for dex in report['dex']:
        print(json.dumps({k:v for k,v in dex.items() if k != 'methods'}, indent=2))
        for cls in ('ZOCmdSendManager', '/flight/b;', '/core/d;', 'RockerView'):
            matching = [r for r in dex['methods'] if cls in r['class_name']]
            print(cls, 'methods=', len(matching), 'patterns=', dict(Counter(r['pattern'] for r in matching)))
    print('Saved:', args.output)


if __name__ == '__main__':
    main()
