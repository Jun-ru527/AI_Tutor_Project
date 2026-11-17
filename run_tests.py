"""一键测试入口（给 PyCharm 用）。

用法：
1. 在 PyCharm 左侧项目树里右键这个文件 -> Run 'run_tests'；
2. 或在底部 Terminal 里执行：py run_tests.py

它会自动找到 tests/ 下的全部测试并跑完，最后打印「全部通过」或失败数量。
不需要配置参数，也不依赖当前工作目录。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    print(f"项目目录：{ROOT}")
    print(f"Python：{sys.version.split()[0]}  ({sys.executable})\n")

    suite = unittest.TestLoader().discover(
        start_dir=os.path.join(ROOT, "tests"),
        pattern="test_*.py",
        top_level_dir=ROOT,
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    print("\n" + "=" * 50)
    if result.wasSuccessful():
        print(f"全部通过：{result.testsRun} 个测试，0 失败。")
        print("说明：这只验证 Prompt 模块的规则，真实模型效果要配置 API Key 后跑 tools/prompt_eval.py。")
        return 0
    print(
        f"有失败：共 {result.testsRun} 个测试，"
        f"失败 {len(result.failures)} 个，错误 {len(result.errors)} 个。"
    )
    print("往上翻，看 FAIL/ERROR 下面的第一行，会写是哪个测试、断言什么。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
