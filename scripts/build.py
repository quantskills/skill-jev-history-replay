"""标准入口 —— 实现 `run(input_data, config=None)` 契约。

input_data 支持两种形态：
    - dict：{"bars_dir": ..., "logs_dir": ..., "output_dir": ..., "semantics": {...}}
    - str ：K线目录路径（等价于 {"bars_dir": <str>}）

config 支持 `{"semantics": {...}, "time_tolerance_minutes": ...}`，
合并优先级：run 参数 > config > config/*.yaml > 内置默认值。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import config as cfg, semantics as sem  # noqa: E402
from scripts.run_eval import ReplayError, evaluate  # noqa: E402

_ALLOWED_KEYS = {
    "bars_dir",
    "logs_dir",
    "output_dir",
    "reference_path",
    "semantics",
    "run_attribution",
}


def validate_input(input_data: Any) -> Dict[str, Any]:
    """校验并规范化输入。缺字段/类型错误一律抛 ReplayError。"""
    if isinstance(input_data, str):
        if not input_data.strip():
            raise ReplayError(
                "empty_input", "input_data 不能为空字符串",
                hint="传入 K线目录路径或含 bars_dir 的 dict",
            )
        params: Dict[str, Any] = {"bars_dir": input_data}
    elif isinstance(input_data, dict):
        unknown = set(input_data) - _ALLOWED_KEYS
        if unknown:
            raise ReplayError(
                "unknown_field", f"未知字段：{sorted(unknown)}",
                hint=f"允许字段：{sorted(_ALLOWED_KEYS)}",
            )
        params = dict(input_data)
    else:
        raise ReplayError(
            "invalid_type",
            f"input_data 必须是 dict 或 str，收到 {type(input_data).__name__}",
        )

    bars_dir = params.get("bars_dir")
    if bars_dir is not None:
        if not isinstance(bars_dir, str):
            raise ReplayError("invalid_type", "bars_dir 必须是 str")
        if not Path(bars_dir).exists():
            raise ReplayError(
                "bars_dir_not_found", f"K线目录不存在：{bars_dir}",
                hint="先运行 scripts/fetch_data.py，或指向 fixtures/bars",
            )

    logs_dir = params.get("logs_dir")
    if logs_dir is not None and not isinstance(logs_dir, str):
        raise ReplayError("invalid_type", "logs_dir 必须是 str")

    semantics = params.get("semantics")
    if semantics is not None:
        if not isinstance(semantics, dict):
            raise ReplayError("invalid_type", "semantics 必须是 dict")
        problems = sem.validate_semantics({**cfg.REFERENCE_SEMANTICS, **semantics})
        if problems:
            raise ReplayError("invalid_semantics", "; ".join(problems))

    if "run_attribution" in params and not isinstance(params["run_attribution"], bool):
        raise ReplayError("invalid_type", "run_attribution 必须是 bool")

    return params


def run(input_data: Any, config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """执行对齐评测，返回报告 dict（同时把 report.json / ledger.jsonl 写入 output_dir）。

    Args:
        input_data: dict 或 K线目录路径
        config: 可选的配置覆盖（semantics / 容差 / 输出目录等）

    Returns:
        报告 dict，含 ledger / attribution / alignment_conclusion /
        value_assessment / applicability / comparability

    Raises:
        ReplayError: 输入校验失败或数据不足
    """
    params = validate_input(input_data)
    if config is not None and not isinstance(config, dict):
        raise ReplayError("invalid_type", "config 必须是 dict 或 None")
    config = dict(config or {})

    semantics_override = dict(params.get("semantics") or {})
    semantics_override.update(config.get("semantics") or {})

    config_overrides = {k: v for k, v in config.items() if k != "semantics"}

    return evaluate(
        bars_dir=params.get("bars_dir"),
        logs_dir=params.get("logs_dir"),
        output_dir=params.get("output_dir") or config_overrides.pop("output_dir", None),
        reference_path=params.get("reference_path"),
        semantics_override=semantics_override or None,
        config_overrides=config_overrides,
        run_attribution=bool(params.get("run_attribution", True)),
    )


if __name__ == "__main__":
    try:
        result = run({})
    except ReplayError as exc:
        print(json.dumps(
            {"ok": False, "error": {"code": exc.code, "message": exc.message, "hint": exc.hint}},
            ensure_ascii=False, indent=2,
        ))
        sys.exit(2)
    print(json.dumps({"ok": True, "summary": result["summary"],
                      "artifacts": result["artifacts"]},
                     ensure_ascii=False, indent=2))