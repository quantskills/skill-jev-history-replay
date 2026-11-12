"""评测编排：加载 → 重放 → 对齐 → 归因 → 价值评估 → 落盘。

执行阶段只读本地 fixture，不访问任何外部服务。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import attribution, config as cfg, data_loader, log_synth, metrics, report
from . import semantics as sem
from .aligner import align_symbol, aggregate_rows
from .replayer import replay_all

REPO_ROOT = Path(__file__).resolve().parents[1]


class ReplayError(ValueError):
    """评测失败（输入不合法 / 数据不足 / 配置冲突）。"""

    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def _load_prev_closes(reference_path: Optional[Path],
                      series_keys: List[str]) -> Dict[str, float]:
    """按 series key 取前收价。

    目录内可能有多个 reference 文件（多日夹具）。每个标的的每个交易日
    各自取自己的前收，绝不复用其它交易日——跨日复用会让涨幅基准错位，
    而那正是本 skill 要度量的东西之一。

    单日模式下 series key 等于裸代码，行为与旧版一致。
    """
    out: Dict[str, float] = {}
    ref_dir = reference_path if reference_path and reference_path.is_dir() else (
        reference_path.parent if reference_path else None
    )
    if not ref_dir or not ref_dir.exists():
        return out

    files = sorted(ref_dir.glob("*.json"))
    if reference_path and reference_path.is_file():
        files = [reference_path]
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for symbol, by_date in payload.get("symbols", {}).items():
            for date_text, row in by_date.items():
                pre = row.get("pre_close")
                if not pre:
                    continue
                out.setdefault(data_loader.series_key(symbol, date_text), float(pre))
                out.setdefault(symbol, float(pre))
    return out


def _find_reference(fixtures_root: Path, date: Optional[str]) -> Optional[Path]:
    """返回 reference 目录（多日模式按目录读全部），兼容旧的单文件路径。"""
    ref_dir = fixtures_root / "reference"
    if ref_dir.exists():
        return ref_dir
    return None


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("jev-%Y%m%dT%H%M%S%fZ")


def evaluate(*, bars_dir: str | Path | None = None,
             logs_dir: str | Path | None = None,
             output_dir: str | Path | None = None,
             reference_path: str | Path | None = None,
             semantics_override: Optional[Dict[str, Any]] = None,
             config_overrides: Optional[Dict[str, Any]] = None,
             run_attribution: bool = True,
             config_path: str | Path | None = None) -> Dict[str, Any]:
    overrides = dict(config_overrides or {})
    if bars_dir is not None:
        overrides["bars_dir"] = str(bars_dir)
    if logs_dir is not None:
        overrides["logs_dir"] = str(logs_dir)
    if output_dir is not None:
        overrides["output_dir"] = str(output_dir)
    config = cfg.load_config(config_path, overrides)

    semantics = dict(config["semantics"])
    if semantics_override:
        semantics.update(semantics_override)
    problems = sem.validate_semantics(semantics)
    if problems:
        raise ReplayError(
            "invalid_semantics",
            "语义配置不合法：" + "; ".join(problems),
            hint="对照 references/semantics_matrix.md 的允许取值",
        )
    semantics["_hash"] = sem.semantics_hash(semantics)

    bars_path = Path(config["bars_dir"])
    if not bars_path.is_absolute():
        bars_path = REPO_ROOT / bars_path
    try:
        bars = data_loader.load_bars(bars_path)
    except data_loader.LoadError as exc:
        raise ReplayError(exc.code, exc.message, exc.hint) from exc

    manifest = None
    manifest_path = REPO_ROOT / "fixtures" / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = None

    ref_path = Path(reference_path) if reference_path else _find_reference(
        bars_path.parent, (manifest or {}).get("date")
    )
    prev_closes = _load_prev_closes(ref_path, list(bars))
    missing_prev = [s for s in bars if s not in prev_closes]
    if missing_prev:
        # 无前收时用当日首根开盘价近似，并在报告里标注
        for series in missing_prev:
            prev_closes[series] = bars[series]["bars"][0]["open"]

    current = replay_all(bars, semantics, prev_closes)

    # --- 日志侧：真实优先，缺失时合成 ---
    log_source = "actual"
    logged_semantics: Optional[Dict[str, Any]] = None
    forced_source = config.get("log_source", "auto")
    logs_dir = config.get("logs_dir")
    log_records: List[Dict[str, Any]] = []
    if logs_dir:
        logs_path = Path(logs_dir)
        if not logs_path.is_absolute():
            logs_path = REPO_ROOT / logs_path
        if logs_path.exists() and data_loader._list_data_files(logs_path):
            try:
                log_records = data_loader.load_logs(logs_path)
            except data_loader.LoadError as exc:
                raise ReplayError(exc.code, exc.message, exc.hint) from exc
    if not log_records:
        profile_name = config["logged_profile"]
        try:
            logged = dict(config["semantics"])
            logged.update(sem.get_profile(profile_name))
        except KeyError as exc:
            raise ReplayError("unknown_profile", str(exc)) from exc
        logged_semantics = {
            "profile": profile_name,
            "hash": sem.semantics_hash(logged),
            "knobs": sem.extract_knobs(logged),
        }
        log_records = log_synth.synthesize_logs(bars, logged, prev_closes)
        log_source = "synthetic"

    if forced_source in ("actual", "synthetic"):
        log_source = forced_source
    elif any(rec.get("_synthetic") for rec in log_records):
        log_source = "synthetic"

    # 从磁盘读到的合成日志同样要能说明"按哪套档位生成"。
    # 否则 provenance 只能说"这是合成的"，却说不出合成所用语义，
    # 读者无法判断差异是否只是档位不同造成的。
    if log_source == "synthetic" and logged_semantics is None:
        profile_name = config["logged_profile"]
        try:
            logged = dict(config["semantics"])
            logged.update(sem.get_profile(profile_name))
        except KeyError as exc:
            raise ReplayError("unknown_profile", str(exc)) from exc
        logged_semantics = {
            "profile": profile_name,
            "hash": sem.semantics_hash(logged),
            "knobs": sem.extract_knobs(logged),
            "source": "disk (fixtures/logs 内含 _synthetic 标记)",
        }

    multi_day = len({entry.get("date") for entry in bars.values()}) > 1
    log_records = data_loader.normalize_log_records(log_records, multi_day=multi_day)
    grouped = data_loader.group_logs(log_records)

    # --- 对齐 ---
    tol = int(config["time_tolerance_minutes"])
    price_tol = float(config["price_tolerance_bps"])
    rows_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    decision_changes: List[Dict[str, Any]] = []
    # 对齐按序列（symbol@date）逐日进行：跨日周期的入场与退出分属两天，
    # 只有逐日对齐才能与同日日志正确配对。单日模式下 by_series 与 symbols 同构。
    series_views = current.get("by_series") or current["symbols"]
    for series, view in series_views.items():
        groups = grouped.get(series) or {
            "condition": [], "signal": [], "plan": [], "fill": []
        }
        aligned = align_symbol(series, view, groups, tol, price_tol)
        rows_by_symbol[series] = aligned["rows"]
        decision_changes.extend(aligned["decision_changes"])

    aggregate = aggregate_rows(rows_by_symbol)
    ledger = report.build_ledger_block(rows_by_symbol, int(config["max_inline_rows"]))
    ledger["decision_changes"] = decision_changes[: int(config["max_inline_rows"])]
    ledger["decision_change_count"] = len(decision_changes)

    # --- 归因 ---
    if run_attribution:
        attribution_result = attribution.run_ablation(
            bars, semantics, prev_closes,
            baseline_divergences=aggregate["total"]["divergent"],
            baseline_comparable=aggregate["total"]["comparable"],
            log_groups_by_symbol=grouped,
            tol_minutes=tol,
            price_tolerance_bps=price_tol,
        )
    else:
        attribution_result = {"verdict": "skipped", "ranked": [], "note": "run_attribution=False"}

    # --- 价值评估：字面直译基线 vs 当前显式语义（同一份真实 K 线）---
    naive = evaluate_naive(bars, semantics, prev_closes)
    value_assessment = report.build_value_assessment(
        naive, current, int(config["min_cycles"])
    )

    alignment = report.build_alignment_conclusion(
        aggregate, ledger["divergence_rows"], log_source
    )

    comparability = {
        "semantics_hash": semantics["_hash"],
        "logged_semantics_hash": (logged_semantics or {}).get("hash"),
        "fixture_fingerprint": (manifest or {}).get("fixture_fingerprint"),
        "symbol_count": len(bars),
        "log_record_count": len(log_records),
        "time_tolerance_minutes": tol,
        "price_tolerance_bps": price_tol,
        "max_inline_rows": int(config["max_inline_rows"]),
        "min_cycles": int(config["min_cycles"]),
        "fixed_fields": [
            "semantics_hash",
            "fixture_fingerprint",
            "time_tolerance_minutes",
            "price_tolerance_bps",
            "min_cycles",
            "log_source",
        ],
        "log_source": log_source,
        "missing_prev_close_symbols": missing_prev,
    }
    comparability["config_hash"] = report.config_hash({
        "semantics_hash": comparability["semantics_hash"],
        "fixture_fingerprint": comparability["fixture_fingerprint"],
        "time_tolerance_minutes": tol,
        "price_tolerance_bps": price_tol,
        "min_cycles": comparability["min_cycles"],
        "log_source": log_source,
    })

    payload = report.assemble(
        run_id=_run_id(),
        generated_at=datetime.now(timezone.utc).isoformat(),
        log_source=log_source,
        semantics=semantics,
        logged_semantics=logged_semantics,
        manifest=manifest,
        ledger=ledger,
        value_assessment=value_assessment,
        attribution=attribution_result,
        alignment=alignment,
        comparability=comparability,
    )
    payload["summary"] = {
        "symbol_count": len(bars),
        "signal_count": current["summary"]["signal_count"],
        "closed_cycles": current["summary"]["closed_count"],
        "total_net_pct": current["summary"]["total_net_pct"],
        "ledger_match_rate": aggregate["total"]["match_rate"],
        "divergence_items": aggregate["total"]["divergent"],
        "one_sided_items": aggregate["total"]["one_sided"],
        "condition_coverage": aggregate["total"].get("condition_coverage"),
        "alignment_verdict": alignment["verdict"],
        "value_verdict": value_assessment["verdict"]["verdict"],
        "attribution_verdict": attribution_result["verdict"],
    }

    out_dir = Path(config["output_dir"])
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    ledger_path = out_dir / "ledger.jsonl"
    with ledger_path.open("w", encoding="utf-8") as fh:
        for symbol, rows in sorted(rows_by_symbol.items()):
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    payload["artifacts"] = {
        "report": str(report_path),
        "ledger": str(ledger_path),
    }
    return payload


def evaluate_naive(bars: Dict[str, Dict[str, Any]], semantics: Dict[str, Any],
                   prev_closes: Dict[str, float]) -> Dict[str, Any]:
    """用字面直译档位跑一次，作为价值评估的冻结基线。

    关键：与主实验共用同一份 prev_closes 与同一份 K 线，
    唯一受控变量是语义档位，否则 delta 不可归因。
    """
    naive_semantics = dict(semantics)
    naive_semantics.update(sem.NAIVE_PROFILE)
    naive_semantics["_hash"] = sem.semantics_hash(naive_semantics)
    return replay_all(bars, naive_semantics, prev_closes)