"""Run both shell functions against a harmless fake console script."""
import os
from pathlib import Path
import shutil
import subprocess
import pytest


@pytest.mark.parametrize('shell', ['bash', 'zsh'])
def test_shell_last_directory(tmp_path, shell):
    executable = shutil.which(shell)
    if not executable:
        pytest.skip(f'{shell} not installed')
    target = tmp_path / '한글 공백\n폴더'
    target.mkdir()
    binary = tmp_path / 'bin'
    binary.mkdir()
    script = binary / 'm2'
    script.write_text('#!/bin/sh\nwhile [ "$#" -gt 0 ]; do\n if [ "$1" = "--last-dir-file" ]; then\n  shift\n  printf "%s" "$MOM_TEST_TARGET" > "$1"\n fi\n shift\ndone\n')
    script.chmod(0o755)
    wrapper = Path(__file__).resolve().parents[1] / 'scripts/mom-shell.sh'
    env = {**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'],
           'MOM_TEST_TARGET': str(target), 'MOM_TEST_WRAPPER': str(wrapper)}
    result = subprocess.run([executable, '-c', 'source "$MOM_TEST_WRAPPER"; m2 "공백 인자"; printf "%s" "$PWD"'],
                            cwd=tmp_path, env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert os.fsdecode(result.stdout) == str(target)


@pytest.mark.parametrize('shell', ['bash', 'zsh'])
def test_shell_failed_exit_keeps_directory(tmp_path, shell):
    executable = shutil.which(shell)
    if not executable:
        pytest.skip(f'{shell} not installed')
    binary = tmp_path / 'bin'
    binary.mkdir()
    script = binary / 'm2'
    script.write_text('#!/bin/sh\nexit 7\n')
    script.chmod(0o755)
    wrapper = Path(__file__).resolve().parents[1] / 'scripts/mom-shell.sh'
    env = {**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'], 'MOM_TEST_WRAPPER': str(wrapper)}
    result = subprocess.run([executable, '-c', 'source "$MOM_TEST_WRAPPER"; m2; code=$?; printf "%s:%s" "$code" "$PWD"'],
                            cwd=tmp_path, env=env, capture_output=True)
    assert result.returncode == 0
    assert os.fsdecode(result.stdout) == '7:' + str(tmp_path)
