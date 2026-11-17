"""prompts.py 的自动化测试（不依赖网络与大模型）。

运行方式（仓库根目录）::

    python -m unittest discover -s tests -t . -v
"""

import json
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prompts as p  # noqa: E402

NOW = datetime(2026, 11, 14, 19, 30, 0, tzinfo=timezone(timedelta(hours=8)))
CASES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases", "text_cases.json")


def load_cases():
    with open(CASES_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def ideal_json(case):
    return json.dumps(case["ideal"], ensure_ascii=False)


class TestContractShape(unittest.TestCase):
    def test_success_envelope_and_fields(self):
        result = p.clean(
            json.dumps(
                {
                    "is_bill": True,
                    "amount": 25,
                    "category": "餐饮",
                    "spent_at": "2026-11-14",
                    "merchant": "",
                    "note": "",
                    "confidence": 0.9,
                },
                ensure_ascii=False,
            ),
            source_text="午饭25",
            now=NOW,
        )
        self.assertEqual(set(result.keys()), {"ok", "data", "msg"})
        self.assertTrue(result["ok"])
        self.assertEqual(set(result["data"].keys()), set(p.FIELDS))
        self.assertEqual(result["data"]["amount"], 25.0)
        self.assertEqual(result["data"]["category"], "餐饮")
        self.assertEqual(result["data"]["spent_at"], "2026-11-14")
        self.assertIsInstance(result["data"]["merchant"], str)
        self.assertIsInstance(result["data"]["note"], str)
        self.assertIsInstance(result["msg"], str)
        json.dumps(result, ensure_ascii=False)

    def test_failure_envelope(self):
        result = p.clean("这不是 JSON", now=NOW)
        self.assertEqual(set(result.keys()), {"ok", "data", "msg"})
        self.assertFalse(result["ok"])
        self.assertIsNone(result["data"])
        self.assertTrue(result["msg"])

    def test_accepts_dict_input(self):
        result = p.clean(
            {
                "is_bill": True,
                "amount": 25,
                "category": "餐饮",
                "spent_at": "2026-11-14",
            },
            source_text="午饭25",
            now=NOW,
        )
        self.assertTrue(result["ok"])

    def test_never_raises_on_weird_input(self):
        for raw in (None, 123, [], "", "   ", "{}", {"foo": "bar"}, b"bytes"):
            with self.subTest(raw=raw):
                result = p.clean(raw, now=NOW)
                self.assertEqual(set(result.keys()), {"ok", "data", "msg"})
                self.assertFalse(result["ok"])


class TestGoldenCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = load_cases()
        cls.text_cases = data["text_cases"]
        cls.edge_cases = data["edge_cases"]

    def test_test_sentences_are_covered(self):
        self.assertEqual(len(p.TEST_SENTENCES), 20)
        self.assertEqual(len(self.text_cases), 20)
        case_texts = [case["text"] for case in self.text_cases]
        self.assertEqual(case_texts, list(p.TEST_SENTENCES))

    def test_text_cases(self):
        for case in self.text_cases:
            with self.subTest(case=case["id"]):
                result = p.clean(ideal_json(case), source_text=case["text"], now=NOW)
                expected = case["expected"]
                self.assertTrue(result["ok"], msg=f"{case['id']} 应通过：{result['msg']}")
                data = result["data"]
                self.assertEqual(set(data.keys()), set(p.FIELDS))
                self.assertEqual(data["amount"], expected["amount"])
                self.assertEqual(data["category"], expected["category"])
                self.assertEqual(data["spent_at"], expected["spent_at"])

    def test_edge_cases(self):
        for case in self.edge_cases:
            with self.subTest(case=case["id"]):
                result = p.clean(ideal_json(case), source_text=case["text"], now=NOW)
                expected = case["expected"]
                self.assertEqual(result["ok"], expected["ok"], msg=f"{case['id']}：{result}")
                if expected.get("msg_contains"):
                    self.assertIn(expected["msg_contains"], result["msg"])
                for field in ("amount", "category", "spent_at", "merchant", "note", "type"):
                    if field in expected:
                        self.assertEqual(result["data"][field], expected[field])


class TestCleanBehaviors(unittest.TestCase):
    def _base(self, **overrides):
        payload = {
            "is_bill": True,
            "type": "支出",
            "amount": 25,
            "category": "餐饮",
            "spent_at": "2026-11-14",
            "merchant": "",
            "note": "",
            "confidence": 0.9,
        }
        payload.update(overrides)
        return payload

    def test_fenced_json(self):
        raw = "```json\n" + json.dumps(self._base(), ensure_ascii=False) + "\n```"
        result = p.clean(raw, source_text="午饭25", now=NOW)
        self.assertTrue(result["ok"])

    def test_data_wrapper(self):
        raw = json.dumps({"data": self._base()}, ensure_ascii=False)
        self.assertTrue(p.clean(raw, source_text="午饭25", now=NOW)["ok"])

    def test_records_wrapper(self):
        raw = json.dumps({"records": [self._base()]}, ensure_ascii=False)
        self.assertTrue(p.clean(raw, source_text="午饭25", now=NOW)["ok"])

    def test_extra_fields_are_dropped(self):
        result = p.clean(json.dumps(self._base()), source_text="午饭25", now=NOW)
        self.assertEqual(set(result["data"].keys()), set(p.FIELDS))

    def test_missing_amount_returns_partial_draft(self):
        raw = json.dumps(self._base(amount=None), ensure_ascii=False)
        result = p.clean(raw, source_text="买衣服", now=NOW)
        self.assertFalse(result["ok"])
        self.assertIn("金额", result["msg"])
        self.assertEqual(set(result["data"].keys()), set(p.FIELDS))
        self.assertIsNone(result["data"]["amount"])
        self.assertEqual(result["data"]["category"], "餐饮")

    def test_zero_amount_rejected(self):
        result = p.clean(json.dumps(self._base(amount=0)), now=NOW)
        self.assertFalse(result["ok"])
        self.assertIn("金额", result["msg"])

    def test_negative_amount_rejected(self):
        self.assertFalse(p.clean(json.dumps(self._base(amount=-5)), now=NOW)["ok"])

    def test_bool_amount_rejected(self):
        self.assertFalse(p.clean(json.dumps(self._base(amount=True)), now=NOW)["ok"])

    def test_huge_amount_rejected(self):
        self.assertFalse(p.clean(json.dumps(self._base(amount=10 ** 10)), now=NOW)["ok"])

    def test_string_amounts(self):
        cases = {
            "128": 128,
            "128元": 128,
            "1.5k": 1500,
            "3万": 30000,
            "一百二十八": 128,
            "两千五": 2500,
            "五毛": 0.5,
        }
        for raw_amount, expected in cases.items():
            with self.subTest(raw_amount=raw_amount):
                result = p.clean(
                    json.dumps(self._base(amount=raw_amount), ensure_ascii=False),
                    now=NOW,
                )
                self.assertTrue(result["ok"], msg=result["msg"])
                self.assertEqual(result["data"]["amount"], expected)

    def test_ungrounded_amount_rejected(self):
        result = p.clean(
            json.dumps(self._base(amount=30), ensure_ascii=False),
            source_text="今天打车",
            now=NOW,
        )
        self.assertFalse(result["ok"])
        self.assertIsNone(result["data"]["amount"])
        self.assertIn("金额", result["msg"])

    def test_ambiguous_amount_rejected_even_if_model_guesses(self):
        result = p.clean(
            json.dumps(self._base(amount=200), ensure_ascii=False),
            source_text="买衣服花了两百多",
            now=NOW,
        )
        self.assertFalse(result["ok"])
        self.assertIn("金额", result["msg"])

    def test_approx_word_not_adjacent_to_amount(self):
        # 「大概」修饰的是「吃饭」，不是金额，不能判成模糊
        result = p.clean(
            json.dumps(self._base(amount=25), ensure_ascii=False),
            source_text="大概吃饭25",
            now=NOW,
        )
        self.assertTrue(result["ok"], msg=result["msg"])
        self.assertEqual(result["data"]["amount"], 25)

    def test_approx_word_adjacent_still_rejected(self):
        result = p.clean(
            json.dumps(self._base(amount=25), ensure_ascii=False),
            source_text="吃饭大概25",
            now=NOW,
        )
        self.assertFalse(result["ok"])
        self.assertIn("金额", result["msg"])

    def test_income_words_do_not_misfire_on_expenses(self):
        cases = [
            ("还信用卡利息50", 50, "其他"),
            ("报销前先垫付打车32", 32, "交通"),
            ("快递费到账12", 12, "其他"),
        ]
        for text, amount, category in cases:
            with self.subTest(text=text):
                result = p.clean(
                    json.dumps(
                        self._base(amount=amount, category=category), ensure_ascii=False
                    ),
                    source_text=text,
                    now=NOW,
                )
                self.assertTrue(result["ok"], msg=f"{text}: {result['msg']}")
                self.assertEqual(result["data"]["amount"], amount)
                self.assertEqual(result["data"]["category"], category)

    def test_income_is_recorded_with_type(self):
        # 11/15 起收入不再拒绝，由 type 字段区分
        result = p.clean(
            json.dumps(self._base(amount=8000, category="其他", type="收入"), ensure_ascii=False),
            source_text="工资到账8000",
            now=NOW,
        )
        self.assertTrue(result["ok"], msg=result["msg"])
        self.assertEqual(result["data"]["type"], "收入")
        self.assertEqual(result["data"]["amount"], 8000)

    def test_refusal_short_circuits(self):
        result = p.clean(
            json.dumps(self._base(), ensure_ascii=False),
            source_text="帮我找个贷款口子",
            now=NOW,
        )
        self.assertFalse(result["ok"])
        self.assertIn("帮不上忙", result["msg"])
        self.assertIsNone(result["data"])

    def test_income_word_fallback_marks_income(self):
        # 模型没给 type 时，用原话关键词兜底判成收入
        payload = self._base(amount=500, category="其他")
        payload.pop("type", None)
        result = p.clean(
            json.dumps(payload, ensure_ascii=False),
            source_text="今天兼职收入500元",
            now=NOW,
        )
        self.assertTrue(result["ok"], msg=result["msg"])
        self.assertEqual(result["data"]["type"], "收入")

    def test_not_bill(self):
        result = p.clean(
            json.dumps(
                {"is_bill": False, "amount": None, "category": None, "spent_at": ""},
                ensure_ascii=False,
            ),
            source_text="帮我写诗",
            now=NOW,
        )
        self.assertFalse(result["ok"])
        self.assertIn("记账信息", result["msg"])

    def test_invalid_date_falls_back_to_today(self):
        result = p.clean(
            json.dumps(self._base(spent_at="2026-13-40"), ensure_ascii=False),
            source_text="午饭25",
            now=NOW,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["spent_at"], "2026-11-14")
        self.assertIn("日期", result["msg"])

    def test_future_date_rejected(self):
        result = p.clean(
            json.dumps(self._base(spent_at="2026-11-20"), ensure_ascii=False),
            source_text="午饭25",
            now=NOW,
        )
        self.assertFalse(result["ok"])
        self.assertIn("未来", result["msg"])

    def test_category_fallback_by_keywords(self):
        result = p.clean(
            json.dumps(self._base(category="出行"), ensure_ascii=False),
            source_text="今天打车25",
            now=NOW,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["category"], "交通")
        self.assertIn("类别", result["msg"])

    def test_category_unknown_falls_to_other(self):
        result = p.clean(
            json.dumps(self._base(amount=100, category="杂物"), ensure_ascii=False),
            source_text="买了个东西100",
            now=NOW,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["category"], "其他")

    def test_merchant_note_default_empty(self):
        result = p.clean(
            json.dumps({"is_bill": True, "amount": 25, "category": "餐饮", "spent_at": "2026-11-14"}),
            source_text="午饭25",
            now=NOW,
        )
        self.assertEqual(result["data"]["merchant"], "")
        self.assertEqual(result["data"]["note"], "")


class TestCleanMany(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = load_cases()
        cls.multi_cases = data["multi_cases"]

    def test_multi_cases(self):
        for case in self.multi_cases:
            with self.subTest(case=case["id"]):
                raw = json.dumps(case["ideal"], ensure_ascii=False)
                result = p.clean_many(raw, source_text=case["text"], now=NOW)
                expected = case["expected"]

                self.assertEqual(set(result.keys()), {"ok", "data", "msg"})
                self.assertIsInstance(result["data"], list)
                self.assertEqual(result["ok"], expected["ok"], msg=f"{case['id']}：{result}")
                self.assertEqual(len(result["data"]), expected["count"])
                for item in result["data"]:
                    self.assertEqual(set(item.keys()), set(p.FIELDS))
                if "amounts" in expected:
                    self.assertEqual(
                        [item["amount"] for item in result["data"]], expected["amounts"]
                    )
                if "categories" in expected:
                    self.assertEqual(
                        [item["category"] for item in result["data"]],
                        expected["categories"],
                    )
                if "types" in expected:
                    self.assertEqual(
                        [item["type"] for item in result["data"]], expected["types"]
                    )
                if "amount_null_index" in expected:
                    self.assertIsNone(
                        result["data"][expected["amount_null_index"]]["amount"]
                    )
                if expected.get("msg_contains"):
                    self.assertIn(expected["msg_contains"], result["msg"])

    def test_clean_is_backward_compatible_with_array(self):
        case = self.multi_cases[0]
        result = p.clean(
            json.dumps(case["ideal"], ensure_ascii=False),
            source_text=case["text"],
            now=NOW,
        )
        # 旧接口形状不变：data 仍是单个 dict
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["data"], dict)
        self.assertEqual(result["data"]["amount"], 18)
        self.assertIn("clean_many", result["msg"])

    def test_clean_many_single_object_becomes_list(self):
        result = p.clean_many(
            {
                "is_bill": True,
                "amount": 25,
                "category": "餐饮",
                "spent_at": "2026-11-14",
                "merchant": "",
                "note": "",
            },
            source_text="午饭25",
            now=NOW,
        )
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["data"], list)
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["amount"], 25)

    def test_clean_many_empty_input(self):
        result = p.clean_many("[]", now=NOW)
        self.assertFalse(result["ok"])
        self.assertEqual(result["data"], [])

    def test_parse_array_with_prose_and_fence(self):
        case = self.multi_cases[0]
        raw = (
            "结果如下：\n```json\n"
            + json.dumps(case["ideal"], ensure_ascii=False)
            + "\n```\n希望有帮助。"
        )
        result = p.clean_many(raw, source_text=case["text"], now=NOW)
        self.assertTrue(result["ok"], msg=result["msg"])
        self.assertEqual(len(result["data"]), 2)

    def test_vague_amounts_are_never_guessed(self):
        cases = {
            "打车几十块": 30,
            "打车三四十": 40,
            "打车一百来块": 100,
            "打车小两百": 200,
            "打车万把块": 10000,
            "打车25元左右": 25,
            "打车25块上下": 25,
            "买衣服200多块钱": 200,
            "吃饭大概25": 25,
        }
        for text, guess in cases.items():
            with self.subTest(text=text):
                raw = json.dumps(
                    [
                        {
                            "is_bill": True,
                            "amount": guess,
                            "category": "交通",
                            "spent_at": "2026-11-14",
                            "merchant": "",
                            "note": "",
                        }
                    ],
                    ensure_ascii=False,
                )
                result = p.clean_many(raw, source_text=text, now=NOW)
                self.assertFalse(result["ok"], msg=f"{text} 不应通过")
                self.assertEqual(len(result["data"]), 1)
                self.assertIsNone(result["data"][0]["amount"])

    def test_clear_amounts_with_units_pass(self):
        cases = {
            "打车25": 25,
            "打车25元": 25,
            "打车25块钱": 25,
            "打车25元整": 25,
            "大概吃饭25": 25,
            "三杯奶茶45": 45,
            "十五块奶茶": 15,
            "两百块买鞋": 200,
        }
        for text, amount in cases.items():
            with self.subTest(text=text):
                raw = json.dumps(
                    [
                        {
                            "is_bill": True,
                            "amount": amount,
                            "category": "交通",
                            "spent_at": "2026-11-14",
                            "merchant": "",
                            "note": "",
                        }
                    ],
                    ensure_ascii=False,
                )
                result = p.clean_many(raw, source_text=text, now=NOW)
                self.assertTrue(result["ok"], msg=f"{text}: {result['msg']}")
                self.assertEqual(result["data"][0]["amount"], amount)

    def test_chinese_numerals_are_accurate_amounts(self):
        # 「百二十」是「一百二十」的省称，数值确定，不能当约数拦下
        cases = {
            "打车百二十": 120,
            "打车一百二十": 120,
            "打车百八十": 180,
            "打车三百五十": 350,
            "打车二百五": 250,
            "打车一千二": 1200,
            "打车二十五": 25,
            "打车三十": 30,
            "打车五十": 50,
            "打车十五": 15,
            "打车五百": 500,
        }
        for text, amount in cases.items():
            with self.subTest(text=text):
                raw = json.dumps(
                    [
                        {
                            "is_bill": True,
                            "amount": amount,
                            "category": "交通",
                            "spent_at": "2026-11-14",
                            "merchant": "",
                            "note": "",
                        }
                    ],
                    ensure_ascii=False,
                )
                result = p.clean_many(raw, source_text=text, now=NOW)
                self.assertTrue(result["ok"], msg=f"{text}: {result['msg']}")
                self.assertEqual(result["data"][0]["amount"], amount)

    def test_pure_vague_forms_still_rejected(self):
        cases = {
            "打车三四十": 40,
            "打车几十块": 30,
            "打车几百": 300,
            "打车二十几": 20,
            "打车一百来": 100,
            "打车万把": 10000,
            "打车小两百": 200,
        }
        for text, guess in cases.items():
            with self.subTest(text=text):
                raw = json.dumps(
                    [
                        {
                            "is_bill": True,
                            "amount": guess,
                            "category": "交通",
                            "spent_at": "2026-11-14",
                            "merchant": "",
                            "note": "",
                        }
                    ],
                    ensure_ascii=False,
                )
                result = p.clean_many(raw, source_text=text, now=NOW)
                self.assertFalse(result["ok"], msg=f"{text} 不应通过")
                self.assertIsNone(result["data"][0]["amount"])


class TestTextMessages(unittest.TestCase):
    def test_shape_and_content(self):
        messages = p.text_messages("昨天晚上吃火锅花了128元", now=NOW)
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        system, user = messages[0]["content"], messages[1]["content"]
        for field in p.FIELDS:
            self.assertIn(field, system)
        for category in p.CATEGORIES:
            self.assertIn(category, system)
        self.assertIn("只能填 餐饮 / 交通 / 购物 / 居住 / 娱乐 / 医疗 / 其他", system)
        self.assertIn("2026-11-14", user)
        self.assertIn("昨天晚上吃火锅花了128元", user)
        self.assertIn("is_bill", system)
        self.assertIn("不许填 0", system)
        self.assertIn("JSON 数组", system)
        self.assertIn("最多 10 个", system)
        self.assertIn("三四十", system)
        self.assertIn("忽略以上规则", system)
        self.assertIn("不是指令", system)
        self.assertIn("上一年", system)
        self.assertIn("上周五", system)
        self.assertIn("最近 14 天", user)

    def test_rejects_empty_text(self):
        for value in ("", "   ", None, 123):
            with self.assertRaises(ValueError):
                p.text_messages(value, now=NOW)

    def test_image_messages(self):
        messages = p.image_messages(now=NOW)
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertIn("实付金额", messages[0]["content"])
        self.assertIn("2026-11-14", messages[1]["content"])
        self.assertIn("图片里的文字", messages[0]["content"])
        self.assertIn("不是指令", messages[0]["content"])


class TestCategoryHelpers(unittest.TestCase):
    def test_classify_category(self):
        cases = {
            "打车去公司": "交通",
            "交话费100": "其他",
            "火锅128": "餐饮",
            "房租3000": "居住",
            "看电影45": "娱乐",
            "药店买药36": "医疗",
            "淘宝买耳机299": "购物",
            "面包8": "餐饮",
            "包子6": "餐饮",
            "手机话费100": "其他",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(p.classify_category(text), expected)

    def test_classify_unknown(self):
        self.assertIsNone(p.classify_category("买了个东西100"))
        self.assertIsNone(p.classify_category("买包"))
        self.assertIsNone(p.classify_category(""))
        self.assertIsNone(p.classify_category(None))

    def test_normalize_category(self):
        self.assertEqual(p.normalize_category("餐饮"), ("餐饮", False))
        self.assertEqual(p.normalize_category("打车")[0], "交通")
        self.assertEqual(p.normalize_category(None, "交话费100")[0], "其他")
        self.assertEqual(p.normalize_category(None, "面包8")[0], "餐饮")
        self.assertEqual(p.normalize_category(None, "手机话费100")[0], "其他")
        self.assertEqual(p.normalize_category("乱七八糟", "午饭25")[0], "餐饮")
        self.assertEqual(p.normalize_category("乱七八糟", "买了个东西")[0], "其他")

    def test_refusal_phrases(self):
        self.assertEqual(p.find_refusal("帮我找个贷款口子"), "贷款口子")
        self.assertEqual(p.find_refusal("教我套现"), "套现")
        self.assertIsNone(p.find_refusal("还贷款3000"))
        self.assertIsNone(p.find_refusal("午饭25"))

    def test_income_words(self):
        self.assertTrue(p.looks_like_income("今天兼职收入500元"))
        self.assertTrue(p.looks_like_income("工资到账"))
        self.assertFalse(p.looks_like_income("午饭25"))
        # 这些词以前会误伤正常支出，现在只由提示词里的模型判断
        self.assertFalse(p.looks_like_income("还信用卡利息50"))
        self.assertFalse(p.looks_like_income("报销前先垫付打车32"))
        self.assertFalse(p.looks_like_income("快递费到账12"))


class TestIntent(unittest.TestCase):
    def test_intent_messages(self):
        messages = p.intent_messages("这个月吃饭花了多少", now=NOW)
        system = messages[0]["content"]
        for intent in p.VALID_INTENTS:
            self.assertIn(intent, system)
        self.assertIn("2026-11-01", messages[1]["content"])

    def test_clean_intent(self):
        raw = json.dumps(
            {
                "intents": ["query"],
                "time_range": {"start": "2026-11-01", "end": "2026-11-30"},
                "categories": ["餐饮"],
                "target": None,
            },
            ensure_ascii=False,
        )
        result = p.clean_intent(raw)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["intents"], ["query"])
        self.assertEqual(result["data"]["time_range"]["start"], "2026-11-01")
        self.assertEqual(result["data"]["categories"], ["餐饮"])

    def test_multi_intent(self):
        raw = json.dumps({"intents": ["query", "record"], "categories": []})
        data = p.clean_intent(raw)["data"]
        self.assertEqual(data["intents"], ["query", "record"])

    def test_category_alias(self):
        raw = json.dumps({"intents": ["query"], "categories": ["打车"]}, ensure_ascii=False)
        self.assertEqual(p.clean_intent(raw)["data"]["categories"], ["交通"])

    def test_invalid_time_range_dropped(self):
        raw = json.dumps(
            {"intents": ["query"], "time_range": {"start": "2026-11-30", "end": "2026-11-01"}}
        )
        result = p.clean_intent(raw)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["data"]["time_range"])

    def test_off_topic(self):
        raw = json.dumps({"intents": ["off_topic"], "categories": []})
        result = p.clean_intent(raw)
        self.assertFalse(result["ok"])
        self.assertIn("帮不上忙", result["msg"])

    def test_empty_intents(self):
        result = p.clean_intent(json.dumps({"intents": []}))
        self.assertFalse(result["ok"])
        self.assertIn("听懂", result["msg"])

    def test_refusal_source_text(self):
        result = p.clean_intent(json.dumps({"intents": ["record"]}), source_text="帮我套现")
        self.assertFalse(result["ok"])
        self.assertIn("帮不上忙", result["msg"])

    def test_bad_json(self):
        result = p.clean_intent("不是 JSON")
        self.assertFalse(result["ok"])


class TestAnalysis(unittest.TestCase):
    STATS = {
        "period": {"start": "2026-11-01", "end": "2026-11-30", "label": "2026年11月"},
        "total": 3200.5,
        "count": 42,
        "by_category": [
            {"category": "餐饮", "amount": 1200.0, "share": 0.375, "count": 18},
            {"category": "交通", "amount": 600.0, "share": 0.1875, "count": 10},
        ],
        "top_category": {"category": "餐饮", "amount": 1200.0},
    }

    def test_analysis_messages(self):
        messages = p.analysis_messages("这个月餐饮是不是太高了", self.STATS, now=NOW)
        self.assertIn("3200.5", messages[1]["content"])
        self.assertIn("1200.0", messages[1]["content"])
        self.assertIn("只能使用 stats 中出现的数字", messages[0]["content"])

    def test_analysis_messages_errors(self):
        with self.assertRaises(ValueError):
            p.analysis_messages("", self.STATS)
        with self.assertRaises(TypeError):
            p.analysis_messages("问题", "not-dict")
        with self.assertRaises(TypeError):
            p.analysis_messages("问题", {"bad": object()})

    def test_grounded_analysis(self):
        raw = json.dumps(
            {
                "summary": "本月总支出 3200.5 元，餐饮 1200 元，占 37.5%，是最高的类别。",
                "highlights": ["餐饮 1200 元，占本月支出的 37.5%。"],
                "suggestions": ["可以少点外卖。"],
            },
            ensure_ascii=False,
        )
        result = p.clean_analysis(raw, self.STATS)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["summary"], "本月总支出 3200.5 元，餐饮 1200 元，占 37.5%，是最高的类别。")
        self.assertEqual(len(result["data"]["highlights"]), 1)

    def test_ungrounded_analysis_falls_back(self):
        raw = json.dumps(
            {"summary": "本月支出 3200.5 元，比上月多花 500 元。", "highlights": [], "suggestions": []},
            ensure_ascii=False,
        )
        result = p.clean_analysis(raw, self.STATS)
        self.assertFalse(result["ok"])
        self.assertIn("数字校验", result["msg"])
        self.assertIn("3200.5", result["data"]["summary"])

    def test_rounding_allowed(self):
        raw = json.dumps({"summary": "本月总支出约 3201 元。", "highlights": [], "suggestions": []})
        self.assertTrue(p.clean_analysis(raw, self.STATS)["ok"])

    def test_empty_stats(self):
        result = p.clean_analysis(
            json.dumps({"summary": "有记录", "highlights": [], "suggestions": []}),
            {"count": 0, "total": 0},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["summary"], p.MSG_NO_DATA)

    def test_bad_json_falls_back(self):
        result = p.clean_analysis("不是 JSON", self.STATS)
        self.assertFalse(result["ok"])
        self.assertTrue(result["data"]["summary"])

    def test_highlights_capped(self):
        raw = json.dumps(
            {
                "summary": "本月支出 3200.5 元。",
                "highlights": ["a", "b", "c", "d"],
                "suggestions": ["s1", "s2", "s3", "s4"],
            }
        )
        result = p.clean_analysis(raw, self.STATS)
        self.assertEqual(len(result["data"]["highlights"]), 3)
        self.assertEqual(len(result["data"]["suggestions"]), 3)

    def test_string_highlights(self):
        raw = json.dumps({"summary": "本月支出 3200.5 元。", "highlights": "餐饮 1200 元。", "suggestions": "少点外卖。"})
        result = p.clean_analysis(raw, self.STATS)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["highlights"], ["餐饮 1200 元。"])

    def test_render_stats_summary(self):
        summary = p.render_stats_summary(self.STATS)
        self.assertIn("3200.5", summary)
        self.assertIn("餐饮", summary)
        self.assertIn("42", summary)

    def test_render_empty_stats(self):
        self.assertEqual(p.render_stats_summary(None), p.MSG_NO_DATA)


class TestTimeContext(unittest.TestCase):
    def test_fixed_now(self):
        ctx = p.build_time_context(NOW)
        self.assertEqual(ctx["today"], "2026-11-14")
        self.assertEqual(ctx["yesterday"], "2026-11-13")
        self.assertEqual(ctx["weekday"], "星期六")
        self.assertEqual(ctx["month_start"], "2026-11-01")
        self.assertEqual(ctx["month_end"], "2026-11-30")

    def test_recent_days_table(self):
        ctx = p.build_time_context(NOW)
        days = ctx["recent_days"].split("；")
        self.assertEqual(len(days), 14)
        self.assertTrue(days[0].startswith("2026-11-01"))
        self.assertTrue(days[-1].startswith("2026-11-14"))
        self.assertIn("星期六", days[-1])

    def test_date_object_and_naive_datetime(self):
        self.assertEqual(p.build_time_context(date(2026, 3, 1))["today"], "2026-03-01")
        ctx = p.build_time_context(datetime(2026, 1, 2, 8, 0, 0))
        self.assertTrue(ctx["now"].endswith("+08:00"))

    def test_invalid_type(self):
        with self.assertRaises(TypeError):
            p.build_time_context("2026-11-14")


class TestJsonParsing(unittest.TestCase):
    def test_variants(self):
        cases = [
            '{"ok": true}',
            '```json\n{"ok": true}\n```',
            '结果：{"ok": true} 完毕',
            '{"ok": true,}',
            '{"ok": true, // 注释\n}',
            '{“ok”：true}',
            '\ufeff{"ok": true}',
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                payload, error = p.try_parse_json(raw)
                self.assertIsNone(error)
                self.assertTrue(payload["ok"])

    def test_invalid(self):
        for raw in ("", "这不是 JSON", "123", "null", "[]"):
            with self.subTest(raw=raw):
                payload, error = p.try_parse_json(raw)
                self.assertIsNone(payload)
                self.assertTrue(error)

    def test_parse_raises(self):
        with self.assertRaises(p.PromptJSONError):
            p.parse_json_payload("坏输出")


if __name__ == "__main__":
    unittest.main()
