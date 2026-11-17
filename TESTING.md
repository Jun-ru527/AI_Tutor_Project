# 怎么测试这个项目

> 适用：当前工作区里的 `prompts.py`（A 岗 Prompt 模块）。
> 环境：Windows + PowerShell；你机器上请用 **`py`** 命令（`python` 是应用商店空壳，会打不开）。

## 0. 进入项目目录

```powershell
cd "C:\Users\赵汝晴\Documents\deepseek-harness\default-workspace"
```

如果中文输出乱码，先执行一次：

```powershell
$env:PYTHONUTF8 = "1"
```

---

## 1. 自动化测试（约 1 秒，不需要 Key）

**最省事：直接双击项目里的 `run_tests.cmd`**，会弹出黑窗口跑完 75 个测试并停在结果页。

或者在 PowerShell 里：

```powershell
py run_tests.py
# 或者
py -m unittest discover -s tests -t . -v
```

预期结果：

```
Ran 75 tests in 0.1s
OK
```

### 在 PyCharm 里运行（第一次需要两步）

1. 打开项目文件夹 `default-workspace`（不是单独打开某个 .py 文件）；
2. 第一次打开会提示 **Trust Project / 信任项目**，点一次（JetBrains 的安全机制，必须本人确认）；
3. 右下角解释器如果显示未配置，点它选：

```
<项目目录>\.venv\Scripts\python.exe
```

之后在左侧右键 `run_tests.py` → **Run 'run_tests'** 即可。

> 如果 PyCharm 标题栏还是 `aiprompt – ...\某个文件.py`，说明你把我们的文件当成 aiprompt 项目的"外部文件"打开了，
> 这时 Run 会灰掉。用 `File → Open` 重新打开整个 `default-workspace` 文件夹。

- 有失败时，输出里会有 `FAIL:` 或 `ERROR:`，并指出用例 id 和断言；
- 只跑单个测试文件：`py -m unittest tests.test_prompts -v`；
- 只跑某一条：`py -m unittest tests.test_prompts.TestCleanBehaviors.test_missing_amount_returns_partial_draft -v`。

这些测试验证的是**契约和规则**：六字段、七类、`{ok,data,msg}`、金额防编造、日期、拒答、JSON 容错。**不验证模型效果**。

---

## 2. Prompt 自检（不需要 Key）

```powershell
py tools/prompt_eval.py --dry-run
py tools/prompt_eval.py --offline
```

预期：

```
[dry-run] 20 条测试句的 Prompt 均构造成功。
[offline] 规则自检通过 20/20（不是模型效果，只验证 clean 规则）
```

- `--dry-run`：只检查 20 条测试句的 messages 能否正常构造；
- `--offline`：用用例里的「理想模型输出」回放 `clean`，检查规则是否 100% 自洽。

---

## 3. 无 Key 手工验证（复制 → 粘贴）

### 第 1 步：打印提示词

```powershell
py tools/try_prompt.py "昨天晚上吃火锅花了128元"
```

会显示 system（只显示字数）和完整的 user 消息。加 `--full` 可看完整 system：

```powershell
py tools/try_prompt.py "昨天晚上吃火锅花了128元" --full
```

### 第 2 步：把 messages 发给任意对话模型

复制 system + user 到 DeepSeek / 智谱 / 豆包等对话框，要求它「只输出 JSON」。
把回答保存成 `answer.txt`（UTF-8），或用下面的方式直接验证。

### 第 3 步：把模型回答喂回 `clean`

```powershell
py tools/try_prompt.py "昨天晚上吃火锅花了128元" --raw-file answer.txt
```

或用管道（避免 PowerShell 吞引号）：

```powershell
Get-Content answer.txt -Raw | py tools/try_prompt.py "昨天晚上吃火锅花了128元" --raw -
```

预期输出：

```json
{
  "ok": true,
  "data": {
    "amount": 128.0,
    "category": "餐饮",
    "spent_at": "2026-11-13",
    "merchant": "",
    "note": ""
  },
  "msg": ""
}
```

退出码：`0` 表示 `clean` 成功，`1` 表示失败，方便脚本判断。

一句话多笔时加 `--many`，`data` 会返回列表：

```powershell
py tools/try_prompt.py "打车18，奶茶16.5" --many --raw-file answer.txt
```

```json
{
  "ok": true,
  "data": [
    {"amount": 18.0, "category": "交通", "spent_at": "2026-11-14", "merchant": "", "note": "打车"},
    {"amount": 16.5, "category": "餐饮", "spent_at": "2026-11-14", "merchant": "", "note": "奶茶"}
  ],
  "msg": ""
}
```

> ⚠️ 不要用 `py tools/try_prompt.py "..." --raw '{"is_bill":true,...}'` 这种内联写法：
> PowerShell 5.1 会吞掉 JSON 里的双引号，看起来像「模型返回格式异常」。
> 用 `--raw-file` 或 `--raw -` 管道最稳。

### 建议手工试的句子

| 句子 | 预期 |
| --- | --- |
| `午饭25` | ok=true，餐饮、25 元、今天 |
| `昨天晚上吃火锅花了128元` | ok=true，餐饮、128、昨天日期 |
| `前天买奶茶花了十五块` | ok=true，中文数字转 15 |
| `买衣服花了两百多` | ok=false，提示金额没听清，草稿里 `amount` 为 Python 的 `None`（模型 JSON 中写作 `null`，SQL 中对应 `NULL`） |
| `今天打车`（模型硬给 30） | ok=false，金额在原话里找不到依据 |
| `帮我写一首诗` | ok=false，「没识别到记账信息」 |
| `帮我找个贷款口子` | ok=false，固定拒答话术 |
| `今天兼职收入500元` | ok=false，「收入暂时不支持」 |
| `明天交房租3000` | ok=false，未来日期需确认 |

---

## 4. 有 Key 跑真实通过率（20 条测试句）

在 PowerShell 里设置环境变量（只对当前窗口生效）：

```powershell
$env:OPENAI_API_KEY = "sk-xxx"
$env:OPENAI_BASE_URL = "https://api.openai.com/v1"
$env:OPENAI_MODEL = "gpt-4o-mini"

py tools/prompt_eval.py
```

- 换成智谱 / DeepSeek 时，把 `OPENAI_BASE_URL` 和 `OPENAI_MODEL` 改成对应值；
- 输出会逐条打印 `PASS/FAIL`，最后给出通过率和报告路径；
- 报告写到 `reports/prompt_eval_<时间>.json`，包含每条原始输出、耗时、失败原因；
- 这个通过率才是能写进 README 的「提示词通过率」；
- `Key 不要提交到仓库`，只放环境变量。

常见报错：

| 报错 | 处理 |
| --- | --- |
| 401 / Unauthorized | Key 或 base_url 不对 |
| 404 model not found | 模型名写错 |
| 400 response_format 不支持 | 加 `--no-json-mode` |
| 超时 | 加 `--timeout 90`，或减少 `--limit` |

---

## 5. 加新测试用例

1. 20 条测试句在 `prompts.py` 的 `TEST_SENTENCES`；
2. 对应期望在 `tests/cases/text_cases.json` 的 `text_cases`（测试会断言两者数量、顺序一致）；
3. 异常场景加到 `edge_cases`，每条包含 `text`、`ideal`（理想模型输出）、`expected`（期望的 ok/字段/msg 关键词）；
4. 重新跑第 1 节测试。

---

## 6. 常见问题

| 现象 | 原因 / 解决 |
| --- | --- |
| 输入 `python` 弹出应用商店 | 用 `py`，或 `py -3.14` |
| `ModuleNotFoundError: No module named 'prompts'` | 必须在项目根目录运行，不要在 `tools\` 里运行 |
| 中文乱码 | `$env:PYTHONUTF8="1"`，或先 `chcp 65001` |
| `--raw` 报格式异常 | PowerShell 吞了双引号，改用 `--raw-file` / 管道 |
| 日期是 2026-11-14 | 测试固定了 `NOW`；真实运行会用当天日期 |
| 测试全过但模型效果差 | 离线测试只验证规则，需按第 4 节跑真实通过率 |
| 报告目录不存在 | 工具会自动创建 `reports/` |

---

## 7. 测试边界（避免误判）

- 75 个测试 + 20/20 规则自检 **不代表模型准确率**；
- 真实模型通过率 **尚未跑**（没有 API Key）；
- OCR / 小票识别只有提示词，**没有用真实图片验证**；
- 收入已支持，由 `type` 字段区分「支出」/「收入」；统计时需按 `type` 过滤；
- 用户不提供日期时默认今天，属于团队当前口径。
