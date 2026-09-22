"""加载 third_party/public_equity_investing 中的原插件脚本（原样引入，未修改）。

原插件多个技能里有同名模块（如两个 skill_core.py），这里按文件路径加载并赋予唯一模块名，
加载期间临时把该脚本目录和插件根目录放进 sys.path，以满足其内部的相对导入。
"""

from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1] / "third_party" / "public_equity_investing"


@lru_cache(maxsize=None)
def load(skill: str, module: str) -> ModuleType:
    scripts = ROOT / "skills" / skill / "scripts"
    path = scripts / f"{module}.py"
    if not path.exists():
        raise FileNotFoundError(path)
    name = f"pei_{skill.replace('-', '_')}__{module}"
    added = [p for p in (str(scripts), str(ROOT)) if p not in sys.path]
    sys.path[:0] = added
    # 同名兄弟模块（如 skill_core 依赖的 plan_validation）可能已被其他技能加载，先移出缓存
    shadowed = {k: sys.modules.pop(k) for k in _siblings(scripts) if k in sys.modules}
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    finally:
        for p in added:
            sys.path.remove(p)
        for k in _siblings(scripts):
            sys.modules.pop(k, None)
        sys.modules.update(shadowed)
    return mod


def _siblings(scripts: Path) -> list[str]:
    """脚本目录下的兄弟模块与子包（含其子模块），如 earnings-deep-dive 的 utils 包。"""
    names = [p.stem for p in scripts.glob("*.py")]
    pkgs = [p.name for p in scripts.iterdir() if p.is_dir() and (p / "__init__.py").exists()]
    names += pkgs + [k for k in list(sys.modules) if any(k.startswith(pkg + ".") for pkg in pkgs)]
    return names
