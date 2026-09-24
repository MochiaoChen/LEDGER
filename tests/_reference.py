"""仅供对照测试：按文件路径加载原 Public Equity Investing 插件脚本（仓库不再包含该插件）。

查找顺序：环境变量 FINAGENT_REFERENCE_PLUGIN → 本仓库上级目录（插件原始目录）。找不到则相关测试跳过。
原插件多个技能里有同名模块（如两个 skill_core.py），这里按文件路径加载并赋予唯一模块名，
加载期间临时把脚本目录和插件根目录放进 sys.path，以满足其内部导入。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[1]
_MARKER = Path("skills") / "three-statement-model-builder" / "scripts" / "skill_core.py"


def reference_root() -> Path | None:
    for cand in (os.environ.get("FINAGENT_REFERENCE_PLUGIN"), _ROOT.parent):
        if cand and (Path(cand) / _MARKER).exists():
            return Path(cand)
    return None


@lru_cache(maxsize=None)
def load(skill: str, module: str) -> ModuleType:
    root = reference_root()
    if root is None:
        raise FileNotFoundError("未找到原插件（设置 FINAGENT_REFERENCE_PLUGIN）")
    scripts = root / "skills" / skill / "scripts"
    path = scripts / f"{module}.py"
    name = f"ref_{skill.replace('-', '_')}__{module}"
    added = [p for p in (str(scripts), str(root)) if p not in sys.path]
    sys.path[:0] = added
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
    names = [p.stem for p in scripts.glob("*.py")]
    pkgs = [p.name for p in scripts.iterdir() if p.is_dir() and (p / "__init__.py").exists()]
    return names + pkgs + [k for k in list(sys.modules) if any(k.startswith(pkg + ".") for pkg in pkgs)]
