"""PandaData MCP 取数结果的离线解析器（纯标准库）。

本 skill 的取数路径是：**阅读 skill 的 AI 通过 MCP 工具
`mcp__pandadata__call_pandadata` 取回数据并落盘**，脚本只消费落盘的 JSON。
脚本自身不联网、没有账号密码、没有 token、没有 base_url。

MCP 工具的返回信封：

    {"ok": true, "method": "get_stock_min", "params": {...},
     "result": ..., "request_id": "..."}

失败时 `ok=false`，`result` 位置是错误信息。`result` 有两种形态：

1. 表格（DataFrame）：

       {"type": "dataframe",
        "columns": ["symbol", "datetime", ...],
        "rows": [[...], ...],
        "row_count": 180, "total_rows": 240,
        "truncated": true, "truncation_reasons": ["byte_limit"]}

   **会被截断**：实测 240 行分钟线只回 180 行。截断时本模块直接抛
   `MCPDataError("truncated_result")`，绝不把不完整的表当成完整数据。

2. 普通列表 / 字典：例如 `get_trade_list` 返回
   `[{"date": "20251110", "symbol": "000001.SZ"}, ...]`，
   `get_prev_trade_date` 返回 `{"date": "20251107"}`。

落盘目录约定（`--from-mcp <dir>`）：

    <dir>/<date>/get_stock_min.json          # 分钟线，必须是**窄日期区间**一次一份
    <dir>/<date>/get_stock_daily.json        # 日线（含前一交易日的行）
    <dir>/<date>/get_prev_trade_date.json    # 前一交易日
    <dir>/<date>/get_trade_list.json         # 当日可交易标的池（可选）
    <dir>/get_st_list.json                   # ST 名单（可选，整段日期一次）
    <dir>/get_suspended_list.json            # 停牌名单（可选，整段日期一次）

每个文件可以是完整信封，也可以直接是 `result`（便于手工准备夹具）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

# 本 skill 用到的 MCP 方法名（与 references/data_access.md 的对照表一致）。
METHODS = (
    "get_stock_min",
    "get_stock_daily",
    "get_prev_trade_date",
    "get_trade_list",
    "get_st_list",
    "get_suspended_list",
)

# 各方法的必需列。缺列必须报错——否则下游会 KeyError 到一个更难看的位置。
MIN_COLUMNS = ("symbol", "datetime", "open", "high", "low", "close",
               "volume", "amount")
DAILY_COLUMNS = ("symbol", "date", "open", "high", "low", "close")
TRADE_LIST_COLUMNS = ("date", "symbol")
ST_COLUMNS = ("symbol", "date", "is_st")
SUSPENDED_COLUMNS = ("symbol", "date", "is_suspended")


class MCPDataError(RuntimeError):
    """MCP 取数结果不可用（缺文件 / 信封错误 / 截断 / 缺列）。

    与本 skill 其它模块的 `FetchError` / `LoadError` 同风格：
    `code` 供程序分支，`message` 给人看，`hint` 给出可操作下一步。
    """

    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def norm_date(value: Any) -> str:
    """把 `20261112` / `2026-11-12` / `2026/11/12` 统一成 `YYYYMMDD`。"""
    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    raise MCPDataError(
        "invalid_date",
        f"无法解析日期：{value!r}",
        hint="MCP 返回的日期应为 YYYYMMDD 或 YYYY-MM-DD",
    )


def load_file(path: Path) -> Dict[str, Any]:
    """读取一个落盘文件，返回信封（或把裸 result 包成信封）。"""
    path = Path(path)
    if not path.is_file():
        raise MCPDataError(
            "missing_mcp_file",
            f"缺少 MCP 取数文件：{path}",
            hint=("按 references/data_access.md 的目录约定，"
                  "让 agent 先调用 mcp__pandadata__call_pandadata 落盘"),
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MCPDataError(
            "invalid_mcp_json",
            f"{path.name} 不是合法 JSON：{exc}",
            hint="确认落盘的是 MCP 工具返回的原始 JSON，而不是日志或截断的片段",
        ) from exc
    if not isinstance(payload, dict):
        raise MCPDataError(
            "invalid_envelope",
            f"{path.name} 顶层不是对象：{type(payload).__name__}",
            hint="顶层应是 call_pandadata 的信封，或直接是 result 内容",
        )
    if "ok" in payload:
        return payload
    if "result" in payload:
        return {"ok": True, "result": payload["result"]}
    # 裸 result：列表（如 get_trade_list）会被包进 dict，这里用哨兵保存
    return {"ok": True, "result": payload, "_bare": True}


def unwrap(envelope: Dict[str, Any], *, method: str = "",
           path: Optional[Path] = None) -> Any:
    """校验信封的 `ok` 并返回 `result`。"""
    where = f"（{Path(path).name}）" if path else ""
    if not envelope.get("ok", False):
        error = envelope.get("error") or envelope.get("result") or envelope
        code = "mcp_call_failed"
        hint = "在 agent 侧重试该 MCP 调用；OAuth 失效时先跑 mcp__pandadata__auth_status"
        if isinstance(error, dict):
            code = str(error.get("code") or code)
            message = str(error.get("message") or error)
            hint = str(error.get("hint") or hint)
        else:
            message = f"{method or 'MCP'} 调用失败{where}：{error}"
        raise MCPDataError(code, message, hint=hint)
    if "result" not in envelope:
        raise MCPDataError(
            "invalid_envelope",
            f"信封缺少 result 字段{where}",
            hint="把 call_pandadata 的完整返回原样落盘",
        )
    return envelope["result"]


def is_dataframe(result: Any) -> bool:
    return isinstance(result, dict) and result.get("type") == "dataframe"


def check_complete(result: Any, *, method: str = "",
                   path: Optional[Path] = None) -> None:
    """表格结果必须是完整的。截断时报错，而不是静默当成全量。"""
    if not is_dataframe(result):
        return
    where = f"（{Path(path).name}）" if path else ""
    reasons = result.get("truncation_reasons") or []
    if result.get("truncated"):
        raise MCPDataError(
            "truncated_result",
            (f"{method or 'MCP'} 返回被截断{where}："
             f"row_count={result.get('row_count')}，"
             f"total_rows={result.get('total_rows')}，reasons={reasons}"),
            hint=("不要把它当成完整数据。按更窄的日期区间（单日或单标的）"
                  "分批调用，再分别落盘；分钟线一次取一天、少量标的"),
        )
    row_count = result.get("row_count")
    total_rows = result.get("total_rows")
    if (isinstance(row_count, int) and isinstance(total_rows, int)
            and total_rows > row_count):
        raise MCPDataError(
            "truncated_result",
            (f"{method or 'MCP'} 行数不一致{where}："
             f"row_count={row_count} < total_rows={total_rows}"
             "（未标 truncated，但数据仍不完整）"),
            hint="按更窄的日期区间分批取数",
        )


def to_records(result: Any, *, method: str = "",
               required: Sequence[str] = (),
               path: Optional[Path] = None,
               allow_empty: bool = False) -> List[Dict[str, Any]]:
    """把两种形态的 result 统一成 `[{列名: 值}]`。

    - DataFrame 形态：校验截断、缺列、行宽；
    - 列表形态：每项必须是对象，且含必需列。
    """
    where = f"（{Path(path).name}）" if path else ""
    check_complete(result, method=method, path=path)

    if is_dataframe(result):
        columns = result.get("columns") or []
        rows = result.get("rows") or []
        if not columns:
            raise MCPDataError(
                "missing_columns",
                f"{method or 'MCP'} 的 DataFrame 结果没有 columns{where}",
                hint="重新调用并落盘完整信封（不要只存 rows）",
            )
        missing = [c for c in required if c not in columns]
        if missing:
            raise MCPDataError(
                "missing_columns",
                f"{method or 'MCP'} 缺少必需列：{missing}；实际列：{columns}{where}",
                hint="调用时显式传 fields=[...]，或在文档里核对列名",
            )
        records: List[Dict[str, Any]] = []
        for index, row in enumerate(rows):
            if isinstance(row, dict):
                records.append(dict(row))
            elif isinstance(row, (list, tuple)):
                if len(row) != len(columns):
                    raise MCPDataError(
                        "ragged_rows",
                        (f"{method or 'MCP'} 第 {index} 行宽度 {len(row)} "
                         f"与 columns 数 {len(columns)} 不符{where}"),
                        hint="落盘文件可能被手工改过；重新取数",
                    )
                records.append(dict(zip(columns, row)))
            else:
                raise MCPDataError(
                    "invalid_rows",
                    f"{method or 'MCP'} 第 {index} 行不是列表或对象{where}",
                    hint="重新落盘 MCP 原始返回",
                )
    elif isinstance(result, list):
        if result and not all(isinstance(item, dict) for item in result):
            raise MCPDataError(
                "invalid_rows",
                f"{method or 'MCP'} 的列表结果不是对象数组{where}",
                hint="重新落盘 MCP 原始返回",
            )
        missing = [c for c in required
                   if result and any(c not in item for item in result)]
        if missing:
            raise MCPDataError(
                "missing_columns",
                f"{method or 'MCP'} 的列表结果缺少字段：{missing}{where}",
                hint="核对方法返回字段，不要手工裁剪",
            )
        records = [dict(item) for item in result]
    else:
        raise MCPDataError(
            "unsupported_result",
            f"{method or 'MCP'} 的 result 既不是表格也不是列表{where}",
            hint="把 call_pandadata 的完整返回原样落盘",
        )

    if not records and not allow_empty:
        raise MCPDataError(
            "no_data",
            f"{method or 'MCP'} 返回空表{where}",
            hint="确认是否为交易日；非交易日返回空表属于正常，可显式允许为空",
        )
    return records


def scalar_date(result: Any, *, method: str = "get_prev_trade_date",
                path: Optional[Path] = None) -> str:
    """取单值日期结果，如 `{"date": "20251107"}` 或裸字符串。"""
    if isinstance(result, dict):
        if "date" not in result:
            raise MCPDataError(
                "missing_columns",
                f"{method} 结果缺少 date 字段{('（%s）' % Path(path).name) if path else ''}",
                hint="直接把 MCP 返回的字典落盘，不要只保留值",
            )
        return norm_date(result["date"])
    if isinstance(result, (str, int)):
        return norm_date(result)
    raise MCPDataError(
        "unsupported_result",
        f"{method} 结果应为 {{'date': 'YYYYMMDD'}}，实际 {type(result).__name__}",
        hint="把 call_pandadata 的完整返回原样落盘",
    )


class MCPSource:
    """落盘 MCP 取数结果的目录封装。

    查找顺序（按方法、按日期）：
      1. `<root>/<date>/<method>.json`
      2. `<root>/<method>.<date>.json`
      3. `<root>/<method>.json`
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"MCPSource({self.root})"

    def path_for(self, method: str, date: Optional[str] = None) -> Optional[Path]:
        if method not in METHODS:
            raise MCPDataError(
                "unknown_method", f"未知的 MCP 方法：{method}",
                hint=f"可用方法：{list(METHODS)}",
            )
        candidates: List[Path] = []
        if date:
            day = norm_date(date)
            candidates.append(self.root / day / f"{method}.json")
            candidates.append(self.root / f"{method}.{day}.json")
        candidates.append(self.root / f"{method}.json")
        for path in candidates:
            if path.is_file():
                return path
        return None

    def has(self, method: str, date: Optional[str] = None) -> bool:
        return self.path_for(method, date) is not None

    def result(self, method: str, date: Optional[str] = None) -> Any:
        path = self.path_for(method, date)
        if path is None:
            raise MCPDataError(
                "missing_mcp_file",
                f"缺少 {method} 的 MCP 取数文件（date={date}，目录 {self.root}）",
                hint=("让 agent 先调用 mcp__pandadata__call_pandadata，"
                      "并按 references/data_access.md 的路径落盘"),
            )
        return unwrap(load_file(path), method=method, path=path)

    def dataframe(self, method: str, *, date: Optional[str] = None,
                  required: Sequence[str] = (),
                  allow_empty: bool = False) -> List[Dict[str, Any]]:
        path = self.path_for(method, date)
        if path is None:
            raise MCPDataError(
                "missing_mcp_file",
                f"缺少 {method} 的 MCP 取数文件（date={date}，目录 {self.root}）",
                hint=("让 agent 先调用 mcp__pandadata__call_pandadata，"
                      "并按 references/data_access.md 的路径落盘"),
            )
        result = unwrap(load_file(path), method=method, path=path)
        return to_records(result, method=method, required=required,
                          path=path, allow_empty=allow_empty)

    def prev_trade_date(self, date: str, *, required: bool = False
                        ) -> Optional[str]:
        path = self.path_for("get_prev_trade_date", date)
        if path is None:
            if required:
                raise MCPDataError(
                    "missing_mcp_file",
                    f"缺少 get_prev_trade_date 的 MCP 取数文件（date={date}）",
                    hint="调用 get_prev_trade_date(date=..., exchange='SH', n=1) 并落盘",
                )
            return None
        result = unwrap(load_file(path), method="get_prev_trade_date", path=path)
        return scalar_date(result, path=path)

    def symbols(self, method: str = "get_trade_list",
                date: Optional[str] = None) -> Set[str]:
        """从列表形态结果里取 symbol 集合。"""
        records = self.dataframe(method, date=date,
                                 required=TRADE_LIST_COLUMNS)
        return {str(row["symbol"]) for row in records}

    def available_methods(self) -> List[str]:
        found = []
        for method in METHODS:
            if self.has(method):
                found.append(method)
            elif self.root.is_dir() and any(
                    (p / f"{method}.json").is_file()
                    for p in self.root.iterdir() if p.is_dir()):
                found.append(method)
        return found
