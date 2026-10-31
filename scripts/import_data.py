"""Extract only the 17 supplied CSVs to local data/raw (ignored by Git)."""
from pathlib import Path
from zipfile import ZipFile
import sys

if len(sys.argv)!=2:
    raise SystemExit('사용법: python scripts/import_data.py "제공된_식자재_데이터.zip"')
source=Path(sys.argv[1])
if not source.is_file(): raise SystemExit(f'파일이 없습니다: {source}')
root=Path(__file__).resolve().parents[1]
target=root/'data'/'raw'
target.mkdir(parents=True,exist_ok=True)
extracted={}
with ZipFile(source) as z:
    for item in z.infolist():
        base=Path(item.filename).name
        if len(base)>3 and base[:2].isdigit() and base[2]=='_' and base.endswith('.csv'):
            # Do not trust archive directory paths; use simple checked basename.
            if int(base[:2]) in range(1,18):
                (target/base).write_bytes(z.read(item));extracted[int(base[:2])]=base
missing=sorted(set(range(1,18))-set(extracted))
if missing: raise SystemExit(f'일부 CSV가 누락되었습니다: {missing}')
print(f'로컬 비공개 데이터 17개 파일 준비 완료: {target}')
