"""Remove fixed generated child directories of this checkout, never shared caches."""
from pathlib import Path
import shutil

root=Path(__file__).resolve().parent.parent
for name in ['.venv-native','.venv-faiss','.venv-servers','.cache','data','runs']:
    target=root/name
    if target.is_symlink():raise RuntimeError('Refusing symlink: '+name)
    if target.exists():
        if target.resolve().parent!=root:raise RuntimeError('Target escaped checkout: '+name)
        size=sum(p.stat().st_size for p in target.rglob('*') if p.is_file())
        shutil.rmtree(target)
        print(name,size,'bytes removed')
