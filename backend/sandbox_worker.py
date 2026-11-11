"""Atlas finite Python subset interpreter, launched in a credential-free process.

This is a language boundary, not an OS sandbox. No user source reaches exec/eval,
imports, attribute lookup, arbitrary callables, filesystem or network APIs.
"""
import ast
import json
import math
import operator
import resource
import sys

MAX_ITEMS = 10000
MAX_VISITS = 20000
MAX_STEPS = 100000
MAX_OUTPUT = 8192
MAX_BITS = 4096


class Rejected(ValueError):
    pass


class Limit(ValueError):
    pass


class BreakLoop(Exception):
    pass


class ContinueLoop(Exception):
    pass


BUILTINS = {
    'abs': abs, 'all': all, 'any': any, 'bool': bool, 'dict': dict,
    'divmod': divmod, 'enumerate': enumerate, 'float': float, 'int': int,
    'len': len, 'list': list, 'max': max, 'min': min, 'pow': pow,
    'range': range, 'reversed': reversed, 'round': round, 'set': set,
    'sorted': sorted, 'str': str, 'sum': sum, 'tuple': tuple, 'zip': zip,
}
BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
          ast.Mod: operator.mod, ast.Pow: operator.pow}
CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
       ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
       ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
       ast.Is: operator.is_, ast.IsNot: operator.is_not}
ALLOWED = (
    ast.Module, ast.Expression, ast.Assign, ast.AugAssign, ast.Expr, ast.If,
    ast.While, ast.For, ast.Break, ast.Continue, ast.Pass, ast.Name,
    ast.Load, ast.Store, ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set,
    ast.Subscript, ast.Slice, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
    ast.IfExp, ast.Call, ast.keyword, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.FloorDiv, ast.Mod, ast.Pow, ast.UAdd, ast.USub, ast.Not,
    ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.In, ast.NotIn, ast.Is, ast.IsNot,
)


def parse(source, mode='exec'):
    if not isinstance(source, str) or len(source.encode()) > 16000:
        raise Rejected('Source exceeds 16000 bytes.')
    try:
        tree = ast.parse(source, mode=mode)
    except (SyntaxError, RecursionError, ValueError) as exc:
        raise Rejected('Invalid Python syntax.') from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 2000:
        raise Rejected('AST exceeds 2000 nodes.')
    for node in nodes:
        if not isinstance(node, ALLOWED):
            raise Rejected(f'{type(node).__name__} is outside the allowed Python subset.')
        if isinstance(node, ast.Name) and (node.id.startswith('_') or '__' in node.id):
            raise Rejected('Private/dunder names are forbidden.')
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in {*BUILTINS, 'print'}:
                raise Rejected('Only direct calls to documented safe builtins are allowed.')
            if any(keyword.arg is None for keyword in node.keywords):
                raise Rejected('Keyword expansion is forbidden.')
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name) and name.id in {*BUILTINS, 'print'}:
                        raise Rejected('Safe builtin names cannot be assigned.')
        if isinstance(node, ast.Constant) and type(node.value) not in (str, int, float, bool, type(None)):
            raise Rejected('Unsupported literal.')
    return tree


def guard(value):
    budget = MAX_VISITS
    scalar_bytes = 65536
    def check(item, depth=0):
        nonlocal budget, scalar_bytes
        budget -= 1
        if budget < 0 or depth > 32:
            raise Limit('Value nesting/size limit exceeded.')
        if type(item) in (str, int, float, bool):
            scalar_bytes -= len(item) if type(item) is str else max(8, item.bit_length() // 3) if type(item) is int else 24
            if scalar_bytes < 0:
                raise Limit('Aggregate value size limit exceeded.')
        if type(item) is int and item.bit_length() > MAX_BITS:
            raise Limit('Integer size limit exceeded.')
        if type(item) is float and not math.isfinite(item):
            raise Limit('Non-finite floating-point result.')
        if type(item) is str and len(item) > MAX_OUTPUT:
            raise Limit('String size limit exceeded.')
        if type(item) in (list, tuple, set, dict, range):
            if len(item) > MAX_ITEMS:
                raise Limit('Collection size limit exceeded.')
            if type(item) is dict:
                for key, val in item.items():
                    check(key, depth + 1)
                    check(val, depth + 1)
            elif type(item) is not range:
                for val in item:
                    check(val, depth + 1)
        elif type(item) not in (int, float, bool, str, type(None)):
            raise Rejected('Unsupported runtime value.')
    check(value)
    return value


class Interpreter:
    def __init__(self):
        self.env = {}
        self.output = ''
        self.steps = 0

    def tick(self):
        self.steps += 1
        if self.steps % 256 == 0:
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if rss > (128 * 1024 * 1024 if sys.platform == 'darwin' else 128 * 1024):
                raise Limit('Worker memory limit exceeded.')
        if self.steps > MAX_STEPS:
            raise Limit('Execution step limit exceeded.')

    def binary(self, op, left, right):
        if isinstance(op, ast.Mult):
            seq, count = (left, right) if type(right) is int else (right, left)
            if type(seq) in (str, list, tuple) and type(count) is int:
                if len(seq) * max(0, count) > (MAX_OUTPUT if type(seq) is str else MAX_ITEMS):
                    raise Limit('Repeated sequence size limit exceeded.')
        if isinstance(op, ast.Pow):
            if abs(right) > MAX_BITS or (type(left) is int and type(right) is int and right > 0 and left.bit_length() * right > MAX_BITS):
                raise Limit('Exponent size limit exceeded.')
        # String interpolation can allocate enormous strings via width specifiers.
        if isinstance(op, ast.Mod) and isinstance(left, str):
            raise Rejected('String formatting is outside the allowed subset.')
        return guard(BINOPS[type(op)](left, right))

    def expr(self, node):
        self.tick()
        if isinstance(node, ast.Constant):
            value = node.value
        elif isinstance(node, ast.Name):
            if node.id not in self.env:
                raise NameError(f'Undefined variable: {node.id}')
            value = self.env[node.id]
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            values = [self.expr(item) for item in node.elts]
            value = values if isinstance(node, ast.List) else tuple(values) if isinstance(node, ast.Tuple) else set(values)
        elif isinstance(node, ast.Dict):
            if any(key is None for key in node.keys):
                raise Rejected('Dictionary expansion is forbidden.')
            value = {self.expr(k): self.expr(v) for k, v in zip(node.keys, node.values)}
        elif isinstance(node, ast.BinOp):
            value = self.binary(node.op, self.expr(node.left), self.expr(node.right))
        elif isinstance(node, ast.UnaryOp):
            value = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}[type(node.op)](self.expr(node.operand))
        elif isinstance(node, ast.BoolOp):
            value = self.expr(node.values[0])
            for operand in node.values[1:]:
                if (isinstance(node.op, ast.And) and not value) or (isinstance(node.op, ast.Or) and value):
                    break
                value = self.expr(operand)
        elif isinstance(node, ast.Compare):
            value, left = True, self.expr(node.left)
            for op, right_node in zip(node.ops, node.comparators):
                right = self.expr(right_node)
                if not CMP[type(op)](left, right):
                    value = False
                    break
                left = right
        elif isinstance(node, ast.IfExp):
            value = self.expr(node.body if self.expr(node.test) else node.orelse)
        elif isinstance(node, ast.Subscript):
            value = self.expr(node.value)[self.index(node.slice)]
        elif isinstance(node, ast.Call):
            args = [self.expr(arg) for arg in node.args]
            kwargs = {keyword.arg: self.expr(keyword.value) for keyword in node.keywords}
            guard(args)
            guard(kwargs)
            name = node.func.id
            if name == 'print':
                if set(kwargs) - {'sep', 'end'} or any(type(v) is not str for v in kwargs.values()):
                    raise Rejected('print accepts only string sep/end keywords.')
                output = kwargs.get('sep', ' ').join(str(arg) for arg in args) + kwargs.get('end', '\n')
                if len(self.output) + len(output) > MAX_OUTPUT:
                    raise Limit('Output limit exceeded.')
                self.output += output
                return None
            if name == 'pow':
                if len(args) not in (2, 3) or kwargs:
                    raise Rejected('pow requires two or three positional arguments.')
                if len(args) == 2:
                    return self.binary(ast.Pow(), *args)
                if abs(args[1]) > MAX_BITS:
                    raise Limit('Exponent size limit exceeded.')
            value = BUILTINS[name](*args, **kwargs)
            if name in ('enumerate', 'zip', 'reversed'):
                value = list(value)
        else:
            raise Rejected('Unsupported expression.')
        return guard(value)

    def index(self, node):
        if isinstance(node, ast.Slice):
            return slice(*(self.expr(v) if v is not None else None for v in (node.lower, node.upper, node.step)))
        return self.expr(node)

    def assign(self, target, value):
        guard(value)
        if isinstance(target, ast.Name):
            self.env[target.id] = value
            guard(self.env)
        elif isinstance(target, (ast.List, ast.Tuple)):
            if len(target.elts) != len(value):
                raise ValueError('Unpacking length mismatch.')
            for item, val in zip(target.elts, value):
                self.assign(item, val)
        elif isinstance(target, ast.Subscript):
            container = self.expr(target.value)
            container[self.index(target.slice)] = value
            guard(container)
        else:
            raise Rejected('Unsupported assignment target.')

    def block(self, nodes):
        for node in nodes:
            self.tick()
            if isinstance(node, ast.Assign):
                value = self.expr(node.value)
                for target in node.targets:
                    self.assign(target, value)
            elif isinstance(node, ast.AugAssign):
                self.assign(node.target, self.binary(node.op, self.expr(node.target), self.expr(node.value)))
            elif isinstance(node, ast.Expr):
                self.expr(node.value)
            elif isinstance(node, ast.If):
                self.block(node.body if self.expr(node.test) else node.orelse)
            elif isinstance(node, (ast.While, ast.For)):
                iterator = iter(self.expr(node.iter)) if isinstance(node, ast.For) else None
                broken = False
                while True:
                    self.tick()
                    if iterator is None:
                        if not self.expr(node.test):
                            break
                    else:
                        try:
                            value = next(iterator)
                        except StopIteration:
                            break
                        self.assign(node.target, value)
                    try:
                        self.block(node.body)
                    except ContinueLoop:
                        continue
                    except BreakLoop:
                        broken = True
                        break
                if not broken:
                    self.block(node.orelse)
            elif isinstance(node, ast.Break):
                raise BreakLoop()
            elif isinstance(node, ast.Continue):
                raise ContinueLoop()
            elif not isinstance(node, ast.Pass):
                raise Rejected('Unsupported statement.')


def json_equal(actual, expected):
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, list) or isinstance(expected, list):
        return (type(actual) is type(expected) and len(actual) == len(expected)
                and all(json_equal(a, b) for a, b in zip(actual, expected)))
    if isinstance(actual, dict) or isinstance(expected, dict):
        return (type(actual) is type(expected) and actual.keys() == expected.keys()
                and all(json_equal(actual[key], expected[key]) for key in actual))
    return actual == expected


def run(payload):
    interpreter = Interpreter()
    results = []
    try:
        program = parse(payload['code'])
        checks = payload['checks']
        expressions = [parse(item['expression'], mode='eval') for item in checks]
        # Check expressions are read-only: no print effects disguised as assertions.
        if any(isinstance(node, ast.Call) and node.func.id == 'print' for expr in expressions for node in ast.walk(expr)):
            raise Rejected('print is not allowed in check expressions.')
        interpreter.block(program.body)
        for check, expression in zip(checks, expressions):
            actual = interpreter.expr(expression.body)
            # Convert only JSON-safe data; finite/nesting bounds already enforced.
            actual = json.loads(json.dumps(actual, allow_nan=False))
            expected = check['expected']
            passed = json_equal(actual, expected)
            results.append({'expression': check['expression'], 'expected': expected, 'actual': actual, 'passed': passed})
        status, error = ('passed' if checks and all(item['passed'] for item in results) else 'failed'), None
    except Rejected as exc:
        status, error = 'rejected', str(exc)
    except (Limit, MemoryError, RecursionError, OverflowError) as exc:
        status, error = 'resource_limit', str(exc) or 'Execution resource limit exceeded.'
    except Exception as exc:
        status, error = 'failed', f'{type(exc).__name__}: {str(exc)[:500]}'
    return {'status': status, 'stdout': interpreter.output, 'error': error, 'checks': results}


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    # Darwin RLIMIT_AS is unreliable. The interpreter also bounds values/steps.
    if sys.platform != 'darwin':
        resource.setrlimit(resource.RLIMIT_AS, (192 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_DATA, (128 * 1024 * 1024,) * 2)
    payload = json.loads(sys.stdin.buffer.read(65537))
    result = run(payload)
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > 65536:
        encoded = json.dumps({'status': 'resource_limit', 'stdout': result['stdout'], 'error': 'Result size limit exceeded.', 'checks': []})
    sys.stdout.write(encoded)


if __name__ == '__main__':
    main()
