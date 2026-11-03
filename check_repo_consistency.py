"""Check current package identity and reproducible PyPI quickstart documentation."""
import ast
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parent


def main():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "antemortem-structural-lab"
    assert project["version"] == "0.8.2"
    module = ast.parse((ROOT / "tomolab/__init__.py").read_text(encoding="utf-8"))
    versions = [node.value.value for node in module.body if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)]
    assert versions == [project["version"]]
    assert project["scripts"]["antemortem-structural-lab"] == project["scripts"]["tomolab"]
    assert not project.get("dependencies")
    for name in ("README.md", "README.ko.md"):
        raw = (ROOT / name).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8")
        for token in ("0.8.2", "v0.8.2", "pip install antemortem-structural-lab", "uvx antemortem-structural-lab --help", "```diff", "M0_HOLD", "NOT_ESTABLISHED"):
            assert token in text, (name, token)
        for marker in ("<!-- QUICKSTART_DEMO_START -->", "<!-- QUICKSTART_DEMO_END -->"):
            assert text.count(marker) == 1, (name, marker)
        forbidden = r"enterprise|open-core|saas|commercial|trading|alpha mining|hedge fund|(?<!omega-)citadel|omegasextant|omega aile"
        assert not re.search(forbidden, text, re.I), name
    print("CONSISTENCY PASS: version 0.8.2, PyPI/uvx, bilingual demo and research boundaries")


if __name__ == "__main__":
    main()
