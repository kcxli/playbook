"""A small, safe expression evaluator for ``when:`` conditions.

Supports: paths (``a.b.0.c``), literals (strings, numbers, true/false/null),
comparison operators ``== != < > <= >=``, membership ``in``, and the boolean
connectives ``and`` / ``or`` / ``not`` with parentheses. No Python ``eval`` is
used, so playbooks authored by colleagues cannot execute arbitrary code.

Examples::

    detailed_personal_info.birth_and_citizenship.requires_visa_sponsorship == true
    answers.previously_employed_here == false
    "disabled_veteran" in detailed_personal_info.veteran_status.protected_veteran_categories
    answers.county != null and answers.county != ""
"""
from __future__ import annotations

import re
from typing import Any

from .context import resolve_path


class ConditionError(Exception):
    pass


_TOKEN_RE = re.compile(
    r"""
      \s*(?:
        (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')   # quoted string
      | (?P<op><=|>=|==|!=|<|>)                          # comparison ops
      | (?P<lparen>\()
      | (?P<rparen>\))
      | (?P<word>[A-Za-z_][\w.]*)                        # keywords / paths
      | (?P<num>-?\d+(?:\.\d+)?)                          # number
      )
    """,
    re.VERBOSE,
)

_KEYWORDS = {"and", "or", "not", "in", "true", "false", "null", "none"}


def _tokenize(expr: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        if expr[pos].isspace():
            pos += 1
            continue
        match = _TOKEN_RE.match(expr, pos)
        if not match or match.end() == pos:
            raise ConditionError(f"cannot parse condition near: {expr[pos:pos + 20]!r}")
        kind = match.lastgroup
        text = match.group(match.lastgroup)
        tokens.append((kind, text))
        pos = match.end()
    tokens.append(("end", ""))
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], context: dict[str, Any]):
        self.tokens = tokens
        self.i = 0
        self.context = context

    def _peek(self) -> tuple[str, str]:
        return self.tokens[self.i]

    def _next(self) -> tuple[str, str]:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def parse(self) -> bool:
        value = self._or()
        if self._peek()[0] != "end":
            raise ConditionError(f"unexpected trailing tokens: {self.tokens[self.i:]}")
        return bool(value)

    def _or(self) -> Any:
        left = self._and()
        while self._is_word("or"):
            self._next()
            right = self._and()
            left = bool(left) or bool(right)
        return left

    def _and(self) -> Any:
        left = self._not()
        while self._is_word("and"):
            self._next()
            right = self._not()
            left = bool(left) and bool(right)
        return left

    def _not(self) -> Any:
        if self._is_word("not"):
            self._next()
            return not bool(self._not())
        return self._comparison()

    def _comparison(self) -> Any:
        left = self._primary()
        kind, text = self._peek()
        if kind == "op":
            self._next()
            right = self._primary()
            return self._apply_op(text, left, right)
        if self._is_word("in"):
            self._next()
            right = self._primary()
            try:
                return left in right
            except TypeError:
                return False
        return left

    def _primary(self) -> Any:
        kind, text = self._next()
        if kind == "lparen":
            value = self._or()
            if self._peek()[0] != "rparen":
                raise ConditionError("missing closing parenthesis")
            self._next()
            return value
        if kind == "str":
            return _unquote(text)
        if kind == "num":
            return float(text) if "." in text else int(text)
        if kind == "word":
            lowered = text.lower()
            if lowered == "true":
                return True
            if lowered == "false":
                return False
            if lowered in ("null", "none"):
                return None
            if lowered in ("and", "or", "not", "in"):
                raise ConditionError(f"unexpected keyword '{text}'")
            return resolve_path(text, self.context, default=None)
        raise ConditionError(f"unexpected token: {text!r}")

    def _is_word(self, word: str) -> bool:
        kind, text = self._peek()
        return kind == "word" and text.lower() == word

    @staticmethod
    def _apply_op(op: str, left: Any, right: Any) -> bool:
        try:
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            if op == "<":
                return left < right
            if op == ">":
                return left > right
            if op == "<=":
                return left <= right
            if op == ">=":
                return left >= right
        except TypeError:
            return False
        raise ConditionError(f"unknown operator {op}")


def _unquote(text: str) -> str:
    inner = text[1:-1]
    return inner.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")


def evaluate(expr: str, context: dict[str, Any]) -> bool:
    """Evaluate a ``when:`` expression to True/False against the context."""
    if expr is None:
        return True
    if isinstance(expr, bool):
        return expr
    tokens = _tokenize(str(expr))
    return _Parser(tokens, context).parse()
