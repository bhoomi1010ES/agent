"""AST-based enforcement test for Rule 1 (production-engineering-rules.md).

Verifies that all backend functions wrap their bodies in try/except or @log_errors,
do not catch bare except:, and never silently swallow exceptions.
"""

import ast
from pathlib import Path


def is_trivial_or_special(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Detect trivial one-line property getters, dunder methods, or abstract stubs."""
    # Special methods like __init__, __repr__, __str__
    if node.name.startswith("__") and node.name.endswith("__"):
        return True

    # Pydantic field validators and classmethods often have standard bodies
    decorator_names = [
        d.id if isinstance(d, ast.Name) else (d.attr if isinstance(d, ast.Attribute) else "")
        for d in node.decorator_list
    ]
    if "property" in decorator_names:
        return True

    # Abstract or protocol stub with docstring + pass/ellipsis
    body_statements = [
        s for s in node.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
    ]
    if len(body_statements) == 1:
        single = body_statements[0]
        if isinstance(single, ast.Pass) or (
            isinstance(single, ast.Expr)
            and isinstance(single.value, ast.Constant)
            and single.value.value is ...
        ):
            return True

    return False


def has_log_errors_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check if function is decorated with @log_errors."""
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "log_errors":
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == "log_errors":
            return True
    return False


def validate_function_ast(node: ast.FunctionDef | ast.AsyncFunctionDef, filename: str) -> list[str]:
    """Validate a single function AST against Rule 1."""
    errors: list[str] = []

    if is_trivial_or_special(node):
        return errors

    if has_log_errors_decorator(node):
        return errors

    # Function must have a try/except wrapping its main body
    body_statements = [
        s for s in node.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
    ]
    if not body_statements:
        return errors

    has_try = any(isinstance(s, ast.Try) for s in body_statements)
    if not has_try:
        errors.append(
            f"{filename}:{node.lineno} - Function '{node.name}' lacks a try/except block or @log_errors decorator."
        )
        return errors

    # Check try statements inside the function
    for stmt in body_statements:
        if isinstance(stmt, ast.Try):
            for handler in stmt.handlers:
                # Disallow bare except:
                if handler.type is None:
                    errors.append(
                        f"{filename}:{handler.lineno} - Function '{node.name}' contains bare 'except:'."
                    )
                # Disallow silent swallowing (except: pass)
                handler_statements = [
                    s
                    for s in handler.body
                    if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                ]
                if len(handler_statements) == 1 and isinstance(handler_statements[0], ast.Pass):
                    errors.append(
                        f"{filename}:{handler.lineno} - Function '{node.name}' swallows exception with bare 'pass'."
                    )

    return errors


def test_codebase_complies_with_rule_1() -> None:
    """Scan all production package modules and verify Rule 1 compliance."""
    backend_dir = Path(__file__).resolve().parents[2]
    package_dir = backend_dir / "modernization_platform"
    assert package_dir.is_dir(), f"Production package directory {package_dir} not found"

    all_errors = []
    for py_file in package_dir.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue

        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                errors = validate_function_ast(node, str(py_file.relative_to(backend_dir)))
                all_errors.extend(errors)

    assert not all_errors, "Rule 1 violations detected in codebase:\n" + "\n".join(all_errors)


def test_rule_1_detects_deliberate_violations() -> None:
    """Verify that the Rule 1 AST scanner reliably catches deliberate violations."""
    violating_code = """
def missing_try(x):
    return x + 1

def bare_except(x):
    try:
        return x / 0
    except:
        return 0

def swallowed_exception(x):
    try:
        return x / 0
    except Exception:
        pass
"""
    tree = ast.parse(violating_code)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            violations.extend(validate_function_ast(node, "dummy.py"))

    assert len(violations) == 3
    assert any("lacks a try/except block" in v for v in violations)
    assert any("bare 'except:'" in v for v in violations)
    assert any("swallows exception" in v for v in violations)
