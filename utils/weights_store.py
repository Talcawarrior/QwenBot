"""JSON weight persistence for SIA.

The SIA loop optimizes MODEL_WEIGHTS in memory and on ModelPerformance rows,
but the live config object is process-local. Without a durable copy, every
restart throws away the learned weights and goes back to the static defaults
in config/settings.py. This module adds a single-file load/save on top.

Design notes
------------
* The file is read at SIALoop.__init__ time, so any process that imports
  engine.strategy and instantiates SIALoop gets the latest learned weights
  before it computes its first probability.
* The file is written on every optimize_weights() call when the maximum
  absolute change vs. the previous persisted weights is >= 0.001 (0.1
  percentage points). Smaller updates are logged but not written so we
  do not spam the disk on cosmetic drift.
* Errors are never raised -- a missing file, a corrupted file, or a
  read-only filesystem all fall back to the in-memory defaults. The bot
  is paper-mode, but it should still survive accidental edits of the
  JSON file.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Project root: two parents up from utils/ -> repo root. The file lives at
# data/model_weights.json so it sits next to data/bot.db.
_DEFAULT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "data", "model_weights.json")
)

_lock = threading.Lock()


def _normalize(weights: Dict[str, float]) -> Dict[str, float]:
    """Return weights as plain floats, dropping unknown keys.

    A new model appearing in code but missing from the persisted file
    will still be picked up from the in-memory defaults because the
    caller (SIALoop.__init__) merges this dict over `self.model_weights`.
    """
    out: Dict[str, float] = {}
    for k, v in weights.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def load_weights(path: Optional[str] = None) -> Optional[Dict[str, float]]:
    """Read model weights from disk.

    Returns the dict on success, or None if the file is missing, empty,
    unparseable, or the data directory is unreadable. Callers should
    fall back to the in-memory defaults on None.
    """
    p = path or _DEFAULT_PATH
    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load model weights from %s: %s", p, exc)
        return None
    if not isinstance(raw, dict):
        return None
    norm = _normalize(raw)
    return norm or None


def save_weights(
    weights: Dict[str, float],
    path: Optional[str] = None,
    *,
    min_change: float = 0.001,
) -> bool:
    """Persist model weights if they changed enough to matter.

    Returns True if a write happened, False if the change was too small
    or the write failed (in which case a warning is logged but no
    exception is raised -- the in-memory update still took effect).
    """
    p = path or _DEFAULT_PATH
    norm = _normalize(weights)
    if not norm:
        return False

    with _lock:
        prev = load_weights(p)
        if prev is not None:
            # Compare union of keys so a newly-tracked model still triggers
            # a write on its first appearance.
            keys = set(prev) | set(norm)
            max_delta = max(
                abs(norm.get(k, 0.0) - prev.get(k, 0.0)) for k in keys
            )
            if max_delta < min_change:
                logger.info(
                    "SIA weight change %.4f below threshold %.4f, skipping write",
                    max_delta,
                    min_change,
                )
                return False
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(norm, f, indent=2, sort_keys=True)
            os.replace(tmp, p)
            logger.info("SIA weights persisted to %s", p)
            return True
        except OSError as exc:
            logger.warning("Could not save model weights to %s: %s", p, exc)
            return False
