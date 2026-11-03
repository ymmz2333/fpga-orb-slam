"""Record the pinned upstream commit when building a source archive without Git."""
import hashlib
import json
from pathlib import Path
import sys

COMMIT = 'c26eae36f034d5a2f9b2a7bfe816b8c43311a4f8'
ORIGINAL = {
    'xir/src/xir/CMakeLists.txt': 'a5ddecb0321e10e8cdae89ba7ef60576f615c2f018406615134bf51cd5509597',
    'target_factory/src/CMakeLists.txt': '11054a49f42f6fe17ab018b6f7fc3eb9a4fd5a13f3259d602b2501141955b64f',
}
INSERT = '''# KV260 archive build: upstream metadata, not a synthetic Git repository.
if(NOT PROJECT_GIT_COMMIT_ID)
  set(PROJECT_GIT_COMMIT_ID "'''+COMMIT+'''")
  set(PROJECT_GIT_BRANCH_NAME "archive-v2.5")
endif()
'''


def main():
    source = Path(sys.argv[1]) / 'src/Vitis-AI-Runtime/VART'
    record = {'upstream_commit': COMMIT, 'scope': 'build metadata only; no operators changed', 'files': []}
    for name, expected in ORIGINAL.items():
        path = source / name
        before = path.read_bytes()
        text = before.decode('utf-8')
        if INSERT in text:
            original = text.replace(INSERT, '', 1).encode('utf-8')
        else:
            original = before
        if hashlib.sha256(original).hexdigest() != expected:
            raise ValueError('Unexpected vendor source: '+name)
        original_text = original.decode('utf-8')
        anchor = 'configure_file(config/config.hpp.in config.hpp @ONLY)' if name.startswith('xir/') else 'configure_file(config.hpp.in config.hpp @ONLY)'
        if original_text.count(anchor) != 1:
            raise ValueError('Unexpected metadata template: '+name)
        after = original_text.replace(anchor, INSERT+anchor, 1).encode('utf-8')
        if after != before:
            path.write_bytes(after)
        record['files'].append({'file': name, 'before_sha256': expected, 'after_sha256': hashlib.sha256(after).hexdigest()})
    output = Path(sys.argv[2])
    output.write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
