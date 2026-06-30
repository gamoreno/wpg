#
# Wildlife Protection Game
# 
# Copyright 2026 Carnegie Mellon University.
# 
# NO WARRANTY. THIS CARNEGIE MELLON UNIVERSITY AND SOFTWARE ENGINEERING INSTITUTE
# MATERIAL IS FURNISHED ON AN "AS-IS" BASIS. CARNEGIE MELLON UNIVERSITY MAKES NO
# WARRANTIES OF ANY KIND, EITHER EXPRESSED OR IMPLIED, AS TO ANY MATTER INCLUDING,
# BUT NOT LIMITED TO, WARRANTY OF FITNESS FOR PURPOSE OR MERCHANTABILITY,
# EXCLUSIVITY, OR RESULTS OBTAINED FROM USE OF THE MATERIAL. CARNEGIE MELLON
# UNIVERSITY DOES NOT MAKE ANY WARRANTY OF ANY KIND WITH RESPECT TO FREEDOM FROM
# PATENT, TRADEMARK, OR COPYRIGHT INFRINGEMENT.
# 
# Licensed under a BSD (SEI)-style license, please see license.txt or contact
# permission@sei.cmu.edu for full terms.
# 
# [DISTRIBUTION STATEMENT A] This material has been approved for public release
# and unlimited distribution.  Please see Copyright notice for non-US Government
# use and distribution.
# 
# This Software includes and/or makes use of Third-Party Software each subject
# to its own license.
# 
# DM26-0661

"""Convert strategy definitions from JsonLogic to a PDDL domain."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple, Union


def strategies_json_to_pddl_domain(
        strategies_json_path: Union[str, Path],
        domain_name: str = "wildlife-strategies",
) -> str:
    """Read a strategies JSON file and return a PDDL domain definition.

    Each strategy becomes one parameterless PDDL action. The strategy
    ``condition`` field is translated into the action ``:precondition`` and
    the strategy ``expectedOutcome`` field is translated into ``:effect``.
    """
    with Path(strategies_json_path).open("rt", encoding="utf-8") as f:
        data = json.load(f)

    try:
        strategies = data["strategies"]
    except KeyError as exc:
        raise ValueError("Strategies JSON must contain a top-level 'strategies' key.") from exc

    if not isinstance(strategies, list):
        raise ValueError("The 'strategies' value must be a list.")

    return strategies_to_pddl_domain(strategies, domain_name=domain_name)[0]


def strategies_to_pddl_domain(
        strategies: Iterable[Mapping[str, Any]],
        domain_name: str = "wildlife-strategies",
) -> tuple[str, dict[str, str]]:
    """Return a PDDL domain definition for strategy dictionaries."""
    strategy_list = list(strategies)
    variable_names = sorted(_collect_variables_from_strategies(strategy_list))
    predicate_names = _make_unique_name_map(variable_names)

    lines = [
        f"(define (domain {_pddl_name(domain_name)})",
        "  (:requirements :strips :negative-preconditions :disjunctive-preconditions)",
        "  (:predicates",
    ]

    if predicate_names:
        for variable_name in variable_names:
            lines.append(f"    ({predicate_names[variable_name]})")
    else:
        lines.append("    ;; No predicates were inferred from the strategy JsonLogic.")

    lines.append("  )")

    action_names: Set[str] = set()
    action_to_strategy_name: Dict[str, str] = {}
    for index, strategy in enumerate(strategy_list, start=1):
        lines.extend(_strategy_to_action(strategy, index, predicate_names, action_names, action_to_strategy_name))

    lines.append(")")
    pddl = "\n".join(lines) + "\n"

    return pddl, action_to_strategy_name


def _strategy_to_action(
        strategy: Mapping[str, Any],
        index: int,
        predicate_names: Mapping[str, str],
        used_action_names: Set[str],
        action_to_strategy_name: Dict[str, str],
) -> List[str]:
    if "name" not in strategy:
        raise ValueError(f"Strategy is missing required field 'name'.")
    raw_name = strategy["name"]
    action_name = _unique_name(_pddl_name(raw_name), used_action_names)
    action_to_strategy_name[action_name] = raw_name
    if "condition" not in strategy:
        raise ValueError(f"Strategy '{raw_name}' is missing required field 'condition'.")
    if "expectedOutcome" not in strategy:
        raise ValueError(f"Strategy '{raw_name}' is missing required field 'expectedOutcome'.")

    precondition = _jsonlogic_to_pddl(
        strategy["condition"],
        predicate_names,
        context="precondition",
    )
    _validate_effect_jsonlogic(strategy["expectedOutcome"], raw_name)
    effect = _jsonlogic_to_pddl(
        strategy["expectedOutcome"],
        predicate_names,
        context="effect",
    )

    return [
        "",
        f"  (:action {action_name}",
        "    :parameters ()",
        f"    :precondition {precondition}",
        f"    :effect {effect}",
        "  )",
    ]


def _jsonlogic_to_pddl(
        expression: Any,
        predicate_names: Mapping[str, str],
        context: str,
) -> str:
    if isinstance(expression, bool):
        return "(and)" if expression else "(or)"

    if isinstance(expression, dict):
        if len(expression) != 1:
            raise ValueError(f"Unsupported JsonLogic expression with multiple operators: {expression}")

        operator, value = next(iter(expression.items()))

        if operator == "var":
            variable_name = _jsonlogic_var_name(value)
            try:
                predicate_name = predicate_names[variable_name]
            except KeyError as exc:
                raise ValueError(f"Unknown JsonLogic variable '{variable_name}'.") from exc
            return f"({predicate_name})"

        if operator == "!":
            operands = _as_operand_list(value)
            if len(operands) != 1:
                raise ValueError(f"JsonLogic '!' expects one operand: {expression}")
            return _negate_expression(
                _jsonlogic_to_pddl(operands[0], predicate_names, context=context)
            )

        if operator in ("and", "or"):
            if context == "effect" and operator == "or":
                raise ValueError("PDDL effects do not support JsonLogic 'or'.")
            operands = _as_operand_list(value)
            converted = [
                _jsonlogic_to_pddl(operand, predicate_names, context=context)
                for operand in operands
            ]
            return _nary_expression(operator, converted)

        if operator in ("==", "==="):
            return _equality_to_pddl(value, predicate_names, negate=False)

        if operator in ("!=", "!=="):
            return _equality_to_pddl(value, predicate_names, negate=True)

    raise ValueError(f"Unsupported JsonLogic expression for PDDL conversion: {expression!r}")


def _equality_to_pddl(value: Any, predicate_names: Mapping[str, str], negate: bool) -> str:
    operands = _as_operand_list(value)
    if len(operands) != 2:
        raise ValueError(f"JsonLogic equality expects two operands: {value}")

    left, right = operands
    predicate = _boolean_comparison_to_predicate(left, right, predicate_names)
    if predicate is None:
        predicate = _boolean_comparison_to_predicate(right, left, predicate_names)
    if predicate is None:
        raise ValueError(f"Only boolean equality against a JsonLogic variable is supported: {value}")

    expression, expected_truth = predicate
    should_negate = negate == expected_truth
    return f"(not {expression})" if should_negate else expression


def _negate_expression(expression: str) -> str:
    if expression.startswith("(not ") and expression.endswith(")"):
        return expression[5:-1]
    return f"(not {expression})"


def _boolean_comparison_to_predicate(
        variable_expression: Any,
        literal_expression: Any,
        predicate_names: Mapping[str, str],
) -> Optional[Tuple[str, bool]]:
    if not (isinstance(variable_expression, dict) and set(variable_expression) == {"var"}):
        return None
    if not isinstance(literal_expression, bool):
        return None

    variable_name = _jsonlogic_var_name(variable_expression["var"])
    predicate_name = predicate_names[variable_name]
    return f"({predicate_name})", literal_expression


def _validate_effect_jsonlogic(expression: Any, strategy_name: str) -> None:
    if not _is_supported_effect_jsonlogic(expression):
        raise ValueError(
            "Strategy "
            f"'{strategy_name}' has an expectedOutcome that cannot be represented "
            "as a PDDL effect. Effects must be a variable, a negated variable, "
            "a boolean equality against a variable, or an 'and' of those."
        )


def _is_supported_effect_jsonlogic(expression: Any) -> bool:
    if isinstance(expression, dict) and len(expression) == 1:
        operator, value = next(iter(expression.items()))
        if operator == "var":
            _jsonlogic_var_name(value)
            return True
        if operator == "!":
            operands = _as_operand_list(value)
            return len(operands) == 1 and _is_effect_literal_jsonlogic(operands[0])
        if operator == "and":
            return all(_is_supported_effect_jsonlogic(item) for item in _as_operand_list(value))
        if operator in ("==", "===", "!=", "!=="):
            return _is_effect_literal_jsonlogic(expression)
    return False


def _is_effect_literal_jsonlogic(expression: Any) -> bool:
    if isinstance(expression, dict) and len(expression) == 1:
        operator, value = next(iter(expression.items()))
        if operator == "var":
            _jsonlogic_var_name(value)
            return True
        if operator in ("==", "===", "!=", "!=="):
            operands = _as_operand_list(value)
            if len(operands) != 2:
                return False
            left, right = operands
            return (
                    _is_var_expression(left) and isinstance(right, bool)
            ) or (
                    _is_var_expression(right) and isinstance(left, bool)
            )
    return False


def _is_var_expression(expression: Any) -> bool:
    if not (isinstance(expression, dict) and set(expression) == {"var"}):
        return False
    _jsonlogic_var_name(expression["var"])
    return True


def _collect_variables_from_strategies(strategies: Iterable[Mapping[str, Any]]) -> Set[str]:
    variable_names: Set[str] = set()
    for strategy in strategies:
        if "condition" in strategy:
            variable_names.update(_collect_variables(strategy["condition"]))
        if "expectedOutcome" in strategy:
            variable_names.update(_collect_variables(strategy["expectedOutcome"]))
    return variable_names


def _collect_variables(expression: Any) -> Set[str]:
    if isinstance(expression, dict):
        variable_names: Set[str] = set()
        for operator, value in expression.items():
            if operator == "var":
                variable_names.add(_jsonlogic_var_name(value))
            else:
                variable_names.update(_collect_variables(value))
        return variable_names

    if isinstance(expression, list):
        variable_names = set()
        for item in expression:
            variable_names.update(_collect_variables(item))
        return variable_names

    return set()


def _jsonlogic_var_name(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    raise ValueError(f"Unsupported JsonLogic var operand: {value!r}")


def _as_operand_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else [value]


def _nary_expression(operator: str, operands: List[str]) -> str:
    if not operands:
        return "(and)" if operator == "and" else "(or)"
    if len(operands) == 1:
        return operands[0]
    joined = " ".join(operands)
    return f"({operator} {joined})"


def _make_unique_name_map(raw_names: Iterable[str]) -> Dict[str, str]:
    used_names: Set[str] = set()
    name_map: Dict[str, str] = {}
    for raw_name in raw_names:
        name_map[raw_name] = _unique_name(_pddl_name(raw_name), used_names)
    return name_map


def _unique_name(name: str, used_names: Set[str]) -> str:
    unique_name = name
    suffix = 2
    while unique_name in used_names:
        unique_name = f"{name}-{suffix}"
        suffix += 1
    used_names.add(unique_name)
    return unique_name


def _pddl_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = "unnamed"
    if not re.match(r"^[a-zA-Z]", cleaned):
        cleaned = f"n-{cleaned}"
    return cleaned
