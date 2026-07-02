import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def load_bootstrap_runtime():
    test_path = Path(__file__).resolve()
    candidates = [
        test_path.parents[1] / "scripts" / "bootstrap_runtime.py",
        test_path.parents[3] / "scripts" / "bootstrap_runtime.py",
    ]
    module_path = next((path for path in candidates if path.exists()), candidates[0])
    spec = importlib.util.spec_from_file_location("bootstrap_runtime", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_version_tuple_accepts_python_311_or_newer():
    helper = load_bootstrap_runtime()

    assert helper.is_compatible_version((3, 11, 0))
    assert helper.is_compatible_version((3, 12, 4))
    assert not helper.is_compatible_version((3, 10, 9))


def test_candidate_order_prefers_explicit_env_then_private_python(tmp_path, monkeypatch):
    helper = load_bootstrap_runtime()
    runtime_dir = tmp_path / "runtime"
    private_python = runtime_dir / ".runtime" / "python" / "bin" / "python3"
    private_python.parent.mkdir(parents=True)
    private_python.write_text("#!/bin/sh\n", encoding="utf-8")
    env_python = tmp_path / "custom-python"
    env_python.write_text("#!/bin/sh\n", encoding="utf-8")

    env = {"XHS_CA_PYTHON": str(env_python), "PATH": os.environ.get("PATH", "")}
    candidates = list(helper.iter_python_candidates(runtime_dir, env))

    assert candidates[0] == ("XHS_CA_PYTHON", env_python)
    assert candidates[1] == ("private runtime", private_python)


def test_missing_python_repair_shell_is_terminal_only():
    helper = load_bootstrap_runtime()
    shell = helper.repair_missing_python_shell(Path("/Users/example/.agents/skills/data-analyze-for-zcl"))

    assert "Copy the whole command block below into macOS Terminal" not in shell
    assert "python3.12" in shell
    assert "python3.11" in shell
    assert "rm -rf \"$RUNTIME_DIR/.venv\"" in shell
    assert "Codex" not in shell


def test_install_repair_shell_uses_temporary_pip_cache():
    helper = load_bootstrap_runtime()
    shell = helper.repair_install_shell(Path("/Users/example/.agents/skills/data-analyze-for-zcl"))

    assert "PIP_CACHE_DIR=\"$(mktemp -d)\"" in shell
    assert "pip install -e \"$RUNTIME_DIR[dev]\"" in shell
    assert "\"$SKILL_DIR/scripts/xhs-ca\" doctor --strict" in shell


def test_venv_needs_rebuild_when_python_is_missing(tmp_path):
    helper = load_bootstrap_runtime()
    runtime_dir = tmp_path / "runtime"
    (runtime_dir / ".venv").mkdir(parents=True)

    assert helper.venv_needs_rebuild(runtime_dir)


def test_package_check_reports_missing_runtime_assets(tmp_path):
    helper = load_bootstrap_runtime()
    runtime_dir = tmp_path / "runtime"
    skill_dir = tmp_path / "skill"

    missing = helper.missing_package_files(runtime_dir, skill_dir)

    assert runtime_dir / "pyproject.toml" in missing
    assert runtime_dir / "xhs_ceramics_analytics" in missing
    assert skill_dir / "scripts" / "xhs-ca" in missing


def test_python_version_returns_none_for_non_executable_file(tmp_path):
    helper = load_bootstrap_runtime()
    binary = tmp_path / "python3"
    binary.write_text("not executable\n", encoding="utf-8")

    assert helper.python_version(binary) is None


def test_main_prints_repair_kit_for_incomplete_skill_package(tmp_path, capsys):
    helper = load_bootstrap_runtime()
    runtime_dir = tmp_path / "runtime"
    skill_dir = tmp_path / "skill"
    runtime_dir.mkdir()
    skill_dir.mkdir()

    exit_code = helper.main(
        [
            "--runtime-dir",
            str(runtime_dir),
            "--skill-dir",
            str(skill_dir),
            "--doctor-root",
            str(runtime_dir),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Copy the whole command block below into macOS Terminal" in captured.err
    assert "npx skills add seyseyseyz/data-analyze-for-zcl -g -y" in captured.err
    assert "Traceback" not in captured.err


def test_bootstrap_wrappers_accept_python311_without_python3(tmp_path):
    test_path = Path(__file__).resolve()
    bootstrap_scripts = [
        candidate
        for candidate in (
            test_path.parents[1] / "scripts" / "bootstrap",
            test_path.parents[1] / "skills" / "data-analyze-for-zcl" / "scripts" / "bootstrap",
            test_path.parents[3] / "scripts" / "bootstrap",
        )
        if candidate.exists()
    ]
    assert bootstrap_scripts
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "python-args.log"
    fake_python = bin_dir / "python3.11"
    fake_python.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" >> {log_file!s}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    fake_dirname = bin_dir / "dirname"
    fake_dirname.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  */*) printf '%s\\n' \"${1%/*}\" ;;\n"
        "  *) printf '.\\n' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_dirname.chmod(0o755)
    fake_cat = bin_dir / "cat"
    fake_cat.write_text("#!/bin/sh\n/bin/cat \"$@\"\n", encoding="utf-8")
    fake_cat.chmod(0o755)
    env = {"PATH": str(bin_dir)}

    for script in bootstrap_scripts:
        result = subprocess.run(
            ["/bin/bash", str(script)],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        assert result.returncode == 0, result.stderr

    logged = log_file.read_text(encoding="utf-8")
    for script in bootstrap_scripts:
        assert str(script.parent / "bootstrap_runtime.py") in logged


def test_main_prints_repair_kit_when_install_command_cannot_start(tmp_path, monkeypatch, capsys):
    helper = load_bootstrap_runtime()
    runtime_dir = tmp_path / "runtime"
    skill_dir = tmp_path / "skill"
    (runtime_dir / "xhs_ceramics_analytics").mkdir(parents=True)
    (runtime_dir / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (runtime_dir / ".venv" / "bin").mkdir(parents=True)
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "scripts" / "bootstrap").write_text("#!/bin/sh\n", encoding="utf-8")
    (skill_dir / "scripts" / "xhs-ca").write_text("#!/bin/sh\n", encoding="utf-8")
    python = helper.PythonCandidate("test", tmp_path / "python3.11", (3, 11, 0))
    monkeypatch.setattr(helper, "resolve_python", lambda runtime: python)
    monkeypatch.setattr(helper, "venv_needs_rebuild", lambda runtime: False)

    def raise_os_error(*args, **kwargs):
        raise OSError("cannot launch subprocess")

    monkeypatch.setattr(helper.subprocess, "run", raise_os_error)

    exit_code = helper.main(
        [
            "--runtime-dir",
            str(runtime_dir),
            "--skill-dir",
            str(skill_dir),
            "--doctor-root",
            str(runtime_dir),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Python dependency installation failed" in captured.err
    assert "Copy the whole command block below into macOS Terminal" in captured.err
    assert "Traceback" not in captured.err


def test_main_prints_repair_kit_when_pip_cache_cannot_be_created(tmp_path, monkeypatch, capsys):
    helper = load_bootstrap_runtime()
    runtime_dir = tmp_path / "runtime"
    skill_dir = tmp_path / "skill"
    (runtime_dir / "xhs_ceramics_analytics").mkdir(parents=True)
    (runtime_dir / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (runtime_dir / ".venv" / "bin").mkdir(parents=True)
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "scripts" / "bootstrap").write_text("#!/bin/sh\n", encoding="utf-8")
    (skill_dir / "scripts" / "xhs-ca").write_text("#!/bin/sh\n", encoding="utf-8")
    python = helper.PythonCandidate("test", tmp_path / "python3.11", (3, 11, 0))
    monkeypatch.setattr(helper, "resolve_python", lambda runtime: python)
    monkeypatch.setattr(helper, "venv_needs_rebuild", lambda runtime: False)
    original_mkdir = helper.Path.mkdir

    def failing_mkdir(self, *args, **kwargs):
        if str(self).endswith("pip-cache"):
            raise OSError("cannot create pip cache")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(helper.Path, "mkdir", failing_mkdir)

    exit_code = helper.main(
        [
            "--runtime-dir",
            str(runtime_dir),
            "--skill-dir",
            str(skill_dir),
            "--doctor-root",
            str(runtime_dir),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Python dependency installation failed" in captured.err
    assert "Copy the whole command block below into macOS Terminal" in captured.err
    assert "Traceback" not in captured.err
