import importlib
import pkgutil
from pathlib import Path

import qickodes


def import_submodules(module_name: str, module_path: Path):
    for _, name, _ in pkgutil.iter_modules([str(module_path)]):
        submodule_name = module_name + "." + name
        submodule_path = module_path / name
        importlib.import_module(submodule_name)
        if submodule_path.is_dir():
            import_submodules(submodule_name, submodule_path)


def test_import_all_modules():

    import_submodules("qickodes", Path(qickodes.__path__[0]))
