import pathlib
import sys
import zipfile

dest = pathlib.Path(sys.argv[2]).resolve()
root = pathlib.Path(__file__).resolve().parent.parent / 'exam_verilog'
if not dest.is_relative_to(root) or dest == root:
    raise ValueError('Select a question folder inside exam_verilog.')
with zipfile.ZipFile(sys.argv[1]) as archive:
    files = []
    for item in archive.infolist():
        target = (dest / item.filename).resolve()
        if not target.is_relative_to(dest):
            raise ValueError('Unsafe archive path: ' + item.filename)
        if not item.is_dir():
            if target.exists():
                raise ValueError('File already exists; import into a new question folder: ' + str(target))
            files.append((item, target))
    for item, target in files:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(item))
print('Imported', len(files), 'files.')
