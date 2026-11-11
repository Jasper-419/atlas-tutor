"""Shared-loop adapters for the per-turn verified solver; no database writes."""
from backend import solver


def _invoke(inv, action, function, **args):
    try:
        return function(inv.context.checkpoint, inv.turn.id, **args)
    except solver.SolveError as exc:
        return {'kind': 'solve', 'action': action, 'status': 'error', 'error': str(exc)}


async def solve_plan(inv):
    return _invoke(inv, 'plan', solver.plan, request=inv.turn.input, **inv.args)


async def solve_status(inv):
    return _invoke(inv, 'status', solver.status)


async def python_check(inv):
    try:
        return await solver.check(inv.context.checkpoint, inv.turn.id, **inv.args)
    except solver.SolveError as exc:
        return {'kind': 'solve', 'action': 'python_check', 'status': 'error', 'error': str(exc)}


async def solve_finish_step(inv):
    return _invoke(inv, 'finish_step', solver.finish_step, **inv.args)


async def solve_finish(inv):
    return _invoke(inv, 'finish', solver.finish, **inv.args)
