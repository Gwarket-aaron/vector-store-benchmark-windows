"""Remove fixed generated child directories of this checkout, never shared caches."""
from pathlib import Path
import shutil
import os

root=Path(__file__).resolve().parent.parent
for name in ['.venv-native','.venv-faiss','.venv-servers','.cache','data','runs']:
    target=root/name
    if target.is_symlink():raise RuntimeError('Refusing symlink: '+name)
    if target.exists():
        if target.resolve().parent!=root:raise RuntimeError('Target escaped checkout: '+name)
        size=sum(p.stat().st_size for p in target.rglob('*') if p.is_file())
        # Payload indexes on Windows bind mounts can exceed the legacy MAX_PATH.
        deletion_path='\\\\?\\'+str(target.resolve()) if os.name=='nt' else str(target)
        shutil.rmtree(deletion_path)
        print(name,size,'bytes removed')
