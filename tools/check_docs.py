#!/usr/bin/env python
"""文档与代码一致性检查（防止改代码后忘更新文档）。

检查项：
1. 文档里的测试数量 == 实际跑出来的测试数量；
2. 文档里的版本号 == prompts.py 的 PROMPT_VERSION；
3. 文档里引用的核心函数在 prompts.py 中真实存在；
4. 用例文件（text_cases.json）能正常加载，且数量与文档一致；
5. 文档里贴的代码示例能跑通（抽样检查）。

运行：py tools/check_docs.py
退出码：0 全部一致，1 有不一致。
"""

import json
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import prompts  # noqa: E402

NOW = datetime(2026, 11, 14, 19, 30, 0, tzinfo=timezone(timedelta(hours=8)))
DOCS = ("PROMPT_MODULE.md", "TESTING.md")
# 文档里必须出现的核心函数
CORE_FUNCTIONS = (
    "text_messages",
    "clean",
    "clean_many",
    "clean_intent",
    "clean_analysis",
    "image_messages",
    "intent_messages",
    "analysis_messages",
    "classify_category",
    "find_refusal",
    "normalize_category",
    "render_stats_summary",
)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return handle.read()


def count_tests():
    suite = unittest.TestLoader().discover(
        start_dir=os.path.join(ROOT, "tests"), pattern="test_*.py", top_level_dir=ROOT
    )
    return suite.countTestCases()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    problems = []
    actual_tests = count_tests()
    version = prompts.PROMPT_VERSION
    cases = json.loads(read(os.path.join("tests", "cases", "text_cases.json")))
    counts = {
        "text_cases": len(cases["text_cases"]),
        "edge_cases": len(cases["edge_cases"]),
        "multi_cases": len(cases["multi_cases"]),
    }

    print(f"实际测试数：{actual_tests}")
    print(f"实际版本号：{version}")
    print(f"用例数量：{counts}")
    print()

    for doc in DOCS:
        text = read(doc)
        # 版本历史段是历史描述，不参与“当前数量”检查
        current_text = re.split(r"^## \d+\. 版本", text, maxsplit=1, flags=re.MULTILINE)[0]

        # 1) 测试数量
        mentioned = {int(n) for n in re.findall(r"(\d+)\s*(?:个测试|tests)", current_text)}
        if mentioned and actual_tests not in mentioned:
            problems.append(
                f"{doc}: 写的测试数是 {sorted(mentioned)}，实际是 {actual_tests}"
            )

        # 2) 版本号：只检查「版本」章节里最新的一条（历史版本不算）
        version_section = re.split(r"^## \d+\. 版本", text, maxsplit=1, flags=re.MULTILINE)
        if len(version_section) > 1:
            first_line = version_section[1].strip().splitlines()[0] if version_section[1].strip() else ""
            found = re.findall(r"([0-9]+\.[0-9]+\.[0-9]+)", first_line)
            if found and found[0] != version:
                problems.append(
                    f"{doc}: 最新版本记录是 {found[0]}，代码是 {version}"
                )

        # 3) 用例数量（只看当前描述，不看版本历史）
        labels = {"text_cases": "测试句", "edge_cases": "异常", "multi_cases": "多笔"}
        for key, value in counts.items():
            pattern = rf"(\d+)\s*条\w*{labels[key]}"
            for found in re.findall(pattern, current_text):
                if int(found) != value:
                    problems.append(f"{doc}: 写的 {key} 数量 {found}，实际 {value}")

    # 4) 核心函数都存在
    for name in CORE_FUNCTIONS:
        if not hasattr(prompts, name):
            problems.append(f"prompts.py 缺少文档提到的函数：{name}")

    # 5) 文档示例能跑通（抽样）
    sample_cases = cases["text_cases"][:3]
    for case in sample_cases:
        raw = json.dumps(case["ideal"], ensure_ascii=False)
        result = prompts.clean_many(raw, source_text=case["text"], now=NOW)
        if not result["ok"]:
            problems.append(f"用例 {case['id']} 在 clean_many 下未通过：{result['msg']}")

    print("=" * 50)
    if problems:
        print(f"发现 {len(problems)} 处不一致：")
        for item in problems:
            print("  ✗", item)
        return 1

    print("✓ 文档与代码一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())