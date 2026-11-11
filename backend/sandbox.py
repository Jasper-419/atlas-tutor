"""Credential-free subprocess boundary for Atlas's finite Python subset.

The AST interpreter, value limits and process limits jointly restrict execution.
This does not offer an OS sandbox and deliberately does not accept arbitrary Python.
"""
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time

LIMITS = {'source_bytes': 16000, 'ast_nodes': 2000, 'wall_seconds': 3, 'cpu_seconds': 2,
          'output_chars': 8192, 'collection_items': 10000, 'execution_steps': 100000,
          'integer_bits': 4096, 'value_depth': 32, 'aggregate_scalar_bytes': 65536, 'value_visits': 20000, 'rss_bytes': 134217728,
          'memory_model': 'bounded interpreter values + RSS checks; RLIMIT_AS/DATA on non-Darwin'}


def _failure(status, error):
    return {'status': status, 'stdout': '', 'error': error, 'checks': [], 'duration_ms': 0, 'limits': dict(LIMITS)}


async def _kill_group(process):
    # start_new_session gives this worker an independent process group. No shell.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


async def run_python(code, checks, *, wall_seconds=3):
    try:
        if not isinstance(code, str) or len(code.encode()) > LIMITS['source_bytes']:
            return _failure('rejected', 'Source exceeds 16000 bytes.')
        if not isinstance(checks, list) or not 1 <= len(checks) <= 12:
            return _failure('rejected', 'One to twelve explicit checks are required.')
        for check in checks:
            if not isinstance(check, dict) or set(check) != {'expression', 'expected'} or not isinstance(check['expression'], str) or not 1 <= len(check['expression']) <= 2000:
                return _failure('rejected', 'Each check requires expression and JSON expected value.')
        payload = json.dumps({'code': code, 'checks': checks}, allow_nan=False).encode()
        if len(payload) > 48000:
            return _failure('rejected', 'Execution request exceeds 48000 bytes.')
    except (TypeError, ValueError, RecursionError):
        return _failure('rejected', 'Checks must contain finite, bounded JSON values.')
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='atlas-python-') as workdir:
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-I', '-S', str(Path(__file__).with_name('sandbox_worker.py').resolve()),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=workdir, env={}, start_new_session=True,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(process.communicate(payload), timeout=min(3, max(.05, wall_seconds)))
        except asyncio.TimeoutError:
            await _kill_group(process)
            result = _failure('timeout', 'Execution wall-clock limit exceeded.')
        except asyncio.CancelledError:
            await _kill_group(process)
            raise
        else:
            if process.returncode != 0 or len(stdout) > 65536:
                result = _failure('resource_limit', 'Execution process stopped or exceeded result limits.')
            else:
                try:
                    result = json.loads(stdout)
                    if result.get('status') not in ('passed', 'failed', 'rejected', 'resource_limit'):
                        raise ValueError('Invalid worker result')
                except (ValueError, TypeError):
                    result = _failure('failed', 'Execution worker returned an invalid result.')
        result['duration_ms'] = round((time.monotonic() - started) * 1000)
        result['limits'] = dict(LIMITS)
        return result
