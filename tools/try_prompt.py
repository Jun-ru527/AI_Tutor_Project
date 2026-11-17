#!/usr/bin/env python
"""手工验证 prompts.py 的小工具（不需要 API Key）。

两种用法：

1) 只看会发给模型的消息，复制到任意对话模型里试：

    py tools/try_prompt.py "昨天晚上吃火锅花了128元"
    py tools/try_prompt.py "昨天晚上吃火锅花了128元" --full   # 连 system 一起打印

2) 把模型返回的 JSON 传回来，验证 clean 能不能正确清洗：

    py tools/try_prompt.py "午饭25" --raw '{"is_bill":true,"amount":25,"category":"餐饮","spent_at":"2026-11-14","merchant":"","note":""}'
    py tools/try_prompt.py "午饭25" --raw-file answer.txt
    Get-Content answer.txt -Raw | py tools/try_prompt.py "午饭25" --raw -

3) 一句话多笔时，用 --many 调用 clean_many()，data 会返回列表：

    py tools/try_prompt.py "打车18，奶茶16.5" --many --raw-file answer.txt

退出码：clean 成功为 0，失败为 1，方便脚本串联。
"""

import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import prompts  # noqa: E402


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="手工验证 text_messages / clean")
    parser.add_argument("text", help="用户原话，例如：午饭25")
    parser.add_argument("--raw", default=None, help="模型返回的 JSON；传 - 表示从 stdin 读取")
    parser.add_argument("--raw-file", default=None, help="从文件读取模型返回的 JSON")
    parser.add_argument("--full", action="store_true", help="打印完整 system prompt")
    parser.add_argument("--many", action="store_true", help="用 clean_many() 返回全部记录")
    parser.add_argument("--now", default=None, help="固定当前时间，ISO 格式")
    args = parser.parse_args(argv)

    now = None
    if args.now:
        try:
            now = datetime.fromisoformat(args.now)
        except ValueError:
            print(f"--now 格式不对：{args.now!r}，示例：2026-11-14T19:30:00+08:00", file=sys.stderr)
            return 2

    messages = prompts.text_messages(args.text, now=now)
    system = messages[0]["content"]
    user = messages[1]["content"]

    if args.full:
        print("=" * 20, "SYSTEM", "=" * 20)
        print(system)
    else:
        print(f"[system] {len(system)} 字（加 --full 查看全文）")
    print("=" * 20, "USER", "=" * 20)
    print(user)

    raw = args.raw
    if args.raw_file:
        try:
            with open(args.raw_file, encoding="utf-8") as handle:
                raw = handle.read()
        except OSError as exc:
            print(f"读取 --raw-file 失败：{exc}", file=sys.stderr)
            return 2
    if raw == "-":
        raw = sys.stdin.read()

    if raw is None:
        print("\n下一步：把 system + user 发给任意对话模型，要求它只输出 JSON；")
        print("再用 --raw '<JSON>' 或 --raw-file answer.txt 传回来验证 clean。")
        return 0

    if args.many:
        result = prompts.clean_many(raw, source_text=args.text, now=now)
    else:
        result = prompts.clean(raw, source_text=args.text, now=now)
    print("=" * 20, "CLEAN" + ("_MANY" if args.many else ""), "=" * 20)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if (
        not result["ok"]
        and result["msg"] == prompts.MSG_BAD_JSON
        and raw
        and '"' not in raw
    ):
        print(
            "提示：JSON 里的双引号可能被 PowerShell 吞掉了。"
            "请改用 --raw-file answer.txt，或用管道：Get-Content answer.txt -Raw | ... --raw -",
            file=sys.stderr,
        )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
