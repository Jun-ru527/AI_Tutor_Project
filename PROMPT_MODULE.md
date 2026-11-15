# prompts.py 模块说明（A 岗 · prompt）

> 对应《记账助手·路线大纲》里 `prompts.py` 的职责：**三套提示词 + 七类同义词 + 拒答词 + 测试句**。
> 对外共享三个函数：`text_messages(text)`、`clean(raw)`（旧接口，单条）和 `clean_many(raw)`（新接口，多笔）；四个文件统一使用 `{ok, data, msg}` 形状和六字段记录。

---

## 1. 团队契约（先看这一节）

### 1.1 一条记录只有六个字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `amount` | 数字 | 多少元（收入也是正数）。识别不出来留空（`None`），**不许填 0** |
| `category` | 文字 | 只能是：餐饮、交通、购物、居住、娱乐、医疗、其他 |
| `spent_at` | 文字 | `"YYYY-MM-DD"`，例如 `2026-11-13` |
| `merchant` | 文字 | 在哪儿花的/来源，可以为空字符串 `""` |
| `note` | 文字 | 补充说明（如「和同事 AA」），可以为空字符串 `""` |
| `type` | 文字 | **11/15 新增**：只能是 `"支出"` 或 `"收入"` |

改字段 = 改契约，必须 `prompts.py / ai_core.py / db.py / app.py` 四个人一起改，所以**当前锁定，不加字段**。

> ⚠️ **统计必须按 `type` 过滤**：问「这个月花了多少」要加 `WHERE type = '支出'`，
> 问「赚了多少」要加 `WHERE type = '收入'`，算结余时两者都要。否则收入会被混进支出，数字全错。

### 1.2 每个函数只返回一种形状

```python
{"ok": True,  "data": {...}, "msg": ""}      # 成功
{"ok": False, "data": None,  "msg": "人话"}   # 失败，msg 可直接展示给用户
```

`clean` 失败但已有部分字段时，`data` 会带回六字段草稿（金额为 `None`），方便页面回填。

### 1.3 三个共享函数

```python
text_messages(text: str, *, now=None) -> list[dict]
# 传一句话，拿回问模型用的 messages（模型按 JSON 数组返回，一句话可多笔）

clean(raw, *, source_text=None, now=None) -> {"ok", "data", "msg"}
# 旧接口：传模型原话，拿回五个字段（数组时只返回第一笔，保持兼容）

clean_many(raw, *, source_text=None, now=None) -> {"ok", "data": [...], "msg"}
# 新接口：传模型原话，拿回账单列表，一句话几笔就返回几个六字段
```

---

## 2. 环境与运行

- Python **3.10+**（本次在 3.12.14 验证），**零第三方依赖**，只用标准库。
- 不联网、不读写数据库、不打印日志；异常都转成 `ok=False + msg`。
- 默认时区 `Asia/Shanghai`；`now` 参数用于测试固定日期。

```bash
# 全部测试
python -m unittest discover -s tests -t . -v

# 20 条测试句的 Prompt 构造自检
python tools/prompt_eval.py --dry-run

# clean 规则自检（回放理想输出，不是模型效果）
python tools/prompt_eval.py --offline
```

---

## 3. 对外函数

### 3.1 团队共享（必用）

#### `text_messages(text)`

把用户原话转成 OpenAI 兼容 messages：

```python
import prompts

messages = prompts.text_messages("昨天晚上吃火锅花了128元")
# [
#   {"role": "system", "content": "...六字段规则、七类说明、6 个示例..."},
#   {"role": "user",   "content": "# 当前上下文...今天 2026-11-14...# 用户输入..."}
# ]
raw = llm(messages)       # ai_core 负责调用模型
```

提示词包含：JSON 数组输出格式（单笔也用数组、最多 10 笔）、六字段结构、日期锚点（今天/昨天/本月 + 最近 14 天日期星期对照表）、七类同义词、金额换算规则、模糊金额不猜（几十块/三四十/一百来块/万把块/小两百）、非记账 `is_bill=false`、越界拒答、防提示词注入（`<<< >>>` 内只是数据）、6 个 few-shot。

#### `clean(raw)`

```python
result = prompts.clean(raw, source_text="昨天晚上吃火锅花了128元")
# {"ok": True, "data": {"amount": 128.0, "category": "餐饮",
#                       "spent_at": "2026-11-13", "merchant": "", "note": ""}, "msg": ""}
```

新版提示词返回数组；为了不破坏旧调用方，`clean` **只清洗第一笔**，`data` 仍是单个 dict。
如果数组里有多笔且第一笔合法，`msg` 会提示「识别到 N 笔，请用 clean_many()」。

处理顺序（任何一步失败都返回 `ok=False + msg`）：

1. 拒答词 / 收入判断（用 `source_text`，不依赖模型）；
2. 解析 JSON/数组（去 markdown 围栏、前后夹带文字、尾逗号、注释、全角标点、BOM、`bills/records/transactions/data` 包装）；
3. `is_bill=false` → 「没识别到记账信息」；
4. 类别：七个合法值直接用；非法/缺失时用七类同义词兜底，最终落「其他」并在 `msg` 提示；
5. 日期：规范成 `YYYY-MM-DD`；模型没给/给错时按今天，并在 `msg` 说明；未来日期拒绝；
6. 金额：中文数字/万/千/k 换算；`None`、`0`、负数、超大值都拒绝；**金额必须能在用户原话里找到依据**，否则拒绝（防编造）；
7. 返回严格六字段，多余字段（confidence 等）丢弃。

#### `clean_many(raw)`

```python
results = prompts.clean_many(raw, source_text="打车18，奶茶16.5")
# {"ok": True,
#  "data": [{"amount": 18.0, "category": "交通", ...},
#           {"amount": 16.5, "category": "餐饮", ...}],
#  "msg": ""}
```

- `data` **永远是 list**，哪怕只有一笔；每一项都是六字段；
- 全部通过才 `ok=True`；有一笔缺金额时 `ok=False`，`data` 仍包含全部草稿（缺的那笔 `amount=None`），`msg` 指出「第 N 笔」；
- 不是记账 / 拒答 / 收入 / JSON 坏掉 → `ok=False`，`data=[]`；
- 自动去掉「一共/合计」被模型误当成单独一笔的总额（三笔以上且金额相加对得上时）。

### 3.2 A 岗扩展（可选，ai_core 按需调用）

| 函数 | 用途 | 返回 data |
| --- | --- | --- |
| `image_messages()` | 小票/支付截图识别提示词 | messages（ai_core 追加图片内容） |
| `intent_messages(text, history=None)` | 意图识别（记账/查账/分析/修改/删除/预算/帮助/无关） | messages |
| `clean_intent(raw)` | 意图结果清洗 | `{"intents": [...], "time_range": {...}/None, "categories": [...], "target": ...}` |
| `analysis_messages(question, stats)` | 消费分析提示词（stats 由 SQL 算好） | messages |
| `clean_analysis(raw, stats)` | 分析结果校验 + 防编造 | `{"summary": str, "highlights": [...], "suggestions": [...]}` |
| `classify_category(text)` | 七类同义词兜底分类 | `"餐饮"` 等，或 `None` |
| `find_refusal(text)` | 拒答词命中检查 | 命中的短语或 `None` |
| `normalize_category(value, text)` | 类别规范化 | `(类别, 是否用了兜底)` |
| `render_stats_summary(stats)` | 不经过模型的数据摘要（分析失败降级用） | `str` |
| `TEST_SENTENCES` | 20 条测试句 | `tuple[str, ...]` |

> 这些扩展同样遵守 `{ok,data,msg}`，不改变团队六字段契约。

---

## 4. 七类与同义词

| 类别 | 典型说法 |
| --- | --- |
| 餐饮 | 吃饭、早/午/晚饭、外卖、火锅、烧烤、奶茶、咖啡、餐厅、食堂、买菜、水果、零食、面包、包子 |
| 交通 | 打车、滴滴、出租车、地铁、公交、高铁、火车、机票、加油、停车、单车、过路费 |
| 购物 | 衣服、鞋、淘宝、京东、超市、日用品、化妆品、数码、耳机、手机、电脑 |
| 居住 | 房租、水费、电费、燃气、物业、宽带、家具、装修 |
| 娱乐 | 电影、游戏、KTV、演出、演唱会、旅游、健身、会员、门票 |
| 医疗 | 医院、挂号、看病、买药、药店、体检、牙医、诊所 |
| 其他 | 话费、手机话费、流量、学费、培训、快递、宠物、红包、维修、理发、无法归类的支出 |

同一份词表在代码里是 `CATEGORY_SYNONYMS`，Prompt 里也会展示，模型和兜底逻辑保持一致。
**类别故意不扩到十几类**：路线大纲明确要求七类，类别越多模型越不稳。

---

## 5. `clean` 行为矩阵（前端/ai_core 按这个分支）

| 场景 | ok | data | msg |
| --- | --- | --- | --- |
| 正常记账 | True | 六字段 | `""` 或类别/日期的提示 |
| 一句话多笔 | True | list（每项六字段） | 用 `clean_many()`；`clean()` 只返回第一笔 |
| 多笔里有一笔缺金额 | False | list（缺的那笔 `amount=None`） | 「第 N 笔：金额我没听清…」 |
| 金额缺失/模糊 | False | 六字段草稿，`amount=None` | 「金额我没听清，请问这笔花了多少钱？」 |
| 金额在原话里找不到依据 | False | 同上 | 「你说的金额我没听清，能再说一次准确的数字吗？」 |
| 不是记账（闲聊/写诗） | False | None | 「这句话我没有识别到记账信息…」 |
| 越界请求（贷款/套现/荐股） | False | None | 「这个请求我帮不上忙…」 |
| 收入（工资/兼职/奖金/退款） | True | 六字段，`type="收入"` | `""` |
| 模型没给 type | True | 六字段，按**这一笔所在的原文小句**兜底 | 兜底时可能带提示 |
| type 写成 expense/income 等别名 | True | 六字段，规范成中文 | `""` |
| 支出和收入混在一句 | True | list，每项各自带 type | 用 `clean_many()` |
| 日期解析失败 | True | 六字段，按今天 | 「日期没看清，已按今天记录。」 |
| 日期在未来 | False | 六字段 | 「这个日期在未来，请确认后再记。」 |
| 类别非法/缺失 | True | 六字段（兜底「其他」） | 「类别先归为「其他」，可以手动改。」 |
| 模型 JSON 坏了 | False | None | 「模型返回格式异常，请再试一次。」 |

> 注意：`ok=True` 也可能带 `msg`（例如类别兜底），前端把它当提示条展示即可，不要当错误。
>
> 收入词只保留「收入/工资/薪水/奖金/兼职/副业/退款」；「利息/报销/到账/分红」不再由代码判收入
> （避免「还信用卡利息」「报销前垫付」「快递费到账」被误杀），是否属于收入交给提示词里的模型判断。

---

## 6. 与 ai_core.py / db.py / app.py 的对接

### 6.1 `ai_core.parse_text`

```python
# ai_core.py
from prompts import text_messages, clean_many, clean

def parse_text(text: str) -> dict:
    """传一句话，拿回 {ok, data, msg}；data 是账单列表（可能 1 笔或多笔）。"""
    messages = text_messages(text)
    raw = llm(messages)                          # 模型调用（temperature=0）
    return clean_many(raw, source_text=text)     # data: [六字段, ...]

# 旧调用方如果只接受单条，可以继续用 clean（数组时只返回第一笔）：
def parse_text_one(text: str) -> dict:
    messages = text_messages(text)
    raw = llm(messages)
    return clean(raw, source_text=text)          # data: 六字段 dict
```

### 6.2 `ai_core.parse_image`

```python
from prompts import image_messages, clean

def parse_image(image_path: str) -> dict:
    messages = image_messages()
    messages[-1]["content"] = [
        {"type": "text", "text": messages[-1]["content"]},
        {"type": "image_url", "image_url": {"url": to_data_url(image_path)}},
    ]
    raw = vision_llm(messages)
    return clean(raw)                      # 有 OCR 文本时可传 source_text=ocr_text
```

### 6.3 `db.add` / `add_bill`

**写库前必须先判断 `ok`**，否则缺金额的草稿（`amount` 为 `None`）会被写进库：

```python
result = clean_many(raw, source_text=text)

if not result["ok"]:
    show_drafts(result["data"])            # 只显示草稿卡让用户补，不入库
    return

for bill in result["data"]:                # ok=True 时每笔 amount 一定不是 None
    db.add(bill["amount"], bill["category"],
           bill["spent_at"], bill["merchant"], bill["note"])
```

如果想更保险，可以再加一道显式检查：

```python
for bill in result["data"]:
    if bill["amount"] is None:             # 双保险：空金额绝不入库
        continue
    db.add(...)
```

> **空值写法对照（新人最容易在这里踩坑）**
>
> | 位置 | 空值关键字 | 示例 |
> | --- | --- | --- |
> | SQL 语句 | `NULL` | `UPDATE records SET merchant = NULL WHERE id = 1` |
> | Python 代码 | `None` | `db.add(None, "餐饮", "2026-11-14", "", "")` |
> | 模型返回的 JSON | `null` | `{"amount": null, "category": "餐饮"}` |
>
> Python 里没有 `NULL` 这个关键字，写 `db.add(NULL, ...)` 会直接 `NameError`。
> `prompts.py` 已经把模型 JSON 里的 `null` 转成了 Python 的 `None`，
> 所以调用方拿到的 `bill["amount"]` 只会是 `float` 或 `None`，不需要自己转换。

### 6.4 查账 / 分析

- 查账：`intent_messages` + `clean_intent` 解析出 `time_range` / `categories`，再调 `db.sum_by_category(start, end)`。
- 分析：把 db 的聚合结果组装成 `stats`，交给 `analysis_messages` + `clean_analysis`。

建议的 `stats` 结构（`clean_analysis` 会按这个白名单校验数字）：

```python
stats = {
    "period": {"start": "2026-11-01", "end": "2026-11-30", "label": "2026年11月"},
    "total": 3200.5,                    # 或 total_expense
    "count": 42,                        # 或 transaction_count
    "by_category": [
        {"category": "餐饮", "amount": 1200.0, "share": 0.375, "count": 18}
    ],
    "top_category": {"category": "餐饮", "amount": 1200.0},
    "previous": {"label": "上月", "total": 2800.0, "change_amount": 400.5},
    "budget": {"amount": 3000.0, "used": 3200.5, "over": True},
}
```

**任何 stats 里没有、也无法由 stats 推导的数字，`clean_analysis` 都会拒绝并降级成数据摘要**，保证「统计不交给模型凭空生成」。

### 6.5 app.py 的两个注意点

1. `ok=False` 且有 `data` 时，把 `data` 回填到草稿卡，只显示 `msg`，不要入库；
2. `ok=True` 且 `msg` 非空时，按提示条展示，不要当失败。

---

## 7. 拒答与边界

`REFUSAL_PHRASES` 用短语匹配，避免误伤正常记账：

- 命中：「贷款口子」「哪里能贷款」「教我贷款」「套现」「绕过额度」「提额」「荐股」「推荐股票」「赌博」「洗钱」「代开发票」「逃税」「刷单」等；
- 不命中：「还贷款 3000」（这是支出，正常记账）。

app / ai_core 可以在调模型前先 `find_refusal(text)`，命中直接返回固定话术，省一次调用；`clean` 里还会再兜底一次。

---

## 8. 测试与通过率

### 8.1 离线测试（已执行）

```bash
python -m unittest discover -s tests -t . -v
```

实际结果（2026-11-15，Python 3.14.10）：

```
Ran 75 tests in 0.114s
OK
```

覆盖：

- 契约形状（`{ok,data,msg}`、严格六字段、不允许多余字段）；
- 20 条测试句的理想输出回放（金额/类别/日期全对）；
- 30 条异常：模糊金额、编造金额、非记账、拒答、收入、中文数字、1.5k、非法类别、默认日期、未来日期、商户/备注、金额 0、模糊词位置、利息/垫付/到账、面包/包子、手机话费、工资收入、兼职收入、退款收入、支出不变收入、type 英文别名、type 缺失兜底、发红包是支出、发工资是支出、退款是收入；
- **17 条多笔账**：两笔拆分、合计总额不单独成笔、多笔里缺一笔金额、三四十模糊范围、非记账数组、`25元左右`、`25块钱`、`百二十`、`百八十`、支出收入混合、两笔收入、混合且模型未写 type（4 种顺序）、中文数字混合 2 种；
- `clean_many` 的数组/单对象/空数组/代码块夹带文字；
- 模糊金额不猜：几十块、三四十、一百来块、小两百、万把块；
- JSON 容错（围栏、前后文字、尾逗号、注释、全角标点、BOM、data/records 包装）；
- 七类同义词、拒答词、收入词；
- 意图（多意图、时间区间、类别别名、off_topic）；
- 分析（数字有据/编造、四舍五入、空数据、字符串数组、降级摘要）；
- 时间上下文（含最近 14 天日期星期表）。

### 8.2 20 条测试句通过率

```bash
python tools/prompt_eval.py --offline      # 规则自检
python tools/prompt_eval.py               # 真实模型（需要 Key）
```

当前实际结果：

- `--dry-run`：20/20 Prompt 构造成功；
- `--offline`：20/20 规则自检通过（**这只是回放理想输出，不是模型能力**）；
- 真实模型通过率：**尚未执行，没有 API Key**。README 里要写的「提示词通过率」需要拿到 Key 后跑一次，报告会写到 `reports/prompt_eval_*.json`。

---

## 9. 已知问题与未解决

1. **收入已支持（11/15 起）**：团队新增第 6 个字段 `type`（存「支出」/「收入」），收入不再拒绝。模型没给 `type` 时用关键词兜底，仍判断不出就默认「支出」。注意「利息/报销/到账/分红」不参与自动判收入，避免误伤正常支出。
2. **真实模型未验证**：Prompt 效果、few-shot 是否够用，必须用 Key 跑 20 条测试句后再调。
3. **AA 语义未定义**：`聚餐AA 150` 默认把 150 记作自己的支出，不自动除以人数；如果要分摊，需要产品确认。
4. **类别边界**：「买菜」归餐饮、「超市」归购物、「话费」归其他，是当前约定，需产品/组长确认。「包」单字已从购物词表删除（避免「面包」「包子」误判），如需「买包」可再补「包包/背包」等词。
5. **日期默认今天**：用户不说日期时按今天，符合记账习惯，但可能不符合「不猜日期」的严格要求，已写进 README 口径。
6. **OCR 未实测**：`image_messages` 只是提示词，图片传入、视觉模型调用属于 `ai_core.parse_image`，当前没有样例小票验证。
7. **`clean_analysis` 只校验阿拉伯数字**：中文数字（「三笔」）不拦截，Prompt 已要求用阿拉伯数字。
8. **没有 `ai_core.py`**：目录里原本没有这个文件，本模块只提供契约与测试；集成代码待 C 岗完成。
9. **多笔账已支持，但单次最多 10 笔**：`clean_many` 会截断超过 `MAX_BILLS=10` 的输入；旧的 `clean` 只返回第一笔（兼容旧代码），新代码请用 `clean_many`。总额兜底只在文本含「一共/总共/合计/总计/共计」且至少 3 笔时生效。

---

## 10. 需要其他组员配合

| 对象 | 需要做什么 |
| --- | --- |
| **C 岗 / ai_core** | ① `parse_text` 按 6.1 调 `text_messages` + `clean_many`（多笔）；② `parse_image` 按 6.2 追加图片；③ Key 走环境变量；④ 把模型原始输出记日志，方便 badcase 回归。 |
| **B 岗 / db** | ① 表字段严格六字段；② `add(amount, category, spent_at, merchant, note, type)`；③ `sum_by_category(start, end)` 返回 6.4 的 `stats`（尤其 `total`/`count`/`by_category`/`top_category`）。 |
| **D 岗 / app** | ① 草稿卡按 `clean_many().data` 列表逐张展示，可编辑；② `ok=False` 显示 `msg` 并保留草稿；③ 类别下拉固定七类；④ 查账/分析页用 `clean_intent` / `clean_analysis` 的结果。 |
| **队长 / 产品** | ① 确认收入是否要支持（涉及加第六个字段）；② 确认 AA 与日期默认口径；③ 提供 API Key 跑真实通过率。 |
| **我 下一步** | ① 拿到 Key 跑 `tools/prompt_eval.py`，把通过率写进 README；② 三轮 Docker/镜像/跑分（大纲第三阶段）等 `app.py` 就绪后做；③ 收集真实 badcase 补进 `tests/cases/text_cases.json`。 |

---

## 11. 版本

- `PROMPT_VERSION = "2.3.1"`（11/15）：**两处判断修正**。
  - 「发工资」「发奖金」从 `EXPENSE_OVERRIDE_WORDS` 移除——口语里「今天发工资了」是自己收到钱，
    不是发出去；之前会被误判成支出。真正发钱给别人一般说「给员工发工资」，另有规则处理。
  - `locate_amount_text()` 支持中文数字定位（五百、三十二、两千五）：之前只认阿拉伯数字，
    金额写成中文时定位失败会退回整句判断，导致「兼职收入五百，打车花三十二」两笔都记成收入。

- `PROMPT_VERSION = "2.3.0"`（11/15）：**合并版**——你的图片提示词改动 + 本版的收支判断算法。
  - **图片提示词新增 `type`**（原版 `_IMAGE_SYSTEM` 没有 type，收款/退款截图会被记成支出）：
    输出格式加 `type` 字段，并写明「付款成功/消费/订单/小票 → 支出；收款/到账/退款/转入 → 收入」。
  - 保留 `locate_amount_text()` 按原文小句定位的兜底算法，多笔不串笔。
  - 保留 `EXPENSE_OVERRIDE_WORDS`（发红包/发工资/转账给/还款等），避免支出被记成收入。
  - `_clean_record` 保留 `multi` 参数与「模型漏写 type」提醒文案；金额解析提前到类型判断之前。

- `PROMPT_VERSION = "2.2.1"`（11/15）：**修复 type 兜底串笔**。
  模型没写 `type` 时，原来用整句话找收入词，导致「兼职收入500，打车花32」里 32 也被记成收入。
  现在改为 `locate_amount_text()`：先按标点切小句，取金额所在的那一小句再判关键词，每笔独立判断。
  同时精简 `INCOME_WORDS`（去掉「红包」「转入」等歧义词），新增 `EXPENSE_OVERRIDE_WORDS`
  （发红包、发工资、转账给、还款等），避免「给朋友发红包」被记成收入。

- `PROMPT_VERSION = "2.2.0"`（11/15）：**支持收入**。团队新增第 6 个字段 `type`（"支出"/"收入"）。
  提示词改为每笔输出 `type`，并新增「收入」「支出收入混合」两个 few-shot；收入不再被拒绝；
  `normalize_type()` 负责把 `expense/income/花费/进账` 等别名规范成中文，模型没给时用原话关键词兜底（默认支出）；
  `_make_data()` 输出第 6 个字段。测试仍为 75 个，但用例数据从 19 条异常增至 25 条、9 条多笔增至 11 条。

- `PROMPT_VERSION = "2.1.0"`：提示词改为返回 JSON 数组（一句话可多笔）；新增 `clean_many()`（data 永远 list，每项六字段）；`clean()` 保留并向后兼容（数组时只取第一笔）；补充「三四十/几十块/一百来块/小两百/万把块」等模糊金额必须留空的规则；自动去掉「合计」误判为单独一笔的总额。

  同版本内的后续修复（未单独升号，已包含在 2.1.0 中）：
  - **中文数字省称不再误拦**：`打车百二十`＝120、`打车百八十`＝180 现在正常入账；只拦截「三四十、几十、几百、二十几、一百来、万把、小两百」这类真·范围/约数。
  - **模糊词隔货币单位也能识别**：`打车25元左右`、`打车25块上下`、`买衣服200多块钱` 都会被判为模糊并留空（之前「元」字挡住了判断）。
  - **模糊词只认紧挨金额的位置**：`大概吃饭25` 正常入账（「大概」修饰的是吃饭），`吃饭大概25` 仍拦下。
  - **收入词不误伤支出**：`还信用卡利息50`、`报销前先垫付打车32`、`快递费到账12` 正常记支出。
  - **七类词表**：删掉单字「包」（避免面包/包子误判），补「面包」「包子」「手机话费」「话费充值」。
  - **测试**：75 个单元测试、20 条测试句、30 条异常、17 条多笔用例。

- `PROMPT_VERSION = "2.0.1"`：修正 4 个问题——模糊词只看紧邻金额的位置；移除误伤正常支出的收入词（利息/报销/到账/分红）；类别词表去掉「包」、补「面包」「包子」「手机话费」；提示词补防注入、日期年份规则、最近 14 天日期星期表（图片提示词同步补防注入）。
- `PROMPT_VERSION = "2.0.0"`：从「22 类 + ValidationResult + build_*」重构为团队契约「6 字段 + 7 类 + {ok,data,msg} + text_messages/clean」。
- 改 Prompt 文案、字段、类别时请升版本号，并同步 `tests/cases/text_cases.json`。
- 旧的 `ai_prompt.py` 已移除，避免两套类别体系并存。
