"""Isolated runtime compatibility checks: no host mounts, ports or data volumes.

Run before the separate synthetic application/restore drill. Does not certify
scanner acceptance, private endpoint access or any production recovery gate.
"""
import argparse
import re
import subprocess

PYTHON_PROBE = r'''
import bz2, curses, ctypes, dbm.gnu, dbm.ndbm, gzip, hashlib, io, json, lzma
import os, pathlib, readline, sqlite3, ssl, sys, tarfile, tempfile, uuid, zipfile
import alembic, fastapi, numpy, openpyxl, pandas, pyarrow, sqlalchemy, uvicorn
assert sys.version_info[:3] == (3, 12, 15)
assert os.getuid() == 10001
data = ("FamilyFin synthetic \u05e9\u05dc\u05d5\u05dd" * 100).encode()
for compress, decompress in ((bz2.compress,bz2.decompress),(lzma.compress,lzma.decompress),(gzip.compress,gzip.decompress)):
    assert decompress(compress(data)) == data
assert ssl.create_default_context().get_ca_certs()
ctypes.CDLL("libuuid.so.1")
assert uuid.UUID(str(uuid.uuid4())).version == 4
with tempfile.TemporaryDirectory() as folder:
    root = pathlib.Path(folder)
    db = sqlite3.connect(root / 'source.sqlite3')
    db.execute('create table probe (value text)')
    db.execute('insert into probe values (?)', ('synthetic',))
    db.commit()
    target = sqlite3.connect(root / 'snapshot.sqlite3')
    db.backup(target)
    assert target.execute('pragma integrity_check').fetchone() == ('ok',)
    assert target.execute('select value from probe').fetchone() == ('synthetic',)
    target.close(); db.close()
    workbook = openpyxl.Workbook()
    workbook.active.append(['synthetic',17.4])
    workbook.save(root / 'source.xlsx')
    assert openpyxl.load_workbook(root / 'source.xlsx').active['B1'].value == 17.4
    pandas.DataFrame({'amount':[17.4]}).to_parquet(root / 'data.parquet')
    assert pandas.read_parquet(root / 'data.parquet')['amount'][0] == 17.4
    with tarfile.open(root / 'archive.tar.gz','w:gz',format=tarfile.PAX_FORMAT) as archive:
        archive.add(root / 'source.xlsx',arcname=('a'*110)+'.xlsx')
    with tarfile.open(root / 'archive.tar.gz') as archive:
        assert archive.extractfile(('a'*110)+'.xlsx').read() == (root / 'source.xlsx').read_bytes()
    for backend in (dbm.gnu,dbm.ndbm):
        with backend.open(str(root / backend.__name__),'c') as store:
            store[b'probe'] = data
            assert store[b'probe'] == data
manifest = json.loads(pathlib.Path('/usr/share/familyfin/python-runtime.json').read_text())
for entry in manifest['copied_libraries']:
    assert hashlib.sha256(pathlib.Path(entry['path']).read_bytes()).hexdigest() == entry['sha256']
    name = entry['package'].replace(':','_') + '.status'
    assert pathlib.Path('/var/lib/dpkg/status.d',name).is_file()
for path in ('/bin/sh','/usr/bin/perl','/usr/bin/mount','/usr/bin/nsenter','/usr/bin/infocmp','/usr/bin/systemd-homed','/usr/bin/dpkg','/usr/local/bin/uv'):
    assert not pathlib.Path(path).exists(), path
assert not pathlib.Path('/usr/local/lib/python3.12/ensurepip').exists()
print(json.dumps({'python':sys.version.split()[0], 'sqlite':sqlite3.sqlite_version,
                  'copied_libraries_verified':len(manifest['copied_libraries']), 'status':'PASS'}))
'''

NODE_PROBE = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),tls=require('node:tls');
assert.equal(process.versions.node,'22.23.4'); assert.equal(process.getuid(),10002);
assert(tls.rootCertificates.length>0);
for(const path of ['/bin/sh','/usr/bin/perl','/usr/bin/mount','/usr/bin/infocmp','/usr/bin/dpkg','/usr/local/bin/npm'])assert(!fs.existsSync(path),path);
require('sharp');
console.log(JSON.stringify({node:process.versions.node,sharp:require('sharp').versions.sharp,status:'PASS'}));
'''


def run(image, entrypoint, *arguments):
    command = ["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--memory", "1g", "--cpus", "2", "--pids-limit", "128",
               "--tmpfs", "/tmp:size=256m,mode=1777,nosuid,noexec", "--entrypoint", entrypoint, image, *arguments]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    print(result.stdout.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"candidate-[a-z0-9][a-z0-9.-]{0,63}", args.tag):
        raise ValueError("Explicit candidate image tag required")
    run(f"familyfin-m1-api:{args.tag}", "python", "-c", PYTHON_PROBE)
    run(f"familyfin-m1-web:{args.tag}", "node", "-e", NODE_PROBE)
    # Build fails if affected OpenPGP packages enter the exact Go dependency set.
    # Verify the shipped evidence against both files before reporting absence.
    run(f"familyfin-m1-caddy:{args.tag}", "sh", "-ec", r'''
cd /usr/share/familyfin
test -s compiled-packages.txt
sed 's|/out/caddy|/usr/bin/caddy|;s|/out/compiled-packages.txt|/usr/share/familyfin/compiled-packages.txt|' caddy.sha256 | sha256sum -c -
! grep -Eq '^golang.org/x/crypto/openpgp(/|$)' compiled-packages.txt
echo 'Caddy exact build dependency evidence: PASS; affected OpenPGP imports absent'
''')


if __name__ == "__main__":
    main()
