"""Offline prompt builder/scorer. No network calls or model-code execution.
Scoring uses a bounded AST interpreter, never eval/exec/subprocess.
"""

import ast, json, sys, hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from axl3 import *

SCHEMA = Schema(
    "coding.handoff.v1",
    (
        ("id", "string", True),
        ("task", "string", True),
        ("sender", "string", True),
        ("to", "string", True),
        ("kind", "string", True),
        ("seq", "integer", True),
        ("body", "object", True),
    ),
)
TASKS = [
    ("add", "Return x plus y.", "x+y"),
    ("max", "Return the greater of x and y.", "x if x>y else y"),
    ("min", "Return the lesser of x and y.", "x if x<y else y"),
    ("difference", "Return absolute difference between x and y.", "x-y if x>=y else y-x"),
    ("even", "Return whether x is even.", "x%2==0"),
    ("square", "Return square of x.", "x*x"),
    ("clamp", "Clamp x into the inclusive interval0to10.", "0 if x<0 else 10 if x>10 else x"),
    ("sign", "Return -1,0or1 according to sign of x.", "-1 if x<0 else 1 if x>0 else 0"),
    ("between", "Return whether0<=x<=y.", "0<=x<=y"),
    ("average", "Return floor integer average of x and y.", "(x+y)//2"),
    ("multiple", "Return whether x is divisible by nonzero y.", "x%y==0"),
    ("positive", "Return whether both inputs are positive.", "x>0 and y>0"),
]
CASES = [(x, y) for x in range(-12, 13) for y in (-7, -2, -1, 1, 2, 7)]


def expression(source, x, y):
    if type(source) is not str or len(source) > 1024:
        raise Error("Expression length/type")
    tree = ast.parse(source, mode="eval")
    nodes = list(ast.walk(tree))
    if len(nodes) > 128:
        raise Error("Expression node limit")
    # Validate every branch before evaluation, including unreachable branches.
    allowed = (
        ast.Expression,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.FloorDiv,
        ast.Mod,
        ast.UnaryOp,
        ast.USub,
        ast.UAdd,
        ast.Not,
        ast.IfExp,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.Compare,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
    )
    for node in nodes:
        if type(node) not in allowed:
            raise Error("Expression syntax not allowed")
        if isinstance(node, ast.Name) and node.id not in {"x", "y"}:
            raise Error("Unknown expression variable")
        if isinstance(node, ast.Constant) and (
            type(node.value) not in (int, bool) or abs(node.value) >= 100000
        ):
            raise Error("Invalid expression constant")

    def walk(n, depth=0):
        if depth > 24:
            raise Error("Expression depth")

        def run(v):
            return walk(v, depth + 1)

        if isinstance(n, ast.Expression):
            return run(n.body)
        if isinstance(n, ast.Constant) and type(n.value) in (int, bool) and abs(n.value) < 100000:
            return n.value
        if isinstance(n, ast.Name) and n.id in {"x", "y"}:
            return x if n.id == "x" else y
        if isinstance(n, ast.BinOp) and type(n.op) in (
            ast.Add,
            ast.Sub,
            ast.Mult,
            ast.FloorDiv,
            ast.Mod,
        ):
            a, b = run(n.left), run(n.right)
            if abs(a) > 1000000 or abs(b) > 1000000:
                raise Error("Arithmetic bound")
            if isinstance(n.op, ast.Add):
                r = a + b
            elif isinstance(n.op, ast.Sub):
                r = a - b
            elif isinstance(n.op, ast.Mult):
                r = a * b
            elif isinstance(n.op, ast.FloorDiv):
                r = a // b
            else:
                r = a % b
            if abs(r) > 1000000:
                raise Error("Arithmetic result bound")
            return r
        if isinstance(n, ast.UnaryOp) and type(n.op) in (ast.USub, ast.UAdd, ast.Not):
            v = run(n.operand)
            return -v if isinstance(n.op, ast.USub) else +v if isinstance(n.op, ast.UAdd) else not v
        if isinstance(n, ast.IfExp):
            return run(n.body) if run(n.test) else run(n.orelse)
        if isinstance(n, ast.BoolOp) and type(n.op) in (ast.And, ast.Or):
            value = run(n.values[0])
            for operand in n.values[1:]:
                if isinstance(n.op, ast.And) and not value:
                    return value
                if isinstance(n.op, ast.Or) and value:
                    return value
                value = run(operand)
            return value
        if isinstance(n, ast.Compare):
            a = run(n.left)
            for op, v in zip(n.ops, n.comparators):
                b = run(v)
                if isinstance(op, ast.Eq):
                    ok = a == b
                elif isinstance(op, ast.NotEq):
                    ok = a != b
                elif isinstance(op, ast.Lt):
                    ok = a < b
                elif isinstance(op, ast.LtE):
                    ok = a <= b
                elif isinstance(op, ast.Gt):
                    ok = a > b
                elif isinstance(op, ast.GtE):
                    ok = a >= b
                else:
                    raise Error("Unsupported comparison")
                if not ok:
                    return False
                a = b
            return True
        raise Error("Expression syntax not allowed")

    return walk(tree)


def expected(task, expr):
    return {
        "id": "result-" + task,
        "task": task,
        "sender": "worker",
        "to": "manager",
        "kind": "result",
        "seq": 0,
        "body": {"expression": expr},
    }


def prompts():
    output = []
    for task, description, _ in TASKS:
        base = (
            "Complete this coding handoff. "
            + description
            + ' Inputs x,y are integers; y is nonzero. Return one JSON-compatible record, body={"expression":Python expression}. Use only x,y,integer/boolean constants,+,-,*,//,%,comparisons,conditional expressions,and/or/not. No calls, imports,attributes or loops. Metadata: '
            + dump({k: v for k, v in expected(task, "").items() if k != "body"})
            + "\nSchema: "
            + dump(SCHEMA.definition)
            + "\n"
        )
        for mode in ("contract_json", "v3", "equivalent_packed_json"):
            if mode == "contract_json":
                fmt = "Return a JSON array containing one record object matching this schema. No prose.\n"
            else:
                fmt = (
                    'Return [3,"'
                    + SCHEMA.fingerprint
                    + '",{},[row]], where row contains values in schema field order. No prose.\n'
                )
            prompt = base + fmt
            output.append(
                {
                    "id": task + ":" + mode,
                    "task": task,
                    "mode": mode,
                    "prompt": prompt,
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                }
            )
    return output


def score(item):
    task = item["task"]
    mode = item["mode"]
    text = item["text"]
    result = {
        "task": task,
        "mode": mode,
        "syntax": False,
        "metadata": False,
        "success": False,
        "passed_cases": 0,
    }
    try:
        records = load(text) if mode == "contract_json" else unpack(text, registry(SCHEMA))
        if type(records) is not list or len(records) != 1:
            raise Error("Expected one record")
        record = records[0]
        SCHEMA.check(record)
        result["syntax"] = True
        expr = record["body"]["expression"]
        if record != expected(task, expr):
            raise Error("Metadata/body mismatch")
        result["metadata"] = True
        oracle = next(e for t, _, e in TASKS if t == task)
        for x, y in CASES:
            actual = expression(expr, x, y)
            target = expression(oracle, x, y)
            if type(actual) is type(target) and actual == target:
                result["passed_cases"] += 1
        result["success"] = result["passed_cases"] == len(CASES)
    except (
        Error,
        ValueError,
        KeyError,
        TypeError,
        SyntaxError,
        StopIteration,
        ZeroDivisionError,
        RecursionError,
    ) as e:
        result["error"] = str(e)
    return result


if __name__ == "__main__":
    if len(sys.argv) == 1:
        for p in prompts():
            print(json.dumps(p))
    else:
        for line in Path(sys.argv[1]).read_text().splitlines():
            print(json.dumps(score(json.loads(line))))
