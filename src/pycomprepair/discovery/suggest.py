"""Fuzzy-match a removed dotted symbol against the installed API.

The :mod:`pycomprepair.discovery.attr_check` analyser flags any attribute
chain that resolves to a path missing from the installed package. When the
removal is covered by :data:`pycomprepair.discovery.known_fixes.KNOWN_FIXES`
the issue carries an actionable fix; otherwise the user still has to look
up the new name by hand.

This module narrows that gap *without* requiring a hand-written rule. For a
missing path like ``numpy.in1dd`` (typo / renamed symbol) it asks the
:class:`APIIndex` for all sibling symbols under the same parent module and
returns the closest matches as ranked ``(name, score)`` tuples.

The matcher is intentionally conservative:

* Only **sibling** symbols are considered (same parent module). Suggesting
  ``torch.tensor`` for ``numpy.tnesor`` would just be noise.
* :func:`difflib.get_close_matches` is used with a strict default cutoff so
  near-miss typos surface but unrelated names do not.
* The result is exposed as advisory only -- callers wrap it in a
  :class:`pycomprepair.core.issue.Fix` with ``safe=False`` and a confidence
  proportional to the match ratio. ``discover --fix`` never auto-applies a
  fuzzy suggestion.
"""

from __future__ import annotations

from difflib import SequenceMatcher, get_close_matches

from pycomprepair.discovery.api_index import APIIndex

__all__ = ["Suggestion", "suggest_replacements"]


class Suggestion(tuple[str, float]):
    """``(qualified_path, score)`` pair returned by :func:`suggest_replacements`.

    ``score`` is the :class:`difflib.SequenceMatcher` ratio in ``[0.0, 1.0]``
    between the missing leaf and the candidate's leaf. We expose the type
    as a named tuple-like to make consumer call-sites self-documenting.
    """

    __slots__ = ()

    def __new__(cls, path: str, score: float) -> Suggestion:
        return super().__new__(cls, (path, score))

    @property
    def path(self) -> str:
        return self[0]

    @property
    def score(self) -> float:
        return self[1]


def _parent_and_leaf(qualified: str) -> tuple[str, str]:
    parent, _, leaf = qualified.rpartition(".")
    return parent, leaf


def _siblings(parent: str, index: APIIndex) -> list[str]:
    """Return every direct child of ``parent`` registered in ``index``.

    ``parent`` itself does not need to be a container; we still match by
    prefix. Grand-children (``parent.sub.leaf``) are excluded so the score
    stays meaningful.
    """
    if not parent:
        return []
    prefix = parent + "."
    out: list[str] = []
    for symbol in index.symbols:
        if not symbol.startswith(prefix):
            continue
        remainder = symbol[len(prefix) :]
        if "." in remainder:
            continue
        out.append(remainder)
    return out


def suggest_replacements(
    missing: str,
    index: APIIndex,
    *,
    cutoff: float = 0.7,
    max_results: int = 3,
) -> list[Suggestion]:
    """Return the best sibling replacements for a missing dotted path.

    Parameters
    ----------
    missing:
        Fully-qualified path that ``attr_check`` flagged as removed
        (``"numpy.in1dd"``).
    index:
        :class:`APIIndex` loaded for the *installed* version of the package.
    cutoff:
        Minimum similarity ratio in ``[0.0, 1.0]``. Defaults to ``0.7`` so
        near-miss typos (``in1d`` vs ``isin``) and obvious renames surface
        without polluting the report with unrelated names.
    max_results:
        Upper bound on the number of suggestions to return.

    The function never raises: an empty list means "no confident sibling
    match"; the caller should fall back to its default behaviour.
    """
    if not missing or not index.belongs_to(missing.partition(".")[0]):
        return []
    parent, leaf = _parent_and_leaf(missing)
    if not leaf:
        return []
    candidates = _siblings(parent, index)
    if not candidates:
        return []
    matches = get_close_matches(leaf, candidates, n=max_results, cutoff=cutoff)
    if not matches:
        return []
    return [
        Suggestion(f"{parent}.{m}", round(SequenceMatcher(None, leaf, m).ratio(), 3))
        for m in matches
    ]
