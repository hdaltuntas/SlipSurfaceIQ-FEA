from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SOURCES = {"rs2", "plaxis", "plaxis2d"}
REQUIRED_COLUMNS = ("depth_m", "M_kNm_per_m", "u_top_mm", "source")
REQUIRED_INPUT_MATCH = (
    "geometry",
    "soil",
    "wall",
    "interfaces",
    "initial_stress",
    "boundaries",
    "stages",
    "tip_connection",
    "tension_cutoff",
)
PEAK_MOMENT_RELATIVE_LIMIT = 0.10
MIN_PROFILE_POINTS = 8
MAX_PROFILE_GAP_M = 1.0
DEPTH_TOL_M = 1e-6


class S4ExternalComparisonError(ValueError):
    """External evidence is incomplete or not equivalent to the locked S4 case."""


def _float(value: str, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise S4ExternalComparisonError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise S4ExternalComparisonError(f"{label} must be finite")
    return number


def _load_meta(path: Path, expected_case_sha: str) -> dict:
    if not path.is_file():
        raise S4ExternalComparisonError(f"Missing external metadata: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    source = str(data.get("source", "")).strip().lower()
    if source not in ALLOWED_SOURCES:
        raise S4ExternalComparisonError("metadata source must be RS2 or PLAXIS/PLAXIS2D")
    if not str(data.get("program_version", "")).strip():
        raise S4ExternalComparisonError("metadata program_version is required")
    if str(data.get("case_sha256", "")).strip().lower() != expected_case_sha.lower():
        raise S4ExternalComparisonError("metadata case_sha256 does not match the locked S4 case")
    if str(data.get("analysis", "")).strip().lower() != "plane_strain":
        raise S4ExternalComparisonError("metadata analysis must be plane_strain")
    if str(data.get("stage", "")).strip().lower() != "excavate":
        raise S4ExternalComparisonError("metadata stage must be excavate")
    if data.get("converged") is not True:
        raise S4ExternalComparisonError("external solution must be marked converged")
    match = data.get("input_match")
    if not isinstance(match, dict):
        raise S4ExternalComparisonError("metadata input_match object is required")
    missing = [name for name in REQUIRED_INPUT_MATCH if match.get(name) is not True]
    if missing:
        raise S4ExternalComparisonError(
            "external input equivalence is not confirmed for: " + ", ".join(missing)
        )
    return data


def _load_external(path: Path, expected_source: str) -> tuple[list[tuple[float, float]], float]:
    if not path.is_file():
        raise S4ExternalComparisonError(f"Missing external table: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = tuple(reader.fieldnames or ())
        missing = [name for name in REQUIRED_COLUMNS if name not in fields]
        if missing:
            raise S4ExternalComparisonError(
                "external.csv missing columns: " + ", ".join(missing)
            )
        rows = list(reader)
    if not rows:
        raise S4ExternalComparisonError("external.csv contains no data rows")

    points = []
    top_values = []
    for index, row in enumerate(rows, start=2):
        depth = _float(row["depth_m"], f"row {index} depth_m")
        moment = _float(row["M_kNm_per_m"], f"row {index} M_kNm_per_m")
        if depth < -DEPTH_TOL_M or depth > 10.5 + DEPTH_TOL_M:
            raise S4ExternalComparisonError(f"row {index} depth is outside the 0..10.5 m wall")
        source = str(row["source"]).strip().lower()
        if source != expected_source:
            raise S4ExternalComparisonError(
                f"row {index} source {source!r} does not match metadata source {expected_source!r}"
            )
        points.append((depth, moment))
        raw_ux = str(row.get("u_top_mm", "")).strip()
        if raw_ux:
            if abs(depth) > DEPTH_TOL_M:
                raise S4ExternalComparisonError("u_top_mm may only be supplied at depth 0")
            top_values.append(_float(raw_ux, f"row {index} u_top_mm"))

    if len(top_values) != 1:
        raise S4ExternalComparisonError("exactly one wall-head u_top_mm value is required")

    grouped: dict[float, list[float]] = {}
    for depth, moment in points:
        key = round(depth, 9)
        grouped.setdefault(key, []).append(moment)
    profile = sorted((depth, sum(values) / len(values)) for depth, values in grouped.items())
    if len(profile) < MIN_PROFILE_POINTS:
        raise S4ExternalComparisonError(
            f"external moment profile needs at least {MIN_PROFILE_POINTS} unique depths"
        )
    if profile[0][0] > 0.1 or profile[-1][0] < 10.4:
        raise S4ExternalComparisonError("external profile must cover the wall head and toe")
    max_gap = max(b[0] - a[0] for a, b in zip(profile, profile[1:]))
    if max_gap > MAX_PROFILE_GAP_M + DEPTH_TOL_M:
        raise S4ExternalComparisonError(
            f"external profile gap {max_gap:.6g} m exceeds {MAX_PROFILE_GAP_M:g} m"
        )
    return profile, top_values[0]


def _load_internal_profile(path: Path) -> list[tuple[float, float]]:
    grouped: dict[float, list[float]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = tuple(reader.fieldnames or ())
        if "depth_m" not in fields or "M_up_kNm_per_m" not in fields:
            raise S4ExternalComparisonError("internal S4 profile schema is incomplete")
        for row in reader:
            depth = _float(row["depth_m"], "internal depth_m")
            moment = _float(row["M_up_kNm_per_m"], "internal M_up_kNm_per_m")
            grouped.setdefault(round(depth, 9), []).append(moment)
    profile = sorted((depth, sum(values) / len(values)) for depth, values in grouped.items())
    if len(profile) < 2:
        raise S4ExternalComparisonError("internal S4 profile is empty")
    return profile


def _interp(profile: list[tuple[float, float]], depth: float) -> float:
    xs = [item[0] for item in profile]
    if depth < xs[0] - DEPTH_TOL_M or depth > xs[-1] + DEPTH_TOL_M:
        raise S4ExternalComparisonError("external depth falls outside internal profile")
    if depth <= xs[0]:
        return profile[0][1]
    if depth >= xs[-1]:
        return profile[-1][1]
    upper = bisect.bisect_right(xs, depth)
    x0, y0 = profile[upper - 1]
    x1, y1 = profile[upper]
    ratio = (depth - x0) / (x1 - x0)
    return y0 + ratio * (y1 - y0)


def compare(
    external_csv: Path,
    external_meta: Path,
    internal_profile_csv: Path,
    internal_results_json: Path,
) -> dict:
    results = json.loads(internal_results_json.read_text(encoding="utf-8"))
    run = results["runs"]["h0125"]
    expected_case_sha = str(run["case_sha256"])
    meta = _load_meta(external_meta, expected_case_sha)
    source = str(meta["source"]).strip().lower()
    external, external_top_ux = _load_external(external_csv, source)
    internal = _load_internal_profile(internal_profile_csv)

    internal_peak = float(run["max_abs_moment_kNm_per_m"])
    internal_top_ux = float(run["wall_top_ux_m"]) * 1000.0
    external_peak_depth, external_peak_signed = max(external, key=lambda item: abs(item[1]))
    external_peak = abs(external_peak_signed)
    if external_peak <= 0:
        raise S4ExternalComparisonError("external maximum moment must be non-zero")

    peak_relative_error = abs(internal_peak - external_peak) / external_peak
    sampled = [(depth, _interp(internal, depth), moment) for depth, moment in external]
    profile_max_abs_error = max(abs(i - e) for _, i, e in sampled) / external_peak
    profile_rmse = math.sqrt(
        sum((i - e) ** 2 for _, i, e in sampled) / len(sampled)
    ) / external_peak
    internal_at_external_peak = _interp(internal, external_peak_depth)
    sign_ok = (
        abs(external_peak_signed) <= 1e-12
        or abs(internal_at_external_peak) <= 1e-12
        or external_peak_signed * internal_at_external_peak > 0
    )
    ux_denominator = max(abs(external_top_ux), 1e-12)
    ux_relative_error = abs(internal_top_ux - external_top_ux) / ux_denominator
    ux_sign_ok = (
        abs(external_top_ux) <= 1e-12
        or abs(internal_top_ux) <= 1e-12
        or external_top_ux * internal_top_ux > 0
    )

    checks = {
        "input_equivalence": True,
        "profile_coverage": True,
        "moment_sign_convention": sign_ok,
        "ux_sign_convention": ux_sign_ok,
        "peak_moment_within_10_percent": peak_relative_error <= PEAK_MOMENT_RELATIVE_LIMIT,
    }
    depths = [item[0] for item in external]
    return {
        "schema": "slipsurface.s4-external-comparison.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "source": source,
        "program_version": str(meta["program_version"]),
        "case_sha256": expected_case_sha,
        "criteria": {
            "peak_moment_relative_error_limit": PEAK_MOMENT_RELATIVE_LIMIT,
            "profile_and_top_ux": (
                "diagnostic; sign convention required, no extra magnitude tolerance"
            ),
        },
        "coverage": {
            "unique_depth_count": len(external),
            "min_depth_m": min(depths),
            "max_depth_m": max(depths),
            "max_gap_m": max(b - a for a, b in zip(depths, depths[1:])),
        },
        "metrics": {
            "slipsurface_peak_abs_moment_kNm_per_m": internal_peak,
            "external_peak_abs_moment_kNm_per_m": external_peak,
            "external_peak_depth_m": external_peak_depth,
            "peak_moment_relative_error": peak_relative_error,
            "moment_profile_normalized_max_abs_difference": profile_max_abs_error,
            "moment_profile_normalized_rmse": profile_rmse,
            "slipsurface_top_ux_mm": internal_top_ux,
            "external_top_ux_mm": external_top_ux,
            "top_ux_relative_difference": ux_relative_error,
        },
        "checks": checks,
    }


def markdown(report: dict) -> str:
    metrics = report["metrics"]
    checks = report["checks"]
    lines = [
        "# S4 external comparison",
        "",
        f"Status: **{report['status'].upper()}**",
        f"Source: {report['source'].upper()} {report['program_version']}",
        "",
        "| Metric | Value |",
        "|---|---:|",
        (
            "| SlipSurface peak | "
            f"{metrics['slipsurface_peak_abs_moment_kNm_per_m']:.6g} kN·m/m |"
        ),
        f"| External peak | {metrics['external_peak_abs_moment_kNm_per_m']:.6g} kN·m/m |",
        f"| Peak relative error | {100 * metrics['peak_moment_relative_error']:.3f}% |",
        (
            "| Moment field max normalized difference | "
            f"{100 * metrics['moment_profile_normalized_max_abs_difference']:.3f}% |"
        ),
        (
            "| Moment field normalized RMSE | "
            f"{100 * metrics['moment_profile_normalized_rmse']:.3f}% |"
        ),
        f"| SlipSurface wall-head ux | {metrics['slipsurface_top_ux_mm']:.6g} mm |",
        f"| External wall-head ux | {metrics['external_top_ux_mm']:.6g} mm |",
        (
            "| Wall-head ux relative difference | "
            f"{100 * metrics['top_ux_relative_difference']:.3f}% |"
        ),
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    lines.extend(f"| {name} | {'PASS' if ok else 'FAIL'} |" for name, ok in checks.items())
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare locked S4 results with RS2/PLAXIS output."
    )
    parser.add_argument("--external", type=Path, default=ROOT / "docs/data/s4/external.csv")
    parser.add_argument("--meta", type=Path, default=ROOT / "docs/data/s4/external-meta.json")
    parser.add_argument(
        "--internal-profile",
        type=Path,
        default=ROOT / "docs/data/s4/h0125-wall-end-forces.csv",
    )
    parser.add_argument(
        "--internal-results", type=Path, default=ROOT / "docs/data/s4/results.json"
    )
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--markdown", dest="markdown_path", type=Path)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = compare(
            args.external, args.meta, args.internal_profile, args.internal_results
        )
    except (OSError, KeyError, json.JSONDecodeError, S4ExternalComparisonError) as exc:
        report = {
            "schema": "slipsurface.s4-external-comparison.v1",
            "status": "blocked",
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    print(payload, end="")
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(payload, encoding="utf-8")
    if args.markdown_path:
        args.markdown_path.parent.mkdir(parents=True, exist_ok=True)
        text = (
            markdown(report)
            if report.get("status") in {"passed", "failed"}
            else "# S4 external comparison\n\n"
            f"Status: **BLOCKED**\n\n{report.get('error', 'External evidence is incomplete.')}\n"
        )
        args.markdown_path.write_text(text, encoding="utf-8")
    return 1 if args.require_pass and report.get("status") != "passed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
