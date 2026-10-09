"""Local temperature readings and actual relay interruption; no real hardware involved."""
import importlib.util
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError

import pytest

spec = importlib.util.spec_from_file_location('thermal_proxy', Path(__file__).parents[1] / 'tools/host/ollama_thermal_proxy.py')
thermal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(thermal)


def test_guard_uses_cpu_critical_margin_and_requires_cooling(tmp_path):
    chip = tmp_path / 'hwmon0'
    chip.mkdir()
    (chip / 'name').write_text('coretemp')
    sensor = chip / 'temp1_input'
    sensor.write_text('60000')
    (chip / 'temp1_crit').write_text('85000')
    readings = thermal.sensors(tmp_path, 85)
    assert readings[0].ceiling == 80
    guard = thermal.Guard(readings, 75)
    assert not guard.blocked.is_set()
    sensor.write_text('80000')
    guard.refresh()
    assert guard.blocked.is_set()
    sensor.write_text('74000')
    guard.refresh()
    assert guard.blocked.is_set()  # ten-degree hysteresis below the effective ceiling
    sensor.write_text('70000')
    guard.refresh()
    assert not guard.blocked.is_set()
    sensor.unlink()
    guard.refresh()
    assert guard.blocked.is_set() and 'indisponible' in guard.reason


def test_no_reading_never_claims_temperature_is_safe(tmp_path):
    assert thermal.sensors(tmp_path, 85) == []
    assert thermal.Guard([], 75).blocked.is_set()


def test_heat_interrupts_running_inference_and_cooling_restores_tags(tmp_path):
    sensor = tmp_path / 'input'
    sensor.write_text('60000')
    guard = thermal.Guard([thermal.Sensor(sensor, 85)], 75)
    entered, disconnected = threading.Event(), threading.Event()

    class Upstream(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/api/tags':
                raw = b'{"models":[]}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            self.send_response(200)
            self.send_header('Content-Length', '100000')
            self.end_headers()
            entered.set()
            try:
                for _ in range(100):
                    self.wfile.write(b' ' * 1000)
                    self.wfile.flush()
                    time.sleep(0.02)
            except (BrokenPipeError, ConnectionResetError):
                disconnected.set()

        do_POST = do_GET

        def log_message(self, *_args):
            pass

    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    relay = thermal.ThermalServer(('127.0.0.1', 0), guard, upstream.server_port)
    for server in (upstream, relay):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{relay.server_port}'
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            task = executor.submit(urlopen, url + '/api/chat', b'{}', timeout=3)
            assert entered.wait(1)
            sensor.write_text('90000')
            guard.refresh()
            with pytest.raises(HTTPError) as error:
                task.result(timeout=2)
            assert error.value.code == 503
            assert 'température' in json.loads(error.value.read())['error']
            assert disconnected.wait(1)
        with pytest.raises(HTTPError) as error:
            urlopen(url + '/api/tags', timeout=1)
        assert error.value.code == 503
        sensor.write_text('70000')
        guard.refresh()
        with urlopen(url + '/api/tags', timeout=1) as response:
            assert json.load(response) == {'models': []}
    finally:
        for server in (relay, upstream):
            server.shutdown()
            server.server_close()
