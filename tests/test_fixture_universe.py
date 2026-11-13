"""夹具标的池必须全期固定。

跨日持仓的前提是同一只股票在相邻交易日都有数据。若每天各自抽样，
池子天天变（实测相邻日重合度最低 18.6%），昨天买的今天不在样本里，
跨日逻辑形同虚设，T+1 相关结论也失去基础。
"""

from __future__ import annotations

import gzip
import json
import re
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BARS_DIR = REPO_ROOT / "fixtures" / "bars"


def _symbols_by_date():
    out = {}
    for path in sorted(BARS_DIR.glob("*.json*")):
        match = re.match(r"(\d{8})\.json", path.name)
        if not match:
            continue
        date = match.group(1)
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as fh:
            records = json.load(fh)
        out[date] = {r["symbol"] for r in records}
    return out


def test_fixture_universe_is_constant_across_dates():
    by_date = _symbols_by_date()
    if len(by_date) < 2:
        pytest.skip("单日夹具不涉及跨日持仓")

    dates = sorted(by_date)
    reference = by_date[dates[0]]
    for date in dates[1:]:
        diff = reference.symmetric_difference(by_date[date])
        assert not diff, (
            f"{date} 的标的池与 {dates[0]} 不一致，差异 {len(diff)} 只："
            f"{sorted(diff)[:5]}。多日夹具必须使用全期固定标的池，"
            "否则跨日持仓会无故中断。"
        )


def test_every_series_has_full_bars():
    """每只股票每天都应有完整的 240 根，不能有天缺数据。"""
    for path in sorted(BARS_DIR.glob("*.json*")):
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as fh:
            records = json.load(fh)
        counts = Counter(r["symbol"] for r in records)
        bad = {s: c for s, c in counts.items() if c != 240}
        assert not bad, f"{path.name} 有标的分时根数异常：{list(bad.items())[:5]}"


def test_bar_gzip_is_reproducible():
    """夹具压缩包必须可重现：gzip 头的 mtime 必须为 0。

    默认 `gzip.open(..., "wb")` 会把**当前时间**写进头部，同一份数据每次
    重建都得到不同字节流 → `fixture_fingerprint` 每次都变 →
    「冻结夹具」名不副实，`compare_baseline` 还会无故报不可比。
    """
    import struct

    offenders = []
    for path in sorted(BARS_DIR.glob("*.json.gz")):
        head = path.read_bytes()[:10]
        if head[:3] != b"\x1f\x8b\x08":
            offenders.append(f"{path.name}: 不是标准 gzip")
            continue
        mtime = struct.unpack("<I", head[4:8])[0]
        if mtime != 0:
            offenders.append(f"{path.name}: MTIME={mtime}（应为 0）")
    assert not offenders, "gzip 头带了时间戳，构建不可重现：\n" + "\n".join(offenders)


def test_manifest_describes_the_actual_fixtures():
    """`fixtures/manifest.json` 必须描述**实际存在**的整套夹具。

    这条来自一个真实缺陷：多日构建时 `main()` 把合并后的 manifest 只 print
    不落盘，而 `build()` 每构建一天都会覆盖写一次 manifest.json。结果是
    仓库里的 manifest 长期停留在「最后一天」：`bar_count: 72000`
    （实际 1,008,000）、`log_record_count: 0`（实际 34,590）、没有 `dates`。
    报告里的 `provenance.fixture_manifest` 直接引用它，等于对外错报夹具规模。
    """
    manifest_path = REPO_ROOT / "fixtures" / "manifest.json"
    if not manifest_path.exists():
        pytest.skip("没有 manifest.json")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    bar_files = sorted(BARS_DIR.glob("*.json*"))
    if not bar_files:
        pytest.skip("没有夹具 K 线")
    dates_on_disk = sorted(
        re.match(r"(\d{8})", p.name).group(1) for p in bar_files
    )

    actual_bars = 0
    for path in bar_files:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as fh:
            actual_bars += len(json.load(fh))

    log_files = sorted((REPO_ROOT / "fixtures" / "logs").glob("*.jsonl"))
    actual_logs = sum(
        sum(1 for line in p.open(encoding="utf-8") if line.strip())
        for p in log_files
    )

    problems = []
    if manifest.get("bar_count") != actual_bars:
        problems.append(f"bar_count: manifest={manifest.get('bar_count')} 实际={actual_bars}")
    if manifest.get("log_record_count") != actual_logs:
        problems.append(
            f"log_record_count: manifest={manifest.get('log_record_count')} 实际={actual_logs}"
        )
    if len(dates_on_disk) > 1:
        if manifest.get("dates") != dates_on_disk:
            problems.append(
                f"dates: manifest={manifest.get('dates')} 实际={dates_on_disk}"
            )
    assert not problems, (
        "manifest.json 与实际夹具不符（多日构建时合并结果未落盘？）：\n"
        + "\n".join(f"  {p}" for p in problems)
    )


def test_fixture_logs_match_current_replayer():
    """落盘日志必须与**当前代码**重放的结果一致。

    真实踩过的坑：修好 `bars_held` 重复累加缺陷后忘了重新生成夹具日志，
    于是 `fixtures/logs/` 里仍是旧代码的产物。对齐时表现为 30 条
    "无法归因"的退出差异（日志判 max_hold、重放判 stop_loss），
    归因被迫降级为 `multi_knob`。**不是语义分歧，是夹具过期**。

    日志只有 34,590 条，逐条比对成本可接受。
    """
    import json as _json

    from scripts import config as cfg
    from scripts import data_loader, log_synth, semantics as sem
    from scripts.run_eval import _load_prev_closes

    bars = data_loader.load_bars(REPO_ROOT / "fixtures" / "bars")
    if not bars:
        pytest.skip("没有 K 线夹具")
    prev = _load_prev_closes(REPO_ROOT / "fixtures" / "reference", list(bars))

    logged = dict(cfg.load_config()["semantics"])
    logged.update(sem.get_profile("jev_assumed"))
    fresh = log_synth.synthesize_logs(bars, logged, prev)

    disk = []
    for path in sorted((REPO_ROOT / "fixtures" / "logs").glob("*.jsonl")):
        disk += [_json.loads(line) for line in path.open(encoding="utf-8")
                 if line.strip()]

    def key(rec):
        return (rec.get("symbol"), str(rec.get("date")), rec.get("ts"),
                rec.get("kind"), rec.get("plan"))

    fresh_map = {key(r): r.get("exit_reason") for r in fresh if r.get("kind") == "plan"}
    disk_map = {key(r): r.get("exit_reason") for r in disk if r.get("kind") == "plan"}
    mismatched = [
        (k, disk_map.get(k), fresh_map.get(k))
        for k in set(fresh_map) | set(disk_map)
        if fresh_map.get(k) != disk_map.get(k)
    ]
    assert mismatched == [], (
        f"{len(mismatched)} 条 plan 记录的退出原因与当前重放不一致——"
        "夹具日志已过期，请重新运行 scripts/build_fixtures.py 生成日志。"
        f"样例：{mismatched[:3]}"
    )
