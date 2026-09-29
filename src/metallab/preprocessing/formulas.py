"""Formula preservation and opt-in SymPy validation."""

from __future__ import annotations

from typing import Any


def formula_metadata(original: str, *, enabled: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "original": original,
        "latex": original if "\\" in original else None,
        "canonical": None,
        "sympy_valid": None,
        "warning": None,
    }
    if not enabled:
        result["warning"] = "SymPy validation disabled by configuration"
        return result
    try:
        from sympy.parsing.latex import parse_latex

        expression = parse_latex(original)
        result["canonical"] = str(expression)
        result["sympy_valid"] = True
    except ImportError:
        result["warning"] = "Install the optional formulas extra to enable SymPy validation"
    except Exception as error:  # Parsing is best effort; original formula always survives.
        result["sympy_valid"] = False
        result["warning"] = f"SymPy could not parse formula: {type(error).__name__}"
    return result
