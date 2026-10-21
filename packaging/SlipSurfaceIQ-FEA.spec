# PyInstaller onedir: Qt DLLs stay replaceable, no installer/admin rights required.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs, copy_metadata

root = Path(SPECPATH).parent
hidden = collect_submodules('slipsurface.fe2d')
datas = copy_metadata('slipsurface-fe2d') + [(str(root / 'LICENSE'), '.')]
a = Analysis(
    [str(root / 'packaging' / 'desktop_entry.py')],
    pathex=[str(root / 'src')],
    binaries=collect_dynamic_libs('llvmlite'),
    datas=datas,
    hiddenimports=hidden,
    excludes=['pyvista', 'vtkmodules', 'PyQt5', 'PyQt6', 'tkinter', 'IPython', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SlipSurfaceIQ-FEA',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='SlipSurfaceIQ-FEA')
