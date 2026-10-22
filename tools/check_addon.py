"""Structural and syntax checks, not Odoo installation/integration tests."""
import ast
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
addon = root / "alvina_pos_comprobantes"
manifest = ast.literal_eval((addon / "__manifest__.py").read_text())
for path in root.rglob("*.py"):
    if ".venv" not in path.parts:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                parent = path.parent
                for _ in range(node.level - 1):
                    parent = parent.parent
                modules = [node.module] if node.module else [alias.name for alias in node.names]
                for module in modules:
                    target = parent.joinpath(*module.split("."))
                    assert target.with_suffix(".py").is_file() or (target / "__init__.py").is_file(), \
                        f"Unresolved relative import {module} in {path}"
for name in manifest["data"]:
    assert (addon / name).is_file(), f"Missing data: {name}"
for bundle in manifest["assets"].values():
    for name in bundle:
        assert (root / name).is_file(), f"Missing asset: {name}"
for path in addon.rglob("*.xml"):
    ET.parse(path)
for path in addon.rglob("*.js"):
    subprocess.run(["node", "--input-type=module", "--check"], input=path.read_text(), text=True, check=True)
assert manifest["version"].startswith("19.0.")
assert {"point_of_sale", "l10n_pe"} <= set(manifest["depends"])
print("OK: Python AST/relative imports, XML, JavaScript syntax, manifest data/assets and Odoo 19 dependencies.")
