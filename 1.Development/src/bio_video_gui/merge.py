"""Merge several per-phase stacks (e.g. baseline, activation) into one continuous stack."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Phase:
    """One labeled segment of the merged timeline."""

    name: str
    start_frame: int  # frame index (in the merged stack) where this phase begins


@dataclass
class MergeResult:
    stack: np.ndarray  # (T, H, W) or (T, H, W, C)
    phases: list[Phase]


def concat_stacks(stacks: list[np.ndarray]) -> np.ndarray:
    """Concatenate stacks along the time axis with no phase labeling.

    Used when phase annotations are defined afterwards, rather than tied to
    the layers being merged (see `Phase` / the widget's phase table).
    """
    if not stacks:
        raise ValueError("at least one stack is required")
    shape_tail = stacks[0].shape[1:]
    for i, s in enumerate(stacks):
        if s.shape[1:] != shape_tail:
            raise ValueError(
                f"stack #{i} has shape {s.shape}, expected trailing "
                f"dims {shape_tail} to match the first stack"
            )
    return np.concatenate(stacks, axis=0)


def merge_phases(stacks: list[np.ndarray], names: list[str]) -> MergeResult:
    """Concatenate stacks along the time axis, recording where each phase starts.

    All stacks must share H, W (and C, if present). Raises ValueError otherwise.
    """
    if len(stacks) != len(names):
        raise ValueError("stacks and names must have the same length")
    if not stacks:
        raise ValueError("at least one stack is required")

    shape_tail = stacks[0].shape[1:]
    for i, s in enumerate(stacks):
        if s.shape[1:] != shape_tail:
            raise ValueError(
                f"stack '{names[i]}' has shape {s.shape}, expected trailing "
                f"dims {shape_tail} to match '{names[0]}'"
            )

    phases: list[Phase] = []
    offset = 0
    for s, name in zip(stacks, names):
        phases.append(Phase(name=name, start_frame=offset))
        offset += s.shape[0]

    merged = np.concatenate(stacks, axis=0)
    return MergeResult(stack=merged, phases=phases)


def phase_label_at(phases: list[Phase], frame: int) -> str:
    """Return the name of the phase active at a given frame index."""
    current = phases[0].name if phases else ""
    for p in phases:
        if frame >= p.start_frame:
            current = p.name
        else:
            break
    return current
