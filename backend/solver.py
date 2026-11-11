"""Per-turn solve plans and execution evidence; checkpoint is the durable authority."""
from copy import deepcopy
from hashlib import sha256
from uuid import uuid4

from backend.sandbox import run_python


class SolveError(ValueError):
    pass


def _text(value, label, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise SolveError(f'{label} must be nonempty and at most {limit} characters.')
    return value.strip()


def _state(checkpoint, turn_id):
    state = checkpoint.get('solve')
    if not state or state.get('turn_id') != turn_id:
        raise SolveError('Create a solve plan for the current turn first.')
    return state


def public_plan(state):
    steps = [{key: deepcopy(step[key]) for key in ('id', 'title', 'method', 'status', 'explanation') if key in step} for step in state['steps']]
    for public, private in zip(steps, state['steps']):
        if private['status'] == 'verified':
            evidence = next((item for item in state['executions'] if item['evidence_id'] == private.get('evidence_id')), None)
            if evidence:
                public['verification'] = {'evidence_id': evidence['evidence_id'], 'plan_version': evidence['plan_version'],
                                          'checks_passed': len(evidence['checks'])}
    counts = {name: sum(step['status'] == name for step in steps) for name in ('verified', 'reasoned')}
    counts['pending'] = len(steps) - counts['verified'] - counts['reasoned']
    return {'version': state['version'], 'goal': state['goal'], 'request': state['request'],
            'status': state['status'], 'steps': steps, 'counts': counts,
            **({'summary': state['summary']} if 'summary' in state else {})}


def public_execution(execution):
    return {key: deepcopy(execution[key]) for key in (
        'evidence_id', 'plan_version', 'step_id', 'status', 'stdout', 'error', 'checks', 'duration_ms', 'limits'
    ) if key in execution}


def plan(checkpoint, turn_id, request, goal, steps, reason=''):
    goal = _text(goal, 'goal')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 6:
        raise SolveError('A solve plan must have one to six steps.')
    validated, ids = [], set()
    for step in steps:
        if not isinstance(step, dict):
            raise SolveError('Each step must be an object.')
        identifier = _text(step.get('id'), 'step id', 80)
        if identifier in ids or step.get('method') not in ('python', 'reasoning'):
            raise SolveError('Step IDs must be unique; method must be python or reasoning.')
        ids.add(identifier)
        validated.append({'id': identifier, 'title': _text(step.get('title'), 'step title', 500),
                          'method': step['method'], 'status': 'pending'})
    previous = checkpoint.get('solve') or {}
    if previous.get('turn_id') == turn_id:
        reason = _text(reason, 'replanning reason', 2000)
    state = {'version': previous.get('version', 0) + 1, 'turn_id': turn_id,
             'request': request, 'request_hash': sha256(request.encode()).hexdigest(),
             'goal': goal, 'status': 'active', 'steps': validated, 'executions': [],
             'reason': str(reason)[:2000]}
    checkpoint['solve'] = state
    return {'kind': 'solve', 'action': 'plan', 'status': 'ok', 'plan': public_plan(state)}


def status(checkpoint, turn_id):
    state = _state(checkpoint, turn_id)
    return {'kind': 'solve', 'action': 'status', 'status': 'ok', 'plan': public_plan(state),
            'executions': [public_execution(item) for item in state['executions']]}


def _step(state, step_id):
    step = next((step for step in state['steps'] if step['id'] == step_id), None)
    if not step:
        raise SolveError('Step does not belong to this plan.')
    return step


async def check(checkpoint, turn_id, step_id, code, checks):
    state = _state(checkpoint, turn_id)
    if state['status'] != 'active':
        raise SolveError('This plan is complete. Replan before running another execution.')
    step = _step(state, step_id)
    if step['method'] != 'python':
        raise SolveError('Python evidence must belong to a python step.')
    if not isinstance(checks, list) or not 1 <= len(checks) <= 12:
        raise SolveError('At least one explicit check is required (maximum twelve).')
    if len(state['executions']) >= 24:
        raise SolveError('Execution attempt limit reached; create a new plan.')
    result = await run_python(code, checks)
    # Cancellation and replan cannot attach execution evidence to a different plan.
    if checkpoint.get('solve') is not state or state.get('turn_id') != turn_id:
        raise SolveError('The active plan changed while this execution was running.')
    execution = {'evidence_id': str(uuid4()), 'plan_version': state['version'],
                 'step_id': step_id, **result,
                 'request_hash': state['request_hash'],
                 'source_hash': sha256(code.encode()).hexdigest()}
    state['executions'].append(execution)
    # A later failed attempt invalidates the earlier completion for this step.
    step['status'] = 'pending'
    step.pop('explanation', None)
    step.pop('evidence_id', None)
    return {'kind': 'solve', 'action': 'python_check', 'status': 'ok',
            'execution': public_execution(execution), 'plan': public_plan(state)}


def finish_step(checkpoint, turn_id, step_id, explanation, evidence_id=None):
    state = _state(checkpoint, turn_id)
    if state['status'] != 'active':
        raise SolveError('This plan is complete.')
    step = _step(state, step_id)
    explanation = _text(explanation, 'explanation')
    if step['method'] == 'python':
        evidence = next((item for item in state['executions'] if item['evidence_id'] == evidence_id), None)
        latest = next((item for item in reversed(state['executions']) if item['step_id'] == step_id), None)
        if (not evidence or evidence is not latest or evidence.get('plan_version') != state['version']
                or evidence.get('step_id') != step_id or evidence.get('request_hash') != state['request_hash']
                or evidence.get('status') != 'passed' or not evidence.get('checks')
                or not all(check.get('passed') is True for check in evidence['checks'])):
            raise SolveError('A passing execution with actual checks from this plan and step is required; use its latest evidence_id.')
        step['status'], step['evidence_id'] = 'verified', evidence_id
    else:
        if evidence_id:
            raise SolveError('A reasoning step cannot claim Python execution evidence.')
        step['status'] = 'reasoned'
    step['explanation'] = explanation
    return {'kind': 'solve', 'action': 'finish_step', 'status': 'ok', 'plan': public_plan(state)}


def finish(checkpoint, turn_id, summary):
    state = _state(checkpoint, turn_id)
    summary = _text(summary, 'summary')
    if any(step['status'] not in ('verified', 'reasoned') for step in state['steps']):
        raise SolveError('Complete every step first; unverified Python steps cannot be presented as checked.')
    state['status'], state['summary'] = 'completed', summary
    return {'kind': 'solve', 'action': 'finish', 'status': 'ok', 'plan': public_plan(state),
            'summary': summary, 'verification': 'Python checks support verified steps; reasoned steps are explanatory and have not been executed.'}
