"""Run the privileged installer against isolated paths and simulated Linux commands."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / 'tools/host/install-analysis-linux.sh'


def executable(path, body):
    path.write_text(body)
    path.chmod(0o755)


def run_installer(tmp_path, *, sensor=False, fail_chat=False, options=(), running=False):
    root = tmp_path / 'root'
    binary = tmp_path / 'bin'
    payload = tmp_path / 'payload'
    binary.mkdir()
    payload.mkdir()
    for directory in ('run/systemd/system', 'etc/systemd/system', 'sys/class/hwmon', 'opt'):
        (root / directory).mkdir(parents=True, exist_ok=True)
    if sensor:
        chip = root / 'sys/class/hwmon/hwmon0'
        chip.mkdir()
        (chip / 'name').write_text('coretemp')
        (chip / 'temp1_input').write_text('55000')
    script = tmp_path / 'installer.sh'
    text = INSTALLER.read_text()
    # Force fresh installs without allowing command lookup to find the real
    # host's Ollama/Tailscale. All executable calls must use the simulated bin.
    for tool in ('tailscale', 'ollama'):
        text = text.replace(f'command -v {tool} >/dev/null 2>&1', f'[[ -x {binary}/{tool} ]]')
        text = text.replace(f'\n{tool} ', f'\n"{binary}/{tool}" ')
        text = text.replace(f'    {tool} ', f'    "{binary}/{tool}" ')
        text = text.replace(f'$( {tool} ', f'$( "{binary}/{tool}" ')
        text = text.replace(f'$({tool} ', f'$("{binary}/{tool}" ')
    for directory in ('/etc/', '/opt/', '/run/', '/sys/'):
        text = text.replace(directory, str(root) + directory)
    script.write_text(text)
    log = tmp_path / 'commands.log'
    executable(binary / 'id', '#!/bin/sh\necho 0\n')
    executable(binary / 'uname', '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo x86_64;; esac\n')
    for name in ('apt-get', 'systemctl'):
        executable(binary / name, '#!/bin/sh\nprintf "%s\\n" "' + name + ' $*" >> "$COMMAND_LOG"\n')
    # Use the actual Python interpreter, without installing packages on the host.
    (binary / 'python3').symlink_to(shutil.which('python3'))
    executable(payload / 'ollama', '''#!/bin/sh
printf '%s\n' "ollama $*" >> "$COMMAND_LOG"
''')
    executable(payload / 'tailscale', '''#!/bin/sh
printf '%s\n' "tailscale $*" >> "$COMMAND_LOG"
case "$1" in
  status) printf '{"BackendState":"%s"}\n' "${TS_STATE:-NeedsLogin}" ;;
  ip) echo 100.114.220.83 ;;
esac
''')
    executable(binary / 'curl', '''#!/usr/bin/env python3
import json, os, shlex, sys
from pathlib import Path
args = sys.argv[1:]
url = next(a for a in args if a.startswith('http'))
out = Path(args[args.index('-o') + 1]) if '-o' in args else None
with open(os.environ['COMMAND_LOG'], 'a') as log:
    log.write('curl ' + url + '\\n')
if url.endswith('install.sh'):
    name = 'tailscale' if 'tailscale.com' in url else 'ollama'
    src = Path(os.environ['PAYLOAD']) / name
    dest = Path(os.environ['MOCK_BIN']) / name
    out.write_text('#!/bin/sh\\ncp ' + shlex.quote(str(src)) + ' ' + shlex.quote(str(dest)) + '\\n')
    raise SystemExit
if url.endswith('/api/tags'):
    value = {'models': [{'name':'qwen3.5:4b'}, {'name':'leoipulsar/harrier-0.6b:latest'}]}
elif url.endswith('/api/embed'):
    value = {'embeddings': [[1.0] * 1024]}
else:
    value = {'done': True, 'message': {'content': '{"ok":false}' if os.environ.get('FAIL_CHAT') else '{"ok":true}'}}
raw = json.dumps(value)
if out:
    out.write_text(raw)
else:
    print(raw)
''')
    env = {**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'],
           'COMMAND_LOG': str(log), 'PAYLOAD': str(payload), 'MOCK_BIN': str(binary)}
    if fail_chat:
        env['FAIL_CHAT'] = '1'
    if running:
        env['TS_STATE'] = 'Running'
    result = subprocess.run(['bash', str(script), *options], env=env, capture_output=True, text=True, timeout=20, check=False)
    return result, root, log.read_text()


@pytest.mark.parametrize('sensor,port', [(False, 11434), (True, 11435)])
def test_installer_downloads_configures_checks_and_starts_worker(tmp_path, sensor, port):
    result, root, commands = run_installer(tmp_path, sensor=sensor)
    assert result.returncode == 0, result.stderr
    assert 'https://tailscale.com/install.sh' in commands and 'https://ollama.com/install.sh' in commands
    assert 'ollama pull qwen3.5:4b' in commands and 'ollama pull leoipulsar/harrier-0.6b' in commands
    assert f'tailscale serve --bg --yes --tcp=11434 tcp://localhost:{port}' in commands
    assert f'curl http://127.0.0.1:{port}/api/embed' in commands and f'curl http://127.0.0.1:{port}/api/chat' in commands
    assert 'Installation terminée' in result.stdout and 'http://100.114.220.83:11434' in result.stdout
    config = (root / 'etc/systemd/system/ollama.service.d/dindon-worker.conf').read_text()
    assert 'OLLAMA_HOST=127.0.0.1:11434' in config and 'OLLAMA_NUM_PARALLEL=1' in config and 'OLLAMA_MAX_LOADED_MODELS=1' in config
    relay = (root / 'opt/dindon-worker/ollama_thermal_proxy.py').read_text()
    assert relay.replace(str(root), '') == (ROOT / 'tools/host/ollama_thermal_proxy.py').read_text()
    if sensor:
        assert 'systemctl enable dindon-thermal' in commands
        assert (root / 'etc/systemd/system/dindon-thermal.service').is_file()
    else:
        assert 'Protection thermique : indisponible' in result.stdout


def test_installer_refuses_required_thermal_protection_without_sensors(tmp_path):
    result, _, commands = run_installer(tmp_path, options=('--require-thermal',))
    assert result.returncode != 0 and 'Aucun capteur CPU reconnu' in result.stderr
    assert 'tailscale serve --yes --tcp=11434 off' in commands
    assert 'tailscale serve --bg' not in commands and 'Installation terminée' not in result.stdout


def test_installer_does_not_report_ready_when_inference_fails(tmp_path):
    result, _, _ = run_installer(tmp_path, fail_chat=True)
    assert result.returncode != 0 and 'vérification JSON' in result.stderr
    assert 'Installation terminée' not in result.stdout


def test_rerun_keeps_existing_tailscale_connection(tmp_path):
    result, _, commands = run_installer(tmp_path, running=True)
    assert result.returncode == 0, result.stderr
    assert 'tailscale up' not in commands
