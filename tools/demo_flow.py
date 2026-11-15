#!/usr/bin/env python
"""演示 prompts.py 到底在防什么（不联网、不需要 API Key）。

注意：下面的「模型回答」是模拟的，用来模拟一个会犯错的模型；
      clean_many() 的校验、SQLite 入库、查询都是真实执行的。
      接真模型时，只需把 MOCK_MODEL[text] 换成 call_model(messages) 的返回值。

运行：py tools/demo_flow.py
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import prompts  # noqa: E402

NOW = datetime(2026, 11, 14, 19, 30, 0, tzinfo=timezone(timedelta(hours=8)))

# 模拟一个「会犯错」的模型：对「今天打车」编了 30 元，对「两百多」猜了 200。
MOCK_MODEL = {
    "午饭25": '[{"is_bill":true,"type":"支出","amount":25,"category":"餐饮","spent_at":"2026-11-14","merchant":"","note":""}]',
    "昨天晚上吃火锅花了128元": '[{"is_bill":true,"type":"支出","amount":128,"category":"餐饮","spent_at":"2026-11-13","merchant":"","note":"晚上吃火锅"}]',
    "打车18，奶茶16.5": '[{"is_bill":true,"type":"支出","amount":18,"category":"交通","spent_at":"2026-11-14","merchant":"","note":"打车"},{"is_bill":true,"type":"支出","amount":16.5,"category":"餐饮","spent_at":"2026-11-14","merchant":"","note":"奶茶"}]',
    "今天发工资8000": '[{"is_bill":true,"type":"收入","amount":8000,"category":"其他","spent_at":"2026-11-14","merchant":"公司","note":"工资"}]',
    "今天打车": '[{"is_bill":true,"type":"支出","amount":30,"category":"交通","spent_at":"2026-11-14","merchant":"","note":""}]',
    "买衣服花了两百多": '[{"is_bill":true,"type":"支出","amount":200,"category":"购物","spent_at":"2026-11-14","merchant":"","note":""}]',
    "帮我找个贷款口子": '[{"is_bill":true,"type":"支出","amount":null,"category":null,"spent_at":"","merchant":"","note":""}]',
}

CASES = list(MOCK_MODEL.keys())


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, "
        "category TEXT, spent_at TEXT, merchant TEXT, note TEXT, type TEXT)"
    )

    print("=" * 64)
    print("AI 记账助手：一句话 → 六字段 → 入库（prompts.py 演示）")
    print("=" * 64)

    saved = 0
    rejected = 0
    for text in CASES:
        raw = MOCK_MODEL[text]
        result = prompts.clean_many(raw, source_text=text, now=NOW)

        messages = prompts.text_messages(text, now=NOW)
        print(f"\n输入：{text}")
        print(f"  发给模型：system {len(messages[0]['content'])} 字 / user {len(messages[1]['content'])} 字")

        if result["ok"]:
            for bill in result["data"]:
                conn.execute(
                    "INSERT INTO records (amount, category, spent_at, merchant, note, type) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        bill["amount"],
                        bill["category"],
                        bill["spent_at"],
                        bill["merchant"],
                        bill["note"],
                        bill["type"],
                    ),
                )
                saved += 1
                print(
                    f"  clean：ok=True → 草稿卡：[{bill['type']}] {bill['category']} | "
                    f"{bill['amount']:g} 元 | {bill['spent_at']}"
                )
            print(f"  → 写入数据库 {len(result['data'])} 笔")
        else:
            rejected += 1
            print("  clean：ok=False → 未入库")
            print(f"  → 提示用户：{result['msg']}")

    print("\n" + "=" * 64)
    print("账本明细（只包含真正通过校验的记录）")
    print("=" * 64)
    rows = conn.execute(
        "SELECT id, spent_at, type, category, amount, note FROM records ORDER BY id"
    ).fetchall()
    for row in rows:
        print(f"  #{row[0]}  {row[1]}  [{row[2]}]  {row[3]}  {row[4]:g} 元  {row[5] or ''}")

    expense = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM records WHERE type = '支出'"
    ).fetchone()[0]
    income = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM records WHERE type = '收入'"
    ).fetchone()[0]
    dining = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM records WHERE category = '餐饮' AND type = '支出'"
    ).fetchone()[0]
    print(f"\n  支出合计：{expense:g} 元（其中餐饮 {dining:g} 元）")
    print(f"  收入合计：{income:g} 元")
    print(f"  结余：{expense - income:g} 元")
    print("  ↑ 注意：支出/收入是分开统计的，工资 8000 不会被算进「花了多少」")

    print("\n" + "=" * 64)
    print(f"{len(CASES)} 句输入：{saved} 笔入账，{rejected} 句被拦下。")
    print("如果直接把模型输出入库：")
    print("  ·「今天打车」会凭空多出 30 元支出")
    print("  ·「买衣服两百多」会被写成 200 元，用户没说过这个数")
    print("  ·「工资 8000」会被当成支出，月底总额全错")
    print("  ·「贷款口子」会被当成正常请求处理")
    print("这些就是 prompts.py 在真实 App 里挡掉的东西。")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())