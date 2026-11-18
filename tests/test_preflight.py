"""前置检查契约的反向守卫（对应 SKILL.md 同名小节）。

本技能运行在 QuantStudio 环境：数据与模型都由宿主提供，脚本只读本地落盘 JSON。
所以 SKILL.md 必须先要求一次前置检查，且不得再出现任何「技能自己准备数据」的符号。
少了这条约束，收件人会直接跳到对齐或回放，把「没权限」当成「没行情」继续算，
或者把合成日志当成 JEV 实际日志——结论静默失真，而报告看上去一切正常。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "SKILL.md"
TEXT = SKILL.read_text(encoding="utf-8")

# 前置检查要覆盖的宿主能力：MCP 会话、权限探针、依赖、不过就停。
REQUIRED = ("QuantStudio", "auth_status", "reauth_required",
            "data_permission_required", "import pytest")

# 扫描范围：读者会照抄的文档，不含 CHANGELOG（历史记述）与测试自身。
DOC_FILES = ("SKILL.md", "README.md", "README.en.md", "INSTALL.md")
DOC_DIRS = ("references", "agents")


def _preflight_block() -> tuple[int, str]:
    i = TEXT.find("## 前置检查")
    assert i >= 0, "SKILL.md 必须有前置检查小节"
    j = TEXT.find("\n## ", i + 5)
    return i, TEXT[i:j if j > 0 else len(TEXT)]


def test_preflight_section_exists_and_covers_host_capabilities():
    """小节必须真的列出四项前提，而不是只有一句「请先检查环境」。"""
    _, block = _preflight_block()
    for need in REQUIRED:
        assert need in block, f"前置检查缺少 {need}"
    assert "标准库" in block, "必须写明脚本只用标准库"
    assert "宿主" in block, "必须写明运行环境与数据由宿主（QuantStudio）提供"
    assert "停止" in block and ("缺" in block or "报告" in block), \
        "必须写明不过就停并报告缺什么"


def test_preflight_precedes_everything_executable():
    """前置检查必须排在所有可执行流程之前，否则等于没有。"""
    i, _ = _preflight_block()
    for later in ("python3 scripts/", "```bash", "```python"):
        k = TEXT.find(later)
        assert k == -1 or k > i, f"{later} 出现在前置检查之前"


def test_preflight_splits_refetch_from_offline_replay():
    """两条线路的阻塞语义必须写清。

    一律阻塞会让无网络的冷克隆跑不起来；一律放行会让收件人把三年前落盘的
    夹具当成当日数据下结论。
    """
    _, block = _preflight_block()
    assert "阻塞项" in block, "必须写明取新数据时 MCP 是阻塞项"
    assert "不是阻塞项" in block, "必须写明离线回放时 MCP 不是阻塞项"
    assert "落盘日期" in block, "离线线路必须要求标注数据的落盘日期"
    assert "inconclusive" in block, "缺 JEV 日志时必须降级为 inconclusive，不得当作对齐通过"


def test_docs_never_describe_a_data_fetching_client():
    """文档里不得再出现取数组件（旧口径称 SDK）或凭证符号，取数只有 MCP 一条路。"""
    banned = ("SDK", "import panda" + "_data",
              "from panda" + "_data", "PANDA" + "_DATA_", "panda" + "-data",
              "init" + "_token")
    paths = [REPO_ROOT / rel for rel in DOC_FILES]
    for sub in DOC_DIRS:
        paths += sorted((REPO_ROOT / sub).glob("*"))
    hits = []
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in banned:
            if token in text:
                hits.append(f"{path.name}: {token}")
    assert hits == [], "文档仍描述取数组件/凭证通道：" + "；".join(hits)
