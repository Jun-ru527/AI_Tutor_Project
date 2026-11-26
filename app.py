# -*- coding: utf-8 -*-
"""
界面层 (王佳欣：岗位 C)

文件职责
--------
本文件是整个应用的唯一入口，负责页面、页签、输入、确认/修正、表格与图表。
按团队接口约定，界面层只 import ai_core 与 db，跨文件只调用函数，
不读取队友模块的内部变量与实现。

一条账单固定 6 个字段：
       amount    金额，数字
       category  分类，文字
       spent_at  消费日期，YYYY-MM-DD
       merchant  商户，文字
       note      备注，用户原话
       type      收支类型，"支出" 或 "收入"

重要：接口约定文档写"所有函数统一返回 {ok,data,msg}"，但 db.py 的真实实现并非如此，
本文件的适配层 call_module() 同时兼容三种返回形态，避免静默失败：
       ai_core.parse_text / parse_image       -> {"ok":bool, "data":dict|list, "msg":str}
       db.init_db / add_bill / set_budget     -> 裸 True / False
       db.list_records / sum_by_category     -> list[dict]（异常时 None / False）
       db.get_budget                         -> {"ok":..., "data":{"limit_amount":...}, "msg":...}
另外 db.sum_by_category 的 SQL 未给 SUM(amount) 起别名，返回键可能是 "SUM(amount)"；
get_budget 的金额字段是 limit_amount 而非 amount。适配层均已兼容。

本模块调用的函数：
       ai_core.parse_text(text) / ai_core.parse_image(image_path)
       ai_core.parse_query(text)   可选，队友未实现时前端降级为手动筛选
       db.init_db() / db.add_bill(data) / db.list_records(type)
       db.sum_by_category(type) / db.set_budget(category, limit_amount, month)
       db.get_budget(category, month)
界面层统一只走 db.add_bill(data) 入库，不调用任何 add_* 内部函数。

演示数据模式
------------
队友模块尚未就绪时，可勾选侧栏 "使用演示数据" 独立跑通全部页面与完整流程，
对应技术方案里 "每个文件先交能返回固定假数据的版本，界面拿假数据即可联调" 的策略。
演示模式下新增的账单会存进内存，可立即在明细/统计/趋势里查到，形成闭环。

真实模式（有 API Key）下的拒答边界（2026-11-26 按队友复核意见修复）：
  * demo_parse() 只允许在演示数据模式下调用，绝不能用于真实模式的失败兜底。
  * ok=False（拒答/非记账）、ok=True 但规整后为空或金额<=0，一律不生成任何草稿，
    只给出醒目的提示，避免用户把凭空造出的假账单确认入库写进真实数据库。
  * 界面层另有越界请求与非记账闲聊两道兜底，与 prompts.py 的拒答形成三重保险。
  * 入库前再校验金额必须 > 0。
  自测用例：「帮我找个贷款口子」「今天天气怎么样」只出提示；「午饭 25」正常出卡。

本周优化（11/26-11/29，岗位 C 的 7 项）：
  T1 明细页导出 CSV（utf-8-sig，Excel 不乱码）
  T2 对账自检：明细逐笔累加 vs 统计页合计，一键给出「一致 / 差异金额」
  T3 缺金额时「确认入库」按钮置灰（保留待补全草稿，不整张丢弃）
  T4 上传限 5MB + PNG/JPG/JPEG 白名单，超限出中文提示且不崩
  T5 隐藏开发机工具栏（.streamlit/config.toml + CSS 兜底）
  T6 草稿卡片显示「置信度 / 来源」，文字输入与小票 OCR 标签不同
  T7 单笔支出 > 5000 提示「金额偏大」，收入不触发

运行方式
--------
    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import calendar
import html
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    # API Key 由 ai_core 负责读取；此处仅做兜底加载，失败不影响界面启动
    pass

# 保留导入异常信息，在侧栏显示，方便排查（例如未配置 ZHIPU_API_KEY 时 OpenAI 初始化会失败）
AI_CORE_IMPORT_ERROR = ""
DB_IMPORT_ERROR = ""
try:
    import ai_core
except Exception as exc:
    ai_core = None
    AI_CORE_IMPORT_ERROR = str(exc)

try:
    import db
except Exception as exc:
    db = None
    DB_IMPORT_ERROR = str(exc)


# ---------------------------------------------------------------------------
# 常量与演示数据
# ---------------------------------------------------------------------------

TYPE_EXPENSE = "支出"
TYPE_INCOME = "收入"
BILL_TYPES = (TYPE_EXPENSE, TYPE_INCOME)

EXPENSE_CATEGORIES = ("餐饮", "交通", "购物", "居住", "娱乐", "医疗", "其他")
INCOME_CATEGORIES = ("工资", "兼职", "红包", "理财", "其他")

BILL_FIELDS = ("amount", "category", "spent_at", "merchant", "note", "type")

# T4：一张 200MB 大图能卡死演示，界面层限制 5MB + 后缀白名单。
MAX_UPLOAD_MB = 5
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")

# T7：OCR 最容易把 24.00 读成 2400；只对「支出」且超过 5000 的金额提醒。
LARGE_EXPENSE_THRESHOLD = 5000.0

# T6：来源标签，文字录入与小票 OCR 必须显示得不一样。
SOURCE_TEXT = "文字输入"
SOURCE_OCR = "小票 OCR"
SOURCE_DEMO = "演示数据"

# 小票/截图上传的落盘位置。请让 D 在 .gitignore 中排除该目录，避免把用户图片提交进仓库。
UPLOAD_DIR = Path(__file__).resolve().parent / "assets" / "uploads"

# 联调用演示账单：覆盖多个月份、支出与收入、多种分类，保证饼图/趋势/明细都有内容。
# 正式的示例账单 CSV 由队友提供，这份仅作为界面独立运行时的兜底数据。
DEMO_BILLS = [
    {"amount": 25.0, "category": "餐饮", "spent_at": "2026-11-17", "merchant": "食堂", "note": "午饭 25", "type": TYPE_EXPENSE},
    {"amount": 32.0, "category": "交通", "spent_at": "2026-11-16", "merchant": "滴滴", "note": "打车 32", "type": TYPE_EXPENSE},
    {"amount": 168.0, "category": "购物", "spent_at": "2026-11-15", "merchant": "超市", "note": "日用品", "type": TYPE_EXPENSE},
    {"amount": 45.0, "category": "娱乐", "spent_at": "2026-11-12", "merchant": "影院", "note": "电影票", "type": TYPE_EXPENSE},
    {"amount": 8000.0, "category": "工资", "spent_at": "2026-11-10", "merchant": "公司", "note": "11 月工资", "type": TYPE_INCOME},
    {"amount": 500.0, "category": "兼职", "spent_at": "2026-11-08", "merchant": "外包项目", "note": "兼职结款", "type": TYPE_INCOME},
    {"amount": 1500.0, "category": "居住", "spent_at": "2026-11-05", "merchant": "房东", "note": "房租", "type": TYPE_EXPENSE},
    {"amount": 38.5, "category": "餐饮", "spent_at": "2026-10-28", "merchant": "外卖", "note": "晚饭", "type": TYPE_EXPENSE},
    {"amount": 260.0, "category": "购物", "spent_at": "2026-10-20", "merchant": "电商", "note": "换季衣服", "type": TYPE_EXPENSE},
    {"amount": 120.0, "category": "医疗", "spent_at": "2026-10-14", "merchant": "药店", "note": "感冒药", "type": TYPE_EXPENSE},
    {"amount": 8000.0, "category": "工资", "spent_at": "2026-10-10", "merchant": "公司", "note": "10 月工资", "type": TYPE_INCOME},
    {"amount": 88.0, "category": "交通", "spent_at": "2026-10-06", "merchant": "地铁", "note": "充值", "type": TYPE_EXPENSE},
    {"amount": 210.0, "category": "餐饮", "spent_at": "2026-09-25", "merchant": "餐厅", "note": "聚餐 AA", "type": TYPE_EXPENSE},
    {"amount": 380.0, "category": "娱乐", "spent_at": "2026-09-18", "merchant": "景区", "note": "周末出游", "type": TYPE_EXPENSE},
    {"amount": 8000.0, "category": "工资", "spent_at": "2026-09-10", "merchant": "公司", "note": "9 月工资", "type": TYPE_INCOME},
    {"amount": 200.0, "category": "红包", "spent_at": "2026-09-03", "merchant": "家人", "note": "生日红包", "type": TYPE_INCOME},
]

DEMO_BUDGETS = {
    ("餐饮", "2026-11"): 600.0,
    ("购物", "2026-11"): 300.0,
    ("交通", "2026-11"): 200.0,
}


# ---------------------------------------------------------------------------
# 状态与模式
# ---------------------------------------------------------------------------


def init_state() -> None:
    """初始化 session_state；Streamlit 每次交互都会重跑脚本，状态必须显式保存。"""
    defaults = {
        # 队友模块任一缺失时默认进入演示数据模式，保证界面永远能启动
        "use_demo": ai_core is None or db is None,
        "demo_store": [],       # 演示模式下的内存账单，让"存了能查到"形成闭环
        "demo_budgets": dict(DEMO_BUDGETS),
        "pending_bills": [],    # 待用户确认/修正的识别结果
        "parse_notice": "",     # 解析阶段的提示语
        "parse_token": 0,       # 每解析一次 +1，用来刷新草稿卡片的控件 key
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def is_demo() -> bool:
    return bool(st.session_state.get("use_demo", False))


# ---------------------------------------------------------------------------
# 适配层：统一处理队友函数的返回契约与异常
# ---------------------------------------------------------------------------


def call_module(module, func_name: str, *args, default=None):
    """
    安全地调用队友模块的函数，返回 (ok, data, msg)。

    兼容三种情况：
      1. 标准契约 {"ok", "data", "msg"}
      2. 队友直接返回裸数据（未按契约包装）
      3. 模块/函数不存在或抛异常 -> 降级返回 default，界面不中断
    """
    func = getattr(module, func_name, None) if module is not None else None
    if func is None or not callable(func):
        return False, default, f"{func_name} 尚未实现，当前使用演示数据"

    try:
        result = func(*args)
    except Exception as exc:
        return False, default, f"{func_name} 调用失败：{exc}"

    # 情况 1：标准契约 {"ok", "data", "msg"}
    if isinstance(result, dict) and "ok" in result:
        return bool(result.get("ok")), result.get("data", default), result.get("msg", "")

    # 情况 2：db 模块多数函数返回裸 bool（add_bill / set_budget / init_db）。
    # 必须单独判断，否则 False 会被当成"调用成功"导致入库失败却提示成功。
    if isinstance(result, bool):
        return result, None, "" if result else f"{func_name} 执行失败（返回 False）"

    # 情况 3：list_records 异常时返回 None，视为失败并降级
    if result is None:
        return False, default, f"{func_name} 返回空结果（数据库可能异常）"

    # 情况 4：裸数据（list_records / sum_by_category 成功时直接返回列表）
    return True, result, ""


# 模型有时返回中文键名（尤其视觉模型），这里做一层别名，避免"全都识别不出来"
_KEY_ALIASES = {
    "amount": ("amount", "金额", "数额", "money", "价格", "实付", "合计", "total"),
    "category": ("category", "分类", "类别", "类目"),
    "spent_at": ("spent_at", "日期", "时间", "date", "消费日期", "交易日期"),
    "merchant": ("merchant", "商户", "商家", "店铺", "来源"),
    "note": ("note", "备注", "说明", "摘要", "desc"),
    "type": ("type", "收支类型", "收支", "类型", "direction"),
}
_ALL_KEYS = {key for group in _KEY_ALIASES.values() for key in group} | {"is_bill", "confidence"}

# 收支类型的各种说法，统一成 BILL_TYPES 里的两个字
_TYPE_ALIASES = {
    "支出": TYPE_EXPENSE, "消费": TYPE_EXPENSE, "付款": TYPE_EXPENSE, "付": TYPE_EXPENSE,
    "expense": TYPE_EXPENSE, "cost": TYPE_EXPENSE, "out": TYPE_EXPENSE, "-": TYPE_EXPENSE,
    "收入": TYPE_INCOME, "收款": TYPE_INCOME, "到账": TYPE_INCOME, "收": TYPE_INCOME,
    "income": TYPE_INCOME, "in": TYPE_INCOME, "+": TYPE_INCOME,
}


def _pick(item: dict, field: str):
    """按字段别名从模型结果里取值，先英文键、后中文键。"""
    for key in _KEY_ALIASES[field]:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _norm_type(value) -> str:
    text = str(value or "").strip()
    if text in _TYPE_ALIASES:
        return _TYPE_ALIASES[text]
    return _TYPE_ALIASES.get(text.lower(), "")


def _norm_amount(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "")
    for junk in (",", "￥", "¥", "元", " "):
        text = text.replace(junk, "")
    found = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(found.group()) if found else 0.0


def _norm_date(value) -> tuple[str, bool]:
    """把 '2026-11-17' / '2026/11/17' / '2026年11月17日' 统一成 YYYY-MM-DD。

    返回 (日期, 是否被夹到今天)。
    认不出来就用今天——绝不让 '昨天' 这种原文直接进数据库；
    晚于今天的日期也夹到今天，否则这笔账会跑进下个月的统计里、本月看不到。
    """
    text = str(value or "").strip()
    today = date.today()
    found = re.search(r"(\d{4})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})", text)
    if found:
        year, month, day = (int(part) for part in found.groups())
        try:
            parsed = date(year, month, day)
        except ValueError:
            return today.isoformat(), False
        if parsed > today:
            return today.isoformat(), True
        return parsed.isoformat(), False
    return today.isoformat(), False


def normalize_bills(data) -> list[dict]:
    """
    把模型返回的 data 规整成 6 字段账单列表。

    实际可能是：
      1. 单个字典
      2. 字典列表（"一句话多笔"，支出和收入可以混在一起）
      3. 外层再包一层，如 {"bills": [...]} / {"records": [...]} / {"data": [...]}
      4. 中文键名的字典（视觉模型常见）
      5. is_bill=false（闲聊、越界请求），这种要丢掉
    """
    if data is None:
        return []

    # 先剥离可能的外层包装（用中英文字段名一起判断，避免把中文键的账单又拆一层）
    for _ in range(3):
        if isinstance(data, dict) and not (set(data) & _ALL_KEYS):
            for key in ("bills", "records", "items", "list", "data", "result"):
                if key in data:
                    data = data[key]
                    break
            else:
                break
        else:
            break

    items = data if isinstance(data, list) else [data]

    bills = []
    for item in items:
        if not isinstance(item, dict):
            continue

        amount = _norm_amount(_pick(item, "amount"))
        # 模型说"这不是一笔账"时，只有金额也确实是空的才丢掉。
        # 有些图（工资明细、转账流水）会被判成"不是小票"，但字段其实读得很准，
        # 这时宁可让用户确认，也不要把整笔悄悄扔掉。
        flag = str(item.get("is_bill", True)).strip().lower()
        if flag in ("false", "0", "no") and amount <= 0:
            continue

        spent_at, date_clamped = _norm_date(_pick(item, "spent_at"))
        note = str(_pick(item, "note") or "")
        if date_clamped:
            note = (note + "；" if note else "") + "原日期在未来，已按今天记"

        bills.append(
            {
                "amount": amount,
                "category": str(_pick(item, "category") or "其他"),
                "spent_at": spent_at,
                "merchant": str(_pick(item, "merchant") or ""),
                "note": note,
                # 关键：这里以前只认 "支出"/"收入" 两个词，其余一律当支出，
                # 于是模型写的英文、带空格、或干脆没这个字段时，收入就永远变支出。
                "type": _norm_type(_pick(item, "type")) or TYPE_EXPENSE,
                # T6：界面专用元数据，以下划线开头，不进入 BILL_FIELDS，
                # 也不会被写进数据库（入库前 edited 只取 6 字段）。
                "_confidence": _as_bill_confidence(item.get("confidence")),
            }
        )
    return bills


# ---------------------------------------------------------------------------
# 拒答 / 非记账输入的边界（2026-11-26 按队友复核意见补齐）
# ---------------------------------------------------------------------------

# 明显的越界/诱导请求；AI 侧 prompts.py 已做拒答，界面层再兜一道。
OUT_OF_SCOPE_KEYWORDS = (
    "贷款口子", "找贷款", "借钱", "套现", "绕过额度", "突破额度",
    "破解", "刷单", "赌博", "洗钱", "信用卡套",
)

# 明显的非记账闲聊/问答。句中有数字就直接放行，
# 避免误伤「午饭 25」「昨天打车 32」这类正常记账。
NON_BILL_KEYWORDS = (
    "天气", "讲个笑话", "你是谁", "你好", "几点", "今天日期",
    "翻译", "写作文", "写代码", "新闻", "股价", "陪我聊天", "讲个故事",
)


def _as_bill_confidence(value):
    """T6：把模型给的 confidence 规范成 0~1 的 float；缺失/非法返回 None。"""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 <= number <= 1.0:
        return number
    if 1.0 < number <= 100.0:
        return number / 100.0
    return None


def is_out_of_scope(text: str) -> bool:
    """识别明显的越界/诱导请求，避免 AI 偶发漏拒时仍生成草稿。"""
    return any(word in (text or "") for word in OUT_OF_SCOPE_KEYWORDS)


def is_non_bill_input(text: str) -> bool:
    """识别明显的非记账输入；句中含有数字则一律放行。"""
    if re.search(r"\d", text or ""):
        return False
    return any(word in (text or "") for word in NON_BILL_KEYWORDS)


def bills_from_ai_result(ok: bool, data, msg: str) -> tuple[list[dict], str, str]:
    """
    把 ai_core 的返回转成「可让用户确认的账单草稿」，返回 (bills, level, notice)。

    按队友复核意见覆盖三种情况：
      1. ok=False（拒答 / 非记账 / 调用异常）-> 不弹卡，只返回 msg。
      2. ok=True 但 normalize_bills 为空列表 / 只剩金额<=0 的无效项 -> 也不弹空卡。
      3. 演示数据模式才允许 demo_parse()，那是刻意设计的联调兜底。
    真实模式下 AI 失败一律不生成任何草稿，绝不调用 demo_parse()，
    避免用户把凭空造出的假账单确认入库写进真实数据库。
    """
    # 情况 1
    if not ok or data is None:
        return [], "error", msg or "AI 未能解析这句话，未生成账单草稿，请改写后重试。"

    # 情况 1 的变体：拒答以纯文本或 {"refused": true, ...} 结构返回
    if isinstance(data, str):
        return [], "warning", "这条请求不在记账范围内，已拒绝：" + data[:120]
    if isinstance(data, dict):
        refusal_keys = ("refused", "reject", "rejected", "is_refusal", "error", "refusal")
        if any(str(k).lower() in refusal_keys and v for k, v in data.items()):
            reply = data.get("reply") or data.get("message") or data.get("msg") or ""
            return [], "warning", ("这条请求不在记账范围内，已拒绝：" + str(reply)[:120]) if reply else "这条请求不在记账范围内，已拒绝。"

    bills = normalize_bills(data)
    # 情况 2：空列表 -> 不弹空卡
    if not bills:
        return [], "warning", "AI 未返回可识别的账单（结果为空），未生成草稿，请改写后重试。"
    # 只丢弃「完全空白的假卡」（拒答/半截 JSON 被字段补齐后的产物）。
    # 缺金额但带分类或备注的草稿必须保留：T3 要求「买衣服两百多」弹出卡片、
    # 确认按钮置灰让用户补全，而不是整张卡消失。
    meaningful = [
        b for b in bills
        if b["amount"] > 0
        or str(b.get("merchant") or "").strip()
        or str(b.get("note") or "").strip()
        or str(b.get("category") or "其他") not in ("其他", "", "None")
    ]
    if not meaningful:
        return [], "warning", "AI 未返回有效的账单数据，未生成草稿，请改写后重试。"
    return meaningful, "success", msg or "解析成功，请确认或修正后入库"


def bills_to_frame(bills: list[dict]) -> pd.DataFrame:
    """账单列表转 DataFrame，并派生月份列用于趋势统计。"""
    frame = pd.DataFrame(bills, columns=list(BILL_FIELDS))
    if frame.empty:
        frame["month"] = pd.Series(dtype="str")
        return frame
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce").fillna(0.0)
    frame["month"] = frame["spent_at"].astype(str).str.slice(0, 7)
    return frame


def load_bills(bill_type: str) -> tuple[pd.DataFrame, str]:
    """取某一收支类型的全部账单，返回 (DataFrame, 提示语)。"""
    demo_rows = [b for b in DEMO_BILLS if b["type"] == bill_type]
    if is_demo():
        rows = demo_rows + [b for b in st.session_state["demo_store"] if b["type"] == bill_type]
        return bills_to_frame(rows), "演示数据模式：界面使用内置示例账单"

    ok, data, msg = call_module(db, "list_records", bill_type, default=demo_rows)
    if not ok or data is None:
        rows = demo_rows + [b for b in st.session_state["demo_store"] if b["type"] == bill_type]
        return bills_to_frame(rows), msg or "接口暂不可用，已切换演示数据"
    return bills_to_frame(normalize_bills(data)), msg


def load_all_bills() -> tuple[pd.DataFrame, str]:
    """同时取支出与收入，合并为一张总表。"""
    expense, msg_e = load_bills(TYPE_EXPENSE)
    income, msg_i = load_bills(TYPE_INCOME)
    frame = pd.concat([expense, income], ignore_index=True)
    note = msg_e if "演示" in msg_e or "切换" in msg_e else msg_i
    return frame, note


def show_empty_hint(frame: pd.DataFrame) -> None:
    """真实模式下数据库为空时给出明确引导，避免评审以为程序没跑通。"""
    if is_demo() or not frame.empty:
        return
    st.info("数据库里还没有账单：可在「记一笔」录入，或点侧栏「导入示例账单到数据库」一键载入演示数据。")


def parse_category_rows(data) -> list[dict]:
    """
    把 db.sum_by_category 的返回值规整成 [{"分类":..., "金额":...}, ...]。

    兼容三种形态：
      1. 字典 {"餐饮": 100}                       （接口约定文档描述的形态）
      2. 列表 [{"category":"餐饮","amount":100}]  （若队友后续给 SQL 起了别名）
      3. 列表 [{"category":"餐饮","SUM(amount)":100}]（当前真实实现，SQL 未起别名）
    异常返回的 False / None 会得到空列表，由调用方降级到界面聚合。
    """
    if isinstance(data, bool) or data is None:
        return []
    rows = []
    if isinstance(data, dict) and data:
        for key, value in data.items():
            try:
                rows.append({"分类": str(key), "金额": float(value)})
            except (TypeError, ValueError):
                continue
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            category = item.get("category")
            value = item.get("amount")
            if value is None:
                for key, candidate in item.items():
                    if "sum" in str(key).lower() or "total" in str(key).lower():
                        value = candidate
                        break
            if category is None or value is None:
                continue
            try:
                rows.append({"分类": str(category), "金额": float(value)})
            except (TypeError, ValueError):
                continue
    return rows


def load_category_summary(bill_type: str, frame: pd.DataFrame) -> pd.DataFrame:
    """
    取分类汇总，返回列为 ["分类", "金额"] 的 DataFrame。

    优先调用 db.sum_by_category(type)；接口缺失时从账单明细在界面层聚合，
    保证饼图永远有数据（这部分只是展示用的聚合，不写回数据库）。
    """
    if not is_demo():
        ok, data, _ = call_module(db, "sum_by_category", bill_type, default=None)
        rows = parse_category_rows(data) if ok else []
        if rows:
            return pd.DataFrame(rows)
    subset = frame[frame["type"] == bill_type]
    if subset.empty:
        return pd.DataFrame(columns=["分类", "金额"])
    return (
        subset.groupby("category", as_index=False)["amount"]
        .sum()
        .rename(columns={"category": "分类", "amount": "金额"})
    )


# ---------------------------------------------------------------------------
# 图表组件
# ---------------------------------------------------------------------------


def show_chart(chart) -> None:
    """兼容不同 Streamlit 版本的图表宽度参数（新版 width，旧版 use_container_width）。"""
    try:
        st.altair_chart(chart, width="stretch")
    except TypeError:
        try:
            st.altair_chart(chart, use_container_width=True)
        except TypeError:
            st.altair_chart(chart)


def show_table(frame: pd.DataFrame, container=None) -> None:
    """兼容不同 Streamlit 版本的表格参数，隐藏无意义的行索引。"""
    target = container if container is not None else st
    try:
        target.dataframe(frame, width="stretch", hide_index=True)
    except TypeError:
        try:
            target.dataframe(frame, use_container_width=True, hide_index=True)
        except TypeError:
            target.dataframe(frame)


def show_image(uploaded) -> None:
    """兼容不同 Streamlit 版本的图片宽度参数。"""
    try:
        st.image(uploaded, caption="待识别图片", width="stretch")
    except TypeError:
        try:
            st.image(uploaded, caption="待识别图片", use_container_width=True)
        except TypeError:
            st.image(uploaded, caption="待识别图片")


def render_pie(summary: pd.DataFrame, title: str) -> None:
    """画分类占比饼图。altair 是 Streamlit 自带依赖，无需额外安装。"""
    if summary.empty or summary["金额"].sum() <= 0:
        st.info(f"暂无{title}数据，先记一笔再来看图表吧。")
        return
    try:
        import altair as alt

        chart = (
            alt.Chart(summary)
            .mark_arc(innerRadius=55)
            .encode(
                theta=alt.Theta("金额:Q"),
                color=alt.Color("分类:N", scale=alt.Scale(scheme="category10")),
                tooltip=["分类:N", alt.Tooltip("金额:Q", format=".2f")],
            )
            .properties(title=title)
        )
        show_chart(chart)
    except Exception:
        # 极少数环境 altair 不可用时，用 Streamlit 原生柱状图降级展示
        st.caption("饼图组件不可用，已降级为柱状图")
        st.bar_chart(summary.set_index("分类")["金额"])


def render_trend(frame: pd.DataFrame) -> None:
    """画月度趋势：支出与收入两条线同时展示。"""
    if frame.empty:
        st.info("暂无账单数据。")
        return
    pivot = (
        frame.pivot_table(
            index="month", columns="type", values="amount", aggfunc="sum", fill_value=0.0
        )
        .sort_index()
    )
    for bill_type in BILL_TYPES:
        if bill_type not in pivot.columns:
            pivot[bill_type] = 0.0
    st.line_chart(pivot[list(BILL_TYPES)])
    st.caption("横轴为月份（YYYY-MM），纵轴为金额（元）；两条线分别为支出与收入。")


def type_badge(bill_type: str) -> str:
    """生成收支类型的彩色标签，用于明细卡片。"""
    if bill_type == TYPE_INCOME:
        bg, fg = "#E1F5EE", "#0F6E56"
    else:
        bg, fg = "#FAECE7", "#993C1D"
    label = html.escape(bill_type)
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'padding:2px 10px;border-radius:10px;font-size:12px;">{label}</span>'
    )


# ---------------------------------------------------------------------------
# 页面：记一笔
# ---------------------------------------------------------------------------


def save_uploaded_file(uploaded) -> str:
    """
    把 Streamlit 的 UploadedFile 落盘，返回可传给 ai_core.parse_image 的路径。

    ai_core.parse_image 把 base64 前缀写死为 data:image/jpeg;base64,...，
    若上传 PNG 会与声明的 MIME 不符，视觉模型可能拒收。这里尝试用 Pillow
    （Streamlit 的传递依赖）把图片统一转成 JPEG；转换不可用时原样保存。
    更彻底的做法是请 A 在 ai_core 里按文件后缀动态生成 MIME 前缀。
    """
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = Path(uploaded.name).suffix.lower()
    raw = uploaded.getbuffer()

    if suffix in (".png", ".webp", ".bmp", ".gif"):
        try:
            import io
            from PIL import Image

            image = Image.open(io.BytesIO(bytes(raw)))
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGB")
            target = UPLOAD_DIR / f"receipt_{stamp}.jpg"
            image.save(target, format="JPEG")
            return str(target)
        except Exception:
            pass  # Pillow 不可用或转换失败，退回原图

    target = UPLOAD_DIR / f"receipt_{stamp}{suffix or '.jpg'}"
    target.write_bytes(raw)
    return str(target)


def demo_parse(text: str) -> list[dict]:
    """演示模式下的极简解析器：从一句话里找金额、猜分类，供界面联调使用。"""
    import re

    amount_match = re.search(r"\d+(?:\.\d+)?", text or "")
    amount = float(amount_match.group()) if amount_match else 0.0
    bill_type = TYPE_INCOME if any(k in text for k in ("工资", "兼职", "红包", "理财", "收入")) else TYPE_EXPENSE
    category = "其他"
    for candidate in (INCOME_CATEGORIES if bill_type == TYPE_INCOME else EXPENSE_CATEGORIES):
        if candidate != "其他" and any(
            k in text
            for k in {
                "餐饮": ("饭", "餐", "外卖", "奶茶", "咖啡"),
                "交通": ("打车", "地铁", "公交", "滴滴", "车费"),
                "购物": ("买", "超市", "衣服", "购物"),
                "居住": ("房租", "水电", "住宿"),
                "娱乐": ("电影", "游戏", "玩"),
                "医疗": ("药", "医院", "看病"),
                "工资": ("工资", "薪水"),
                "兼职": ("兼职", "外包"),
                "红包": ("红包",),
                "理财": ("理财", "收益"),
            }.get(candidate, ())
        ):
            category = candidate
            break
    return [
        {
            "amount": amount,
            "category": category,
            "spent_at": date.today().isoformat(),
            "merchant": "",
            "note": text or "",
            "type": bill_type,
        }
    ]


def bump_parse_token() -> None:
    """每解析一次就换一批控件 key。

    为什么必须换：Streamlit 的 selectbox / date_input 带 key 之后会把值记在
    session_state 里，之后即使 index= 传了新的默认值也不生效。
    结果就是——上一笔记的是"支出"，这一笔明明是收入，卡片上却还显示"支出"；
    日期也跟着上一笔走。换个 token 等于换了一批全新的控件。
    """
    st.session_state["parse_token"] = int(st.session_state.get("parse_token", 0)) + 1


def parse_token() -> str:
    return str(st.session_state.get("parse_token", 0))


def set_pending(bills: list[dict], notice: str = "", source: str = SOURCE_TEXT) -> None:
    """T6：给每笔草稿打上来源标签，让「文字输入」和「小票 OCR」在卡片上可区分。"""
    for bill in bills:
        bill.setdefault("_source", source)
    st.session_state["pending_bills"] = bills
    st.session_state["parse_notice"] = notice
    bump_parse_token()


def log_ai_call(raw_input: str, data, ok: bool) -> None:
    """把一次 AI 调用写进 ai_logs 表（本地留痕）。

    为什么放在界面层而不是 ai_core：ai_core 只负责调模型，不该知道数据库；
    由 app 统一决定"这次调用要不要记下来"，和 add_bill 的分层一致。
    演示模式不写，避免把联调数据混进真实账本。
    """
    if is_demo():
        return
    try:
        payload = json.dumps(data, ensure_ascii=False) if ok else f"调用失败：{data}"
    except (TypeError, ValueError):
        payload = str(data)
    call_module(db, "log_ai", str(raw_input or "")[:500], payload[:2000], default=None)


def flash(message: str, kind: str = "success") -> None:
    """把提示存进会话，等下一次 rerun 再显示。

    为什么需要它：原来写完 st.success() 紧接着就 st.rerun()，
    提示还没画到屏幕上就被重跑清掉了 —— 用户点完按钮只看到页面闪一下，
    完全不知道自己到底成功没有。改成"先存起来、下次渲染再显示"。
    """
    st.session_state["flash_message"] = message
    st.session_state["flash_kind"] = kind


def show_flash() -> None:
    """在页面顶部把上一次操作的结果显示出来（显示一次就清掉）。"""
    message = st.session_state.pop("flash_message", "")
    if not message:
        return
    kind = st.session_state.pop("flash_kind", "success")
    render = {"success": st.success, "warning": st.warning, "error": st.error}.get(kind, st.success)
    render(message)


def page_record() -> None:
    st.subheader("记一笔")
    st.caption("一句话记账，或上传小票/支付截图。识别结果需你确认或修正后才入库。")

    mode = st.radio("录入方式", ("一句话记账", "小票 / 截图 OCR"), horizontal=True)

    if mode == "一句话记账":
        text = st.text_input("说出这一笔", placeholder="例如：午饭 25，和同事 AA")
        if st.button("解析", type="primary", key="parse_text"):
            if not text.strip():
                set_pending([], "")
                st.warning("先输入一句话再解析。")
            elif is_out_of_scope(text):
                # 越界请求：界面层兜底，两种模式都不生成草稿
                set_pending([], "")
                st.warning("这条请求不在记账范围内，本应用只处理记账相关输入，已拒绝。")
            elif is_non_bill_input(text):
                # 「今天天气怎么样」这类非记账输入：演示模式下也不走 demo_parse
                set_pending([], "")
                st.warning("这句话不是一笔消费或收入，未生成账单草稿。请用「午饭 25」这样的方式描述。")
            elif is_demo():
                # 演示数据模式才允许 demo_parse 造示例草稿（有意设计），并明确标注
                set_pending(demo_parse(text), "演示模式：使用内置解析器生成示例草稿（非真实 AI 结果）",
                            source=SOURCE_DEMO)
            else:
                ok, data, msg = call_module(ai_core, "parse_text", text, default=None)
                bills, level, notice = bills_from_ai_result(ok, data, msg)
                log_ai_call(text, data if ok else (msg or "解析失败"), bool(ok and bills))
                set_pending(bills, "", source=SOURCE_TEXT)
                if level == "error":
                    st.error(notice)
                elif level == "warning":
                    st.warning(notice)
                elif level == "success":
                    st.caption(notice)
    else:
        uploads = st.file_uploader(
            "上传小票或支付截图（可一次选多张）",
            type=("png", "jpg", "jpeg"),
            accept_multiple_files=True,
        )
        uploads = uploads or []
        # T4：先过滤，避免把 200MB 大图交给 st.image / 视觉模型导致演示卡死。
        accepted = []
        rejected = []
        for file in uploads:
            suffix = Path(file.name).suffix.lower()
            if suffix not in ALLOWED_IMAGE_SUFFIXES:
                rejected.append(f"「{file.name}」不是支持的图片格式（仅 PNG / JPG / JPEG）")
                continue
            try:
                size = len(file.getbuffer())
            except Exception:
                size = int(getattr(file, "size", 0) or 0)
            if size > MAX_UPLOAD_BYTES:
                rejected.append(f"「{file.name}」{size / 1024 / 1024:.1f} MB，超过 {MAX_UPLOAD_MB} MB 上限，已跳过")
                continue
            accepted.append(file)
        uploads = accepted
        for reason in rejected[:3]:
            st.warning(reason)
        if rejected and not uploads:
            st.info("没有可识别的图片，请压缩后重新上传（单张不超过 5 MB）。")
        if uploads:
            preview_cols = st.columns(min(len(uploads), 3))
            for i, file in enumerate(uploads):
                with preview_cols[i % len(preview_cols)]:
                    show_image(file)

        if st.button("识别", type="primary", key="parse_image"):
            if not uploads:
                st.warning("先上传至少一张图片再识别。")
            elif is_demo():
                set_pending(
                    [{
                        "amount": 38.5,
                        "category": "餐饮",
                        "spent_at": date.today().isoformat(),
                        "merchant": "示例小票",
                        "note": "OCR 演示结果",
                        "type": TYPE_EXPENSE,
                    }],
                    "演示模式：返回示例识别结果",
                    source=SOURCE_DEMO,
                )
            else:
                collected: list[dict] = []
                failed: list[str] = []
                for file in uploads:
                    image_path = save_uploaded_file(file)
                    ok, data, msg = call_module(ai_core, "parse_image", image_path, default=None)
                    ok_call = bool(ok and data is not None)
                    log_ai_call(file.name, data if ok_call else (msg or "识别失败"), ok_call)
                    parsed, level, parsed_notice = bills_from_ai_result(ok, data, msg)
                    if parsed:
                        collected.extend(parsed)
                    else:
                        failed.append(f"{file.name}：{parsed_notice or msg or '识别失败'}")
                notice = f"识别成功，共 {len(collected)} 笔" if collected else "识别失败"
                if failed:
                    notice += "；失败 " + "；".join(failed[:2])
                set_pending(collected, notice, source=SOURCE_OCR)

    notice = st.session_state.get("parse_notice", "")
    if notice:
        st.caption(notice)

    pending = st.session_state.get("pending_bills", [])
    if not pending:
        return

    st.divider()
    st.markdown(f"**识别到 {len(pending)} 笔，请确认或修正后入库**")

    edited = []
    token = parse_token()
    for index, bill in enumerate(pending):
        with st.expander(f"第 {index + 1} 笔", expanded=True):
            # T6：置信度与来源标签，回答「AI 凭什么这么归」
            confidence = bill.get("_confidence")
            confidence_text = (f"{confidence * 100:.0f}%" if confidence is not None else "未提供")
            source_text = str(bill.get("_source") or SOURCE_TEXT)
            st.caption(f"来源：{html.escape(source_text)}　|　置信度：{confidence_text}")
            col_a, col_b = st.columns(2)
            bill_type = col_a.selectbox(
                "收支类型",
                BILL_TYPES,
                index=BILL_TYPES.index(bill["type"]) if bill["type"] in BILL_TYPES else 0,
                key=f"type_{token}_{index}",
            )
            amount = col_b.number_input(
                "金额",
                min_value=0.0,
                step=1.0,
                value=float(bill["amount"]),
                key=f"amount_{token}_{index}",
            )
            categories = INCOME_CATEGORIES if bill_type == TYPE_INCOME else EXPENSE_CATEGORIES
            category = col_a.selectbox(
                "分类",
                categories,
                index=categories.index(bill["category"]) if bill["category"] in categories else len(categories) - 1,
                key=f"category_{token}_{index}",
            )
            spent_at = col_b.date_input(
                "消费日期",
                value=date.fromisoformat(bill["spent_at"]) if _valid_date(bill["spent_at"]) else date.today(),
                key=f"date_{token}_{index}",
            )
            merchant = col_a.text_input("商户", value=bill["merchant"], key=f"merchant_{token}_{index}")
            note = col_b.text_input("备注（原话）", value=bill["note"], key=f"note_{token}_{index}")
            # T7：只判「支出」且金额偏大，8000 的工资不触发
            if bill_type == TYPE_EXPENSE and float(amount) > LARGE_EXPENSE_THRESHOLD:
                st.warning(f"金额偏大（¥ {float(amount):,.2f}）：OCR 可能把 24.00 读成 2400，请核对小票。")
            edited.append(
                {
                    "amount": float(amount),
                    "category": category,
                    "spent_at": spent_at.isoformat(),
                    "merchant": merchant,
                    "note": note,
                    "type": bill_type,
                }
            )

    # T3：缺金额时按钮直接置灰，不让用户点了才看到「入库失败」
    missing_amount = [i + 1 for i, b in enumerate(edited) if b["amount"] <= 0]
    if missing_amount:
        st.warning("第 " + "、".join(str(i) for i in missing_amount) + " 笔缺少金额，请补全后再入库。")
    col_ok, col_cancel = st.columns(2)
    if col_ok.button("确认入库", type="primary", disabled=bool(missing_amount)):
        if any(b["amount"] <= 0 for b in edited):
            st.error("存在金额为空或为 0 的记录，已阻止入库，请补全金额后重试。")
        else:
            success, failed, messages = 0, 0, []
            for bill in edited:
                if is_demo():
                    st.session_state["demo_store"].append(bill)
                    success += 1
                    continue
                # db 内部虽已把 add 拆分，界面层统一只走 add_bill 这一个契约入口
                ok, _, msg = call_module(db, "add_bill", bill, default=None)
                if ok:
                    success += 1
                else:
                    failed += 1
                    if msg:
                        messages.append(msg)
            message = ""
            if success:
                message = f"成功入库 {success} 笔"
            if failed:
                message += ("；" if message else "") + f"{failed} 笔入库失败：" + "；".join(messages[:3])
            flash(message, "error" if failed else "success")
            set_pending([], "")
            st.rerun()

    if col_cancel.button("放弃"):
        set_pending([], "")
        st.rerun()


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(str(value)[:10])
        return True
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# 页面：分类统计（支出与收入两张饼图）
# ---------------------------------------------------------------------------


def page_overview() -> None:
    st.subheader("分类统计")
    frame, note = load_all_bills()
    if note:
        st.caption(note)
    show_empty_hint(frame)

    left, right = st.columns(2)
    with left:
        st.markdown("**支出构成**")
        expense_summary = load_category_summary(TYPE_EXPENSE, frame)
        render_pie(expense_summary, "支出分类占比")
        st.metric("支出合计", f"¥ {expense_summary['金额'].sum():,.2f}")
    with right:
        st.markdown("**收入构成**")
        income_summary = load_category_summary(TYPE_INCOME, frame)
        render_pie(income_summary, "收入分类占比")
        st.metric("收入合计", f"¥ {income_summary['金额'].sum():,.2f}")

    st.divider()
    balance = income_summary["金额"].sum() - expense_summary["金额"].sum()
    st.metric("累计结余（收入 - 支出）", f"¥ {balance:,.2f}")

    with st.expander("查看分类汇总明细"):
        col_a, col_b = st.columns(2)
        show_table(expense_summary, col_a)
        show_table(income_summary, col_b)


# ---------------------------------------------------------------------------
# 页面：月度趋势（支出与收入两条线）
# ---------------------------------------------------------------------------


def page_trend() -> None:
    st.subheader("月度趋势")
    frame, note = load_all_bills()
    if note:
        st.caption(note)
    render_trend(frame)

    if not frame.empty:
        monthly = (
            frame.pivot_table(
                index="month", columns="type", values="amount", aggfunc="sum", fill_value=0.0
            )
            .sort_index()
        )
        for bill_type in BILL_TYPES:
            if bill_type not in monthly.columns:
                monthly[bill_type] = 0.0
        monthly = monthly[list(BILL_TYPES)].rename(
            columns={TYPE_EXPENSE: "支出(元)", TYPE_INCOME: "收入(元)"}
        )
        monthly["结余(元)"] = monthly["收入(元)"] - monthly["支出(元)"]
        # 月份是索引，转成普通列，避免隐藏索引后看不到月份
        show_table(monthly.reset_index().rename(columns={"month": "月份"}))


# ---------------------------------------------------------------------------
# 页面：账单明细（卡片带收支类型标签 + 自然语言查账）
# ---------------------------------------------------------------------------


def parse_query_local(text: str) -> dict:
    """
    界面层的轻量查账解析器：把自然语言拆成「时间范围 + 类别 + 收支类型」。

    考核要求自然语言查账必须真正解析时间范围与类别，而不是把问题原样交给模型自由回答。
    ai_core 目前只提供 parse_text / parse_image，没有查账解析函数，因此这里在界面层
    做确定性规则解析，再交给 apply_query_filters 过滤真实入库的数据。
    若 A 后续提供 ai_core.parse_query，page_details 会优先调用模型解析。
    """
    today = date.today()
    result = {"start": "", "end": "", "category": "全部",
              "bill_type": "全部", "top": False, "label": ""}

    # --- 时间范围 ---
    month_match = re.search(r"(20\d{2})\s*[-年/.]\s*(\d{1,2})", text)
    if "上个月" in text or "上月" in text:
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        result["start"] = first_prev.isoformat()
        result["end"] = last_prev.isoformat()
    elif "这个月" in text or "本月" in text or "当月" in text:
        first_this = today.replace(day=1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        result["start"] = first_this.isoformat()
        result["end"] = today.replace(day=last_day).isoformat()
    elif "今年" in text:
        result["start"] = date(today.year, 1, 1).isoformat()
        result["end"] = date(today.year, 12, 31).isoformat()
    elif month_match:
        year, month = int(month_match.group(1)), int(month_match.group(2))
        if 1 <= month <= 12:
            last_day = calendar.monthrange(year, month)[1]
            result["start"] = date(year, month, 1).isoformat()
            result["end"] = date(year, month, last_day).isoformat()
    else:
        days_match = re.search(r"近\s*(\d+)\s*天|最近\s*(\d+)\s*天", text)
        if days_match:
            days = int(days_match.group(1) or days_match.group(2))
            result["start"] = (today - timedelta(days=days - 1)).isoformat()
            result["end"] = today.isoformat()

    # --- 类别关键词 ---
    category_keywords = {
        "餐饮": ("吃饭", "餐饮", "午饭", "晚饭", "外卖", "奶茶", "食堂"),
        "交通": ("打车", "交通", "地铁", "公交", "滴滴", "车费"),
        "购物": ("购物", "买东西", "淘宝", "超市", "衣服"),
        "居住": ("房租", "居住", "水电", "住宿"),
        "娱乐": ("娱乐", "电影", "游戏", "玩", "旅游"),
        "医疗": ("医疗", "看病", "买药", "医院"),
        "工资": ("工资", "薪水"),
        "兼职": ("兼职", "外快"),
        "红包": ("红包",),
        "理财": ("理财", "收益"),
    }
    for cat, words in category_keywords.items():
        if any(word in text for word in words):
            result["category"] = cat
            break

    # --- 收支类型 ---
    if any(word in text for word in ("收入", "赚了", "进账", "工资", "红包")):
        result["bill_type"] = TYPE_INCOME
    elif any(word in text for word in ("花了", "支出", "消费", "用了")):
        result["bill_type"] = TYPE_EXPENSE

    # --- "哪类花得最多" ---
    if any(word in text for word in ("最多", "哪类", "最高", "占比", "排行")):
        result["top"] = True

    parts = []
    if result["start"]:
        parts.append(f"{result['start']} ~ {result['end']}")
    if result["category"] != "全部":
        parts.append(result["category"])
    if result["bill_type"] != "全部":
        parts.append(result["bill_type"])
    if result["top"]:
        parts.append("按类别排序")
    result["label"] = " / ".join(parts) if parts else "未识别出条件，显示全部"
    return result


def apply_query_filters(frame: pd.DataFrame, start: str, end: str,
                        bill_type: str, category: str) -> pd.DataFrame:
    """按时间范围、收支类型、分类过滤账单。"""
    result = frame.copy()
    if start:
        result = result[result["spent_at"] >= start]
    if end:
        result = result[result["spent_at"] <= end]
    if bill_type != "全部":
        result = result[result["type"] == bill_type]
    if category != "全部":
        result = result[result["category"] == category]
    return result


def page_details() -> None:
    st.subheader("账单明细")
    frame, note = load_all_bills()
    if note:
        st.caption(note)

    # 自然语言查账：优先用 A 的 parse_query（若已提供），否则用界面层规则解析器。
    # 解析结果存入 session_state，保证 Streamlit rerun 后筛选条件不丢失。
    if "query_filter" not in st.session_state:
        st.session_state["query_filter"] = None

    query = st.text_input("用一句话查账", placeholder="例如：我上个月吃饭花了多少？")
    if st.button("查询") and query.strip():
        parsed = None
        if not is_demo():
            ok, data, _ = call_module(ai_core, "parse_query", query, default=None)
            if ok and isinstance(data, dict):
                parsed = {
                    "start": str(data.get("start") or "")[:10],
                    "end": str(data.get("end") or "")[:10],
                    "category": str(data.get("category") or "全部"),
                    "bill_type": str(data.get("type") or "全部"),
                    "top": bool(data.get("top")),
                    "label": "模型解析",
                }
        if parsed is None:
            parsed = parse_query_local(query)
        st.session_state["query_filter"] = parsed

    if st.button("清除查询条件"):
        st.session_state["query_filter"] = None
        st.rerun()

    active = st.session_state.get("query_filter")
    if active:
        st.success(f"已解析：{active['label']}")

    all_categories = ("全部",) + tuple(sorted(set(EXPENSE_CATEGORIES + INCOME_CATEGORIES)))

    def default_index(options, value):
        try:
            return list(options).index(value)
        except ValueError:
            return 0

    col1, col2, col3, col4 = st.columns(4)
    start = col1.text_input("起始日期", value=(active or {}).get("start", ""),
                            placeholder="2026-11-01")
    end = col2.text_input("结束日期", value=(active or {}).get("end", ""),
                          placeholder="2026-11-30")
    bill_types = ("全部",) + BILL_TYPES
    bill_type = col3.selectbox("收支类型", bill_types,
                               index=default_index(bill_types, (active or {}).get("bill_type", "全部")))
    category = col4.selectbox("分类", all_categories,
                              index=default_index(all_categories, (active or {}).get("category", "全部")))

    filtered = apply_query_filters(frame, start, end, bill_type, category)
    filtered = filtered.sort_values("spent_at", ascending=False)

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("笔数", len(filtered))
    col_m2.metric("支出", f"¥ {filtered[filtered['type'] == TYPE_EXPENSE]['amount'].sum():,.2f}")
    col_m3.metric("收入", f"¥ {filtered[filtered['type'] == TYPE_INCOME]['amount'].sum():,.2f}")

    # T1：导出当前筛选结果。utf-8-sig 带 BOM，Excel 直接打开中文不乱码。
    csv_bytes = filtered[list(BILL_FIELDS)].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "导出 CSV（当前筛选结果）",
        data=csv_bytes,
        file_name=f"账单明细_{date.today().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        key="export_csv",
    )

    # T2：明细逐笔累加（pandas）vs 统计页分类合计（真实模式走 db.sum_by_category）。
    # 两条独立路径比对，专门回答「被要求对账时」的一键结论。
    if st.button("对账自检", key="reconcile"):
        lines = []
        for check_type in BILL_TYPES:
            detail = float(frame[frame["type"] == check_type]["amount"].sum())
            summary = load_category_summary(check_type, frame)
            stat = float(summary["金额"].sum()) if not summary.empty else 0.0
            diff = detail - stat
            if abs(diff) < 0.01:
                lines.append(f"{check_type}：一致（¥ {detail:,.2f}）")
            else:
                lines.append(f"{check_type}：差异 ¥ {diff:,.2f}"
                             f"（明细 ¥ {detail:,.2f} / 统计 ¥ {stat:,.2f}）")
        if all("一致" in line for line in lines):
            st.success("对账一致　" + "；".join(lines))
        else:
            st.error("对账不一致　" + "；".join(lines))

    # "哪类花得最多"：给出按类别降序的真实统计，而不是把问题丢给模型自由回答
    if active and active.get("top") and not filtered.empty:
        st.markdown("**按类别排序**")
        ranking = (
            filtered.groupby("category", as_index=False)["amount"]
            .sum()
            .sort_values("amount", ascending=False)
            .rename(columns={"category": "分类", "amount": "金额"})
        )
        st.bar_chart(ranking.set_index("分类")["金额"])
        top_row = ranking.iloc[0]
        st.caption(f"花得最多的类别是「{top_row['分类']}」，合计 ¥ {float(top_row['金额']):,.2f}")

    st.divider()
    st.markdown("**账目卡片**")
    if filtered.empty:
        st.info("没有符合条件的账单。")
        return

    for _, row in filtered.head(50).iterrows():
        with st.container(border=True):
            c_left, c_mid, c_right = st.columns([2, 4, 2])
            c_left.markdown(f"**{html.escape(str(row['spent_at']))}**")
            c_left.markdown(type_badge(str(row["type"])), unsafe_allow_html=True)
            c_mid.markdown(
                f"**{html.escape(str(row['merchant']) or '未填写商户')}** "
                f"· {html.escape(str(row['category']))}"
            )
            if row["note"]:
                c_mid.caption(html.escape(str(row["note"])))
            sign = "+" if row["type"] == TYPE_INCOME else "-"
            c_right.markdown(f"### {sign} ¥ {float(row['amount']):,.2f}")

    if len(filtered) > 50:
        st.caption(f"仅展示最近 50 笔，共 {len(filtered)} 笔。完整数据见下方表格。")

    with st.expander("表格视图（全部字段）"):
        show_table(filtered[list(BILL_FIELDS)])

    with st.expander("AI 调用记录（最近 10 次）"):
        st.caption("每次「解析 / 识别」都会在这里留一条：你说了什么、模型返回了什么。"
                   "记录只存在本地 ledger.db 的 ai_logs 表里，答辩前可以清空。")
        ok_log, logs, _ = call_module(db, "get_ai_logs", 10, default=None)
        if not ok_log or not logs:
            st.caption("还没有记录。去「记一笔」解析一次，就会出现在这里。")
        else:
            st.dataframe(pd.DataFrame(logs), width="stretch", hide_index=True)
            if st.button("清空这些记录", key="clear_ai_logs"):
                call_module(db, "clear_ai_logs", default=None)
                st.rerun()


# ---------------------------------------------------------------------------
# 页面：预算与超支提醒
# ---------------------------------------------------------------------------


def get_budget_value(category: str, month: str):
    """
    读取预算：真实模式走 db.get_budget，演示模式读内存字典。

    db.get_budget 返回 {"ok":True,"data":{"category","limit_amount","month"},"msg":...}，
    未设置时返回 ok=False；异常时返回裸 False。金额字段是 limit_amount，不是 amount。
    """
    if is_demo():
        return st.session_state["demo_budgets"].get((category, month))
    ok, data, _ = call_module(db, "get_budget", category, month, default=None)
    if not ok or data is None:
        return None
    if isinstance(data, dict):
        for key in ("limit_amount", "amount", "budget"):
            if key in data:
                return data[key]
        return None
    return data


def page_budget() -> None:
    st.subheader("预算与超支提醒")
    st.caption("可为分类或总额设定月度预算；接近（80%）或超出预算时给出提醒。")

    col_m, col_c, col_a = st.columns(3)
    month = col_m.text_input("预算月份", value=date.today().strftime("%Y-%m"), placeholder="2026-11")
    budget_categories = ("总额",) + EXPENSE_CATEGORIES
    category = col_c.selectbox("预算对象", budget_categories)
    amount = col_a.number_input("预算金额", min_value=0.0, step=50.0, value=600.0)

    if st.button("保存预算", type="primary"):
        if is_demo():
            st.session_state["demo_budgets"][(category, month)] = float(amount)
            st.success(f"已设置 {month} {category} 预算 ¥ {amount:,.2f}（演示数据）")
        else:
            ok, _, msg = call_module(db, "set_budget", category, float(amount), month, default=None)
            st.success(msg or "预算已保存") if ok else st.error(msg or "预算保存失败，请检查 db.set_budget")

    st.divider()
    expense_frame, _ = load_bills(TYPE_EXPENSE)
    current = expense_frame[expense_frame["month"] == month]

    st.markdown("**本月预算执行情况**")
    # 说明：超支判定本应由 D 的 logic.py 提供；该模块目前缺失，
    # 这里在界面层做只读的降级判断，待 D 提供规则函数后替换。
    for target in budget_categories:
        budget = get_budget_value(target, month)
        if budget is None:
            continue
        try:
            budget = float(budget)
        except (TypeError, ValueError):
            continue
        spent = float(current["amount"].sum()) if target == "总额" else float(
            current[current["category"] == target]["amount"].sum()
        )
        ratio = spent / budget if budget > 0 else 0.0
        col_x, col_y = st.columns([3, 1])
        col_x.markdown(f"**{target}**　预算 ¥ {budget:,.2f}　已花 ¥ {spent:,.2f}")
        col_y.progress(min(ratio, 1.0))
        if ratio >= 1.0:
            st.error(f"{target} 已超支 ¥ {spent - budget:,.2f}，建议控制后续支出。")
        elif ratio >= 0.8:
            st.warning(f"{target} 已用掉 {ratio * 100:.0f}% 预算，接近上限。")
        else:
            st.caption(f"{target} 使用进度 {ratio * 100:.0f}%，状态正常。")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


@st.cache_resource
def bootstrap() -> str:
    """应用启动时初始化一次数据库；队友模块未就绪时跳过，不阻塞界面。"""
    if db is None or not callable(getattr(db, "init_db", None)):
        return "数据库模块尚未就绪，已跳过初始化"
    ok, _, msg = call_module(db, "init_db", default=None)
    if ok:
        return "数据库已连接（ledger.db）"
    return msg or "数据库初始化失败"


def import_demo_to_db() -> tuple[int, int, int]:
    """
    重置演示数据：先清空 bills 表，再写入内置的 16 笔示例账单。

    返回 (写入成功数, 失败数, 清空数)。注意是"清空再写"，不是"追加"。

    以前是只插不删，点一次多 16 笔，点十几次就成了 200 多笔、支出合计几十万。
    现在优先调用 db.reset_demo_bills()，它在一个事务里完成「删+写」：
    两个标签页同时点、或者手快连点两下，后到的请求会排队，不会交错成 31 笔。
    """
    # 首选：原子版本（一个事务里先清空再整批写入）
    ok_all, result, _ = call_module(db, "reset_demo_bills", DEMO_BILLS, default=None)
    if ok_all and isinstance(result, (tuple, list)) and len(result) == 2:
        return int(result[0]), 0, int(result[1])

    # 兜底：老版本 db.py 没有这个函数时，退回"先清空再逐条写"（并发下可能交错，仅作降级）
    ok_clear, deleted, _ = call_module(db, "clear_all_bills", default=None)
    if not ok_clear:
        return 0, 0, 0
    deleted = int(deleted or 0)

    success = failed = 0
    for bill in DEMO_BILLS:
        payload = dict(bill)
        payload["is_demo"] = 1      # 标记成演示数据，之后可以一键只清这部分
        ok, _, _ = call_module(db, "add_bill", payload, default=None)
        success += 1 if ok else 0
        failed += 0 if ok else 1
    return success, failed, deleted


def hide_dev_toolbar() -> None:
    """T5 兜底：即使 .streamlit/config.toml 没被打包进镜像，也隐藏开发机工具栏。"""
    st.markdown(
        """<style>
        [data-testid="stToolbar"] { display: none !important; }
        #MainMenu { visibility: hidden !important; }
        footer { visibility: hidden !important; }
        header { visibility: hidden !important; }
        [data-testid="stStatusWidget"] { display: none !important; }
        </style>""",
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="个人记账与消费分析 AI 助手", page_icon="¥", layout="wide")
    hide_dev_toolbar()
    init_state()

    st.title("个人记账与消费分析 AI 助手")
    st.caption("一句话记账 / 小票 OCR / 自动分类 / 自然语言查账 / 预算提醒")
    show_flash()

    with st.sidebar:
        st.header("运行状态")
        st.checkbox(
            "使用演示数据（联调模式）",
            key="use_demo",
            help="勾选后界面使用内置示例账单，不依赖 ai_core / db，可独立跑通全部流程",
        )
        st.caption(bootstrap())
        st.caption(f"ai_core：{'已加载' if ai_core else '未就绪'}"
                   f"　db：{'已加载' if db else '未就绪'}")
        # 真实条数：不要用写死的"已初始化"当证据，这里读的是数据库里的实际行数
        if not is_demo():
            ok_n, n_bills, _ = call_module(db, "count_bills", default=None)
            if ok_n and isinstance(n_bills, int):
                st.caption(f"当前账本：{n_bills} 笔")

        # 显示导入失败原因，最常见是 .env 里缺 ZHIPU_API_KEY 导致 OpenAI 初始化失败
        if AI_CORE_IMPORT_ERROR:
            with st.expander("ai_core 加载失败原因"):
                st.code(AI_CORE_IMPORT_ERROR)
                st.caption("检查 .env 是否配置了 ZHIPU_API_KEY，以及 prompts.py / openai 是否可用。")
        if DB_IMPORT_ERROR:
            with st.expander("db 加载失败原因"):
                st.code(DB_IMPORT_ERROR)

        if is_demo():
            st.info("当前为演示数据模式。取消勾选可切换到队友的真实接口。")
        else:
            st.divider()
            st.markdown("**演示数据**")
            st.caption("「重置演示数据」会先清空 bills 表，再写入 16 笔示例账单。"
                       "点几次结果都是 16 笔，不会叠加。")
            if st.button("重置演示数据（清空后写入 16 笔）", type="primary"):
                ok_count, fail_count, deleted = import_demo_to_db()
                if fail_count:
                    flash(f"已清空 {deleted} 笔，写入 {ok_count} 笔，"
                          f"失败 {fail_count} 笔，请检查 db.add_bill", "warning")
                else:
                    flash(f"已清空 {deleted} 笔，重新写入 {ok_count} 笔")
                st.rerun()

            if st.button("清空全部账单（含手记）"):
                ok_clear, cleared, msg = call_module(db, "clear_all_bills", default=None)
                if ok_clear and isinstance(cleared, int):
                    flash(f"已清空 {cleared} 笔账单")
                else:
                    flash(f"清空失败：{msg}", "error")
                st.rerun()

        st.divider()
        st.caption("启动命令：streamlit run app.py")
        st.caption("API Key 放在本地 .env（ZHIPU_API_KEY），切勿提交进仓库。")

    tabs = st.tabs(["记一笔", "分类统计", "月度趋势", "账单明细", "预算与提醒"])
    with tabs[0]:
        page_record()
    with tabs[1]:
        page_overview()
    with tabs[2]:
        page_trend()
    with tabs[3]:
        page_details()
    with tabs[4]:
        page_budget()


if __name__ == "__main__":
    main()
