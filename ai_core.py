#君如负责ai框架模块
import base64
import json
import os

import prompts  # 队友的提示词模块：文本/图片两套 messages 都在这里
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

TEXT_MODEL = "glm-4-flash"
VISION_MODEL = "glm-4v-flash"
BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"

# 1. 文本模型
client_text = OpenAI(api_key=os.getenv("ZHIPU_API_KEY"), base_url=BASE_URL)

# 2. 视觉模型
client_vision = OpenAI(api_key=os.getenv("ZHIPU_API_KEY"), base_url=BASE_URL)

# 常见图片后缀 -> MIME，保证 base64 前缀和真实格式一致（PNG 别再谎称 jpeg）
_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
}


def _detect_mime(raw: bytes, path: str = "") -> str:
    """按文件头判断真实格式，而不是只看扩展名。

    实测遇到过：文件名是 .jpg，内容其实是 PNG。按扩展名声明成 image/jpeg 时，
    视觉接口可能直接拒收，表现成"识别失败"。读前几个字节就能认准。
    """
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:2] == b"BM":
        return "image/bmp"
    return _MIME.get(os.path.splitext(str(path))[1].lower(), "image/jpeg")


def _parse_model_json(raw):
    """把模型返回的文本变成 Python 对象。

    优先用 prompts.try_parse_json：它已经处理了 ```json 包裹、多余文字、
    尾逗号这些情况，比裸 json.loads 稳得多。
    """
    if isinstance(raw, (dict, list)):
        return raw
    parser = getattr(prompts, "try_parse_json", None)
    if parser is not None:
        try:
            payload, _err = parser(raw)
            if payload is not None:
                return payload
        except Exception:
            pass
    cleaned = str(raw).replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)


# ==========================================
# 函数 1：真实解析文本记账
# ==========================================
def parse_text(text):
    """一句话 -> 模型 JSON（数组，可含多笔、可含收入）。

    返回 {"ok": bool, "data": list|dict|None, "msg": str}
    """
    try:
        messages = prompts.text_messages(text)  # 里面已经带了今天/昨天的时间上下文
        response = client_text.chat.completions.create(
            model=TEXT_MODEL,
            messages=messages,
            temperature=0,
        )
        data = _parse_model_json(response.choices[0].message.content)
        return {"ok": True, "data": data, "msg": "文本解析成功"}
    except Exception as e:
        return {"ok": False, "data": None, "msg": f"解析失败: {e}"}


# ==========================================
# 函数 2：真实解析图片记账（小票 / 支付截图）
# ==========================================
def parse_image(image_path):
    """图片 -> 模型 JSON。

    关键改动：以前这里自己写了一句"请提取金额、分类…只返回JSON"，
    没有任何字段格式约束，模型就返回了中文键名
    （{"金额":2400,"分类":"兼职收入","收支类型":"收入"}），
    界面按 amount/type 去取全都是空 -> 表现成"什么都没识别出来"。

    现在改用 prompts.image_messages()：
      - 有严格的 JSON 字段和后缀规范
      - 带"今天/昨天"上下文，日期能落到正确的一天
      - 带七类分类表和收支类型判定规则
    """
    try:
        with open(image_path, "rb") as f:
            raw_bytes = f.read()
        if len(raw_bytes) > 6 * 1024 * 1024:
            return {"ok": False, "data": None,
                    "msg": "图片太大（超过 6MB），请压缩后再上传"}

        mime = _detect_mime(raw_bytes, image_path)
        img_b64 = base64.b64encode(raw_bytes).decode()

        messages = prompts.image_messages()
        system_text = ""
        user_text = ""
        for msg in messages:
            if msg.get("role") == "system":
                system_text = msg.get("content", "")
            else:
                user_text = msg.get("content", "")

        # 视觉模型对 system 角色支持不稳定，把系统提示并进 user 文本一起发
        text_part = (system_text + "\n\n" + user_text).strip()
        # 实测补充：工资条、银行流水、转账记录也属于"一笔账"，
        # 否则模型会把它们当成"不是小票"，is_bill 填 false，整笔被丢掉。
        text_part += (
            "\n\n# 补充说明\n"
            "工资条 / 收入明细 / 银行流水 / 转账记录截图，同样属于一笔账，is_bill 填 true。"
            "「实发到账 / 应发合计」这类字段取实发金额。"
        )

        response = client_vision.chat.completions.create(
            model=VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": text_part},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                ],
            }],
            temperature=0,
        )
        data = _parse_model_json(response.choices[0].message.content)
        return {"ok": True, "data": data, "msg": "图片解析成功"}
    except Exception as e:
        return {"ok": False, "data": None, "msg": f"解析失败: {e}"}


if __name__ == "__main__":
    print(">>> 测试开始 <<<")
    print(parse_text("昨天打车 32"))
    print(parse_text("发工资了 8000"))
