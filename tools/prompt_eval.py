#!/usr/bin/env python
"""提示词通过率评测（对齐团队路线大纲：20 条测试句）。

三种模式：

    # 1) 不联网：检查 20 条测试句的 Prompt 都能构造
    python tools/prompt_eval.py --dry-run

    # 2) 不联网：用「理想模型输出」回放 clean，检查规则自检是否 100%
    python tools/prompt_eval.py --offline

    # 3) 真实模型：需要 OpenAI 兼容 API Key，统计金额/类别/日期通过率
    set OPENAI_API_KEY=sk-xxx
    set OPENAI_BASE_URL=https://api.openai.com/v1
    set OPENAI_MODEL=<模型名>
    python tools/prompt_eval.py

说明：
- Key 只从环境变量读取，不写入仓库；
- 通过标准：ok 与预期一致；ok=True 时 amount/category/spent_at 三项全对；
- 报告写到 reports/prompt_eval_<时间戳>.json，README 里可以引用这个通过率。
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import prompts as p  # noqa: E402

NOW = datetime(2026, 11, 14, 19, 30, 0, tzinfo=timezone(timedelta(hours=8)))
CASES_PATH = os.path.join(ROOT, "tests", "cases", "text_cases.json")


def load_text_cases():
    with open(CASES_PATH, encoding="utf-8") as handle:
        return json.load(handle)["text_cases"]


def call_model(base_url, api_key, model, messages, *, temperature, timeout, use_json_mode):
    body = {"model": model, "messages": messages, "temperature": temperature}
    if use_json_mode:
        body["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"接口未返回 choices：{raw[:300]}")
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):  # 部分厂商返回分段内容
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content, data.get("usage")


def check(result, expected):
    if result["ok"] != expected["ok"]:
        return False
    if not expected["ok"]:
        return True
    data = result.get("data") or {}
    return (
        data.get("amount") == expected["amount"]
        and data.get("category") == expected["category"]
        and data.get("spent_at") == expected["spent_at"]
    )


def summarize(results, mode):
    total = len(results)
    passed = sum(1 for item in results if item["passed"])
    return {
        "mode": mode,
        "total": total,
        "passed": passed,
        "accuracy": round(passed / total, 4) if total else 0.0,
        "prompt_version": p.PROMPT_VERSION,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="提示词通过率评测（20 条测试句）")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    parser.add_argument(
        "--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", ""))
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--no-json-mode", action="store_true")
    parser.add_argument("--report-dir", default=os.path.join(ROOT, "reports"))
    parser.add_argument("--fail-under", type=float, default=0.0)
    args = parser.parse_args(argv)

    cases = load_text_cases()
    if args.limit > 0:
        cases = cases[: args.limit]

    if args.dry_run:
        for case in cases:
            messages = p.text_messages(case["text"], now=NOW)
            assert len(messages) == 2 and messages[0]["content"]
        print(f"[dry-run] {len(cases)} 条测试句的 Prompt 均构造成功。")
        return 0

    if args.offline:
        results = []
        for case in cases:
            raw = json.dumps(case["ideal"], ensure_ascii=False)
            result = p.clean(raw, source_text=case["text"], now=NOW)
            results.append(
                {
                    "id": case["id"],
                    "text": case["text"],
                    "passed": check(result, case["expected"]),
                    "result": result,
                }
            )
        report = {"meta": summarize(results, "offline-rule-selfcheck"), "results": results}
        passed = report["meta"]["passed"]
        print(f"[offline] 规则自检通过 {passed}/{len(results)}（不是模型效果，只验证 clean 规则）")
        if passed != len(results):
            for item in results:
                if not item["passed"]:
                    print(f"  FAIL {item['id']} {item['text']} -> {item['result']}")
            return 1
        return 0

    if not args.api_key:
        print(
            "未配置 OPENAI_API_KEY，已跳过真实模型评测。\n"
            "设置环境变量后再跑（Key 不要提交到仓库）：\n"
            "  set OPENAI_API_KEY=sk-xxx\n"
            "  set OPENAI_BASE_URL=https://api.openai.com/v1\n"
            "  set OPENAI_MODEL=<模型名>\n"
            "也可先跑不联网自检：python tools/prompt_eval.py --offline",
            file=sys.stderr,
        )
        return 0

    results = []
    for case in cases:
        messages = p.text_messages(case["text"], now=NOW)
        entry = {"id": case["id"], "text": case["text"]}
        begin = time.perf_counter()
        try:
            raw, usage = call_model(
                args.base_url,
                args.api_key,
                args.model,
                messages,
                temperature=args.temperature,
                timeout=args.timeout,
                use_json_mode=not args.no_json_mode,
            )
            entry["elapsed_ms"] = round((time.perf_counter() - begin) * 1000, 1)
            entry["usage"] = usage
            entry["raw_output"] = raw
            result = p.clean(raw, source_text=case["text"], now=NOW)
            entry["result"] = result
            entry["passed"] = check(result, case["expected"])
        except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, ValueError) as exc:
            entry["passed"] = False
            entry["error"] = f"{type(exc).__name__}: {exc}"
            result = None
        results.append(entry)
        flag = "PASS" if entry["passed"] else "FAIL"
        print(f"[{flag}] {case['text']}")

    meta = summarize(results, "live-model")
    meta.update(
        {
            "model": args.model,
            "base_url": args.base_url,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "temperature": args.temperature,
        }
    )
    os.makedirs(args.report_dir, exist_ok=True)
    report_path = os.path.join(
        args.report_dir, f"prompt_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump({"meta": meta, "results": results}, handle, ensure_ascii=False, indent=2)

    print(f"\n通过 {meta['passed']}/{meta['total']}，通过率 {meta['accuracy']:.1%}")
    print(f"报告：{report_path}")
    return 1 if meta["accuracy"] < args.fail_under else 0


if __name__ == "__main__":
    sys.exit(main())
