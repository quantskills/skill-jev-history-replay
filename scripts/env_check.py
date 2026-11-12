"""环境自检：报告缺失依赖与缺失数据，输出结构化 JSON。

设计原则：评测本身不需要 panda_data，因此缺它只报 warn 不报 blocked。
真正 blocked 的只有「夹具缺失」——那是评测无法进行的原因。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]


def check() -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    python_ok = sys.version_info >= (3, 10)
    checks.append({
        "name": "python",
        "status": "pass" if python_ok else "blocked",
        "detail": sys.version.split()[0],
        "hint": "" if python_ok else "需要 Python >= 3.10",
    })

    bars_dir = REPO_ROOT / "fixtures" / "bars"
    bar_files = _data_files(bars_dir)
    checks.append({
        "name": "fixtures_bars",
        "status": "pass" if bar_files else "blocked",
        "detail": [p.name for p in bar_files],
        "hint": "" if bar_files else "运行 scripts/build_fixtures.py（需凭证）或放入 K 线 JSON",
    })

    logs_dir = REPO_ROOT / "fixtures" / "logs"
    log_files = _data_files(logs_dir)
    checks.append({
        "name": "fixtures_logs",
        "status": "pass" if log_files else "warn",
        "detail": [p.name for p in log_files],
        "hint": "" if log_files else "缺日志时将走合成模式（结论只能是 inconclusive）",
    })

    ref_dir = REPO_ROOT / "fixtures" / "reference"
    ref_files = sorted(ref_dir.glob("*.json")) if ref_dir.exists() else []
    checks.append({
        "name": "fixtures_reference",
        "status": "pass" if ref_files else "warn",
        "detail": [p.name for p in ref_files],
        "hint": "" if ref_files else "缺前收价时回退为当日首根开盘价（已在报告中标注）",
    })

    try:
        import panda_data  # noqa: F401
        panda_status = "pass"
        panda_detail = "已安装（仅再生夹具时需要）"
    except ImportError:
        panda_status = "warn"
        panda_detail = "未安装（评测不需要）"
    checks.append({
        "name": "panda_data",
        "status": panda_status,
        "detail": panda_detail,
        "hint": "pip install -r requirements.txt" if panda_status == "warn" else "",
    })

    try:
        import yaml  # noqa: F401
        yaml_status = "pass"
        yaml_detail = "已安装"
    except ImportError:
        yaml_status = "warn"
        yaml_detail = "未安装，将回退到内置默认配置"
    checks.append({
        "name": "pyyaml",
        "status": yaml_status,
        "detail": yaml_detail,
        "hint": "pip install -r requirements-dev.txt" if yaml_status == "warn" else "",
    })

    blocked = [c for c in checks if c["status"] == "blocked"]
    warn = [c for c in checks if c["status"] == "warn"]
    return {
        "ok": not blocked,
        "summary": {
            "total": len(checks),
            "pass": sum(1 for c in checks if c["status"] == "pass"),
            "warn": len(warn),
            "blocked": len(blocked),
        },
        "checks": checks,
    }


def _data_files(base: Path) -> List[Path]:
    if not base.exists():
        return []
    return [
        p for p in sorted(base.iterdir())
        if p.is_file() and p.name.endswith((".json", ".jsonl", ".json.gz", ".jsonl.gz"))
    ]


def main(argv: List[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="JEV replay skill environment self-check")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出（默认也是 JSON）")
    args = parser.parse_args(argv)
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())