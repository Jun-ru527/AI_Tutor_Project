#君如负责ai框架模块
import os
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
# 初始化配置（真实接入时使用）
load_dotenv()
# client_vision = OpenAI(api_key=os.getenv("ZHIPU_API_KEY"), base_url="https://open.bigmodel.cn/api/paas/v4/")
# client_text = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")

# ==========================================
# 函数 1：解析文本记账（严格按契约返回）
# ==========================================
# 函数 1：解析文本记账（假数据版）
def parse_text(text):
    try:
        mock_data = {
            "amount": 25.0,
            "category": "餐饮",
            "spent_at": "2026-11-15",
            "merchant": "食堂",
            "note": text,
            "type": "支出"      # 🚨 新增的字段
        }
        return {"ok": True, "data": mock_data, "msg": "文本解析成功"}
    except Exception as e:
        return {"ok": False, "data": None, "msg": str(e)}

# 函数 2：解析图片记账（假数据版）
def parse_image(image_path):
    try:
        mock_data = {
            "amount": 5000.0,
            "category": "工资",
            "spent_at": "2026-11-15",
            "merchant": "公司",
            "note": "发工资啦",
            "type": "收入"      # 🚨 新增的字段
        }
        return {"ok": True, "data": mock_data, "msg": "图片识别成功"}
    except Exception as e:
        return {"ok": False, "data": None, "msg": str(e)}
