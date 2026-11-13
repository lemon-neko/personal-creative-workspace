import json

import pytest

from app.plugin_packages import HUB_ENTRYPOINTS, VERSIONS, WEB_ENTRYPOINTS, tree_hash, verify_packages


@pytest.fixture
def packages(tmp_path):
    for name, entries in (("web", WEB_ENTRYPOINTS), ("autoloop", HUB_ENTRYPOINTS)):
        for entry in entries:
            path = tmp_path / name / entry
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")
    manifest = {
        "versions": dict(VERSIONS),
        "sha256": {name: tree_hash(tmp_path / name) for name in ("web", "autoloop")},
    }
    (tmp_path / "packages.json").write_text(json.dumps(manifest))
    return tmp_path, manifest


@pytest.mark.parametrize(("problem", "expected"), [
    ("version", "版本"), ("hash", "校验"), ("missing", "必要入口"),
    ("symlink", "符号链接"), ("manifest", "JSON"), ("schema", "SHA-256"),
])
def test_packages_validate_independently(packages, problem, expected):
    root, manifest = packages
    verify_packages(root)
    path = root / "web" / WEB_ENTRYPOINTS[-1]
    if problem == "version":
        manifest["versions"]["super-productivity"] = "99.0.0"
    elif problem == "hash":
        path.write_text("tampered")
    elif problem == "missing":
        path.unlink()
    elif problem == "symlink":
        path.unlink()
        path.symlink_to(root / "autoloop" / HUB_ENTRYPOINTS[0])
    elif problem == "schema":
        manifest["sha256"]["web"] = []
    (root / "packages.json").write_text("{" if problem == "manifest" else json.dumps(manifest))
    with pytest.raises(ValueError, match=expected):
        verify_packages(root, package="web")
    if problem != "manifest":
        verify_packages(root, package="autoloop")


def test_manifest_and_package_root_symlinks_are_rejected(packages, tmp_path):
    root, _ = packages
    path = root / "packages.json"
    private = tmp_path / "other.json"
    path.rename(private)
    path.symlink_to(private)
    with pytest.raises(ValueError, match="路径无效"):
        verify_packages(root)
    with pytest.raises(ValueError, match="目录无效"):
        path.unlink()
        path.symlink_to(root / "web", target_is_directory=True)
        tree_hash(path)
