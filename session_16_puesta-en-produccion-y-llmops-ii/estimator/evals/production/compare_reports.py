#!/usr/bin/env python3
"""Session 16 — regression check: this run against the baseline.

One measurement says how the system is today. Two say whether the last change
made it better or worse, which is the only question a change can be judged on.

    python -m evals.production.compare_reports reports/<baseline>.json reports/<latest>.json

A change is not judged by the case it fixed but by what it did to the whole set,
so this reports three things and fails on any of them:

* cases that passed in the baseline and fail now — the silent regression,
* a drop in the accuracy rate beyond ``--max-drop``,
* the loss of a correct abstention, which is a safety failure and never a
  rounding error.

It also prints what MOVED between the two runs — model, prompt, retrieval mode,
commit. A five-point drop means one thing when the only change is a prompt line
and something else entirely when the generation model changed underneath.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def _flat_meta(report: dict) -> dict[str, Any]:
    meta = report.get("meta") or {}
    flat = {k: v for k, v in meta.items() if not isinstance(v, dict)}
    for group in ("models", "retrieval"):
        for key, value in (meta.get(group) or {}).items():
            flat[f"{group}.{key}"] = value
    return flat


def _pct(value: Any) -> str:
    return "n/d" if value is None else f"{value * 100:.0f}%"


def compare(baseline_path: str, current_path: str, *, max_drop: float = 0.05) -> int:
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    current = json.loads(Path(current_path).read_text(encoding="utf-8"))

    base_meta, cur_meta = _flat_meta(baseline), _flat_meta(current)
    moved = {k: (base_meta.get(k), cur_meta.get(k)) for k in base_meta | cur_meta
             if base_meta.get(k) != cur_meta.get(k)}
    if moved:
        print(f"{DIM}Qué cambió entre las dos ejecuciones{RESET}")
        for key, (before, after) in sorted(moved.items()):
            print(f"  {key}: {before} → {after}")
    if base_meta.get("target") != cur_meta.get("target"):
        print(
            f"{YELLOW}AVISO: son rutas distintas ({base_meta.get('target')} vs "
            f"{cur_meta.get('target')}); esto compara dos sistemas, no dos versiones.{RESET}"
        )

    bm, cm = baseline["metrics"], current["metrics"]
    print(f"\n{DIM}Métricas{RESET}")
    for key, render in (
        ("within_range_rate", _pct),
        ("mean_absolute_error_hours", lambda v: "n/d" if v is None else f"{v:.1f} h"),
        ("mean_latency_ms", lambda v: "n/d" if v is None else f"{v/1000:.0f} s"),
        ("p95_latency_ms", lambda v: "n/d" if v is None else f"{v/1000:.0f} s"),
        ("hallucination_rate", _pct),
        ("error_rate", _pct),
    ):
        print(f"  {key:<26} {render(bm.get(key))} → {render(cm.get(key))}")

    passed_before = {c["id"] for c in baseline["cases"] if c.get("passed")}
    failing_now = {c["id"] for c in current["cases"] if not c.get("passed")}
    regressions = sorted(passed_before & failing_now)
    fixed = sorted({c["id"] for c in current["cases"] if c.get("passed")}
                   - {c["id"] for c in baseline["cases"] if c.get("passed")})

    print(f"\n  arreglados: {', '.join(fixed) if fixed else 'ninguno'}")
    print(f"  {'regresiones: ' + ', '.join(regressions) if regressions else 'regresiones: ninguna'}")

    drop = (bm.get("within_range_rate") or 0) - (cm.get("within_range_rate") or 0)
    safety_lost = bool(bm.get("abstention_correct")) and not cm.get("abstention_correct")
    if safety_lost:
        print(f"{RED}SEGURIDAD: el caso de abstención ya no se abstiene{RESET}")
    if drop > max_drop:
        print(f"{RED}La tasa de acierto cae {drop*100:.0f} puntos (máximo tolerado "
              f"{max_drop*100:.0f}){RESET}")

    failed = bool(regressions) or drop > max_drop or safety_lost
    print(("\n" + RED + "REGRESIÓN" + RESET) if failed else ("\n" + GREEN + "sin regresión" + RESET))
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("baseline")
    parser.add_argument("current")
    parser.add_argument(
        "--max-drop",
        type=float,
        default=0.05,
        help="Caída tolerada de within_range_rate antes de declarar regresión (0.05 = 5 puntos)",
    )
    args = parser.parse_args(argv)
    return compare(args.baseline, args.current, max_drop=args.max_drop)


if __name__ == "__main__":
    raise SystemExit(main())
