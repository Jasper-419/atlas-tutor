"""Focused restricted-Python and solve-evidence contract checks; no model/network calls."""
import asyncio
import os
from unittest.mock import patch
from types import SimpleNamespace


async def main():
    # Removing the AST gate or execution/evidence binding must fail these checks.
    from backend.sandbox import run_python
    from backend.tutor.handlers import solver

    for source in ('import os', 'x = (1).__class__', 'open("/tmp/atlas-escape", "w")', 'eval("1")', 'x = globals()', 'f = print\nf("alias")'):
        result = await run_python(source, [{"expression": "True", "expected": True}])
        assert result['status'] == 'rejected', (source, result)
    good = await run_python('x = sum(range(11))\nprint(x)', [{"expression": "x", "expected": 55}])
    assert good['status'] == 'passed' and good['stdout'].strip() == '55', good
    typed = await run_python('x = 0', [{"expression": "x", "expected": False}])
    assert typed['status'] == 'failed', typed
    bad = await run_python('x = 2 + 2', [{"expression": "x", "expected": 5}])
    assert bad['status'] == 'failed' and not bad['checks'][0]['passed'], bad
    loop = await run_python('while True:\n    pass', [{"expression": "True", "expected": True}], wall_seconds=.3)
    assert loop['status'] in ('timeout', 'resource_limit'), loop
    flood = await run_python('for i in range(10000):\n    print("x" * 100)', [{"expression": "True", "expected": True}])
    assert flood['status'] == 'resource_limit' and len(flood['stdout']) <= 8192, flood
    memory = await run_python('x = [0] * 1000000000', [{"expression": "True", "expected": True}])
    assert memory['status'] == 'resource_limit', memory

    # Observe a real spawned process, then ensure cancellation kills and reaps it.
    import backend.sandbox as sandbox
    spawn = asyncio.create_subprocess_exec
    launched = asyncio.Event()
    children = []
    async def capture(*args, **kwargs):
        child = await spawn(*args, **kwargs)
        children.append(child)
        assert kwargs['env'] == {} and kwargs['start_new_session'] is True
        launched.set()
        return child
    with patch.object(sandbox.asyncio, 'create_subprocess_exec', capture):
        task = asyncio.create_task(run_python('while True:\n    x = sorted(range(1000))', [{"expression": "True", "expected": True}]))
        await launched.wait()
        await asyncio.sleep(.02)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('Cancellation must propagate')
    assert children[0].returncode is not None
    try:
        os.kill(children[0].pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError('Cancelled worker is still alive')
    timeout = await run_python('while True:\n    x = sorted(range(1000))', [{"expression": "True", "expected": True}], wall_seconds=.05)
    assert timeout['status'] == 'timeout', timeout
    language = await run_python('x=0\nfor i in range(5):\n    if i == 3:\n        break\n    x += i', [{"expression": "x", "expected": 3}])
    assert language['status'] == 'passed', language

    cp = {}
    inv = SimpleNamespace(context=SimpleNamespace(checkpoint=cp), turn=SimpleNamespace(id='turn-1', input='计算1到10的和并说明方法'), args={})
    async def call(handler, **args):
        inv.args = args
        return await handler(inv)
    plan_args = dict(goal='计算求和', steps=[dict(id='calc', title='计算求和', method='python'), dict(id='explain', title='说明', method='reasoning')])
    plan = await call(solver.solve_plan, **plan_args)
    assert plan['plan']['version'] == 1 and len(plan['plan']['steps']) == 2
    assert cp['solve']['request'] == inv.turn.input
    empty = await call(solver.python_check, step_id='calc', code='x=55', checks=[])
    assert empty['status'] == 'error', empty
    failed = await call(solver.python_check, step_id='calc', code='x=54', checks=[dict(expression='x', expected=55)])
    failure_id = failed['execution']['evidence_id']
    deny = await call(solver.solve_finish_step, step_id='calc', explanation='算完了', evidence_id=failure_id)
    assert deny['status'] == 'error', deny
    fixed = await call(solver.python_check, step_id='calc', code='x=sum(range(11))', checks=[dict(expression='x', expected=55)])
    evidence = fixed['execution']['evidence_id']
    assert (await call(solver.solve_finish_step, step_id='explain', explanation='说明', evidence_id=evidence))['status'] == 'error'
    assert (await call(solver.solve_finish, summary='55'))['status'] == 'error'
    done = await call(solver.solve_finish_step, step_id='calc', explanation='真实计算得到55', evidence_id=evidence)
    assert done['plan']['steps'][0]['status'] == 'verified', done
    await call(solver.solve_finish_step, step_id='explain', explanation='按等差数列解释')
    done = await call(solver.solve_finish, summary='总和55；计算已检查，解释为推理。')
    assert done['plan']['steps'][0]['verification']['checks_passed'] == 1
    assert 'request_hash' not in str(done) and 'source_hash' not in str(done)
    assert done['plan']['counts'] == {'verified': 1, 'reasoned': 1, 'pending': 0}, done
    assert (await call(solver.solve_plan, **plan_args))['status'] == 'error'
    assert cp['solve']['version'] == 1
    await call(solver.solve_plan, **plan_args, reason='重新独立计算')
    assert cp['solve']['version'] == 2 and cp['solve']['executions'] == []
    assert (await call(solver.solve_finish_step, step_id='calc', explanation='复用旧结果', evidence_id=evidence))['status'] == 'error'
    inv.turn.id = 'turn-2'
    assert (await call(solver.solve_status))['status'] == 'error'
    print('solver smoke: passed (AST, real subprocess, failures, bounds, plan/evidence/replan)')


if __name__ == '__main__':
    asyncio.run(main())
