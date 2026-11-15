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
# 函数 1：解析文本记账（带逻辑的假数据版）
# ==========================================
def parse_text(text):
    try:
        # 聪明的假数据：根据用户输入的关键词，返回不同的假数据，方便测试前端和后端！
        if "打车" in text or "交通" in text:
            mock_data = {
                "amount": 32.0, "category": "交通", "spent_at": "2026-11-15", 
                "merchant": "滴滴出行", "note": text, "type": "支出"
            }
        elif "买" in text or "购物" in text or "淘宝" in text:
            mock_data = {
                "amount": 199.0, "category": "购物", "spent_at": "2026-11-15", 
                "merchant": "淘宝", "note": text, "type": "支出"
            }
        elif "工资" in text or "收入" in text or "发钱" in text:
            mock_data = {
                "amount": 5000.0, "category": "工资", "spent_at": "2026-11-15", 
                "merchant": "公司财务", "note": text, "type": "收入"
            }
        else:
            # 默认返回餐饮
            mock_data = {
                "amount": 25.0, "category": "餐饮", "spent_at": "2026-11-15", 
                "merchant": "食堂", "note": text, "type": "支出"
            }
            
        return {"ok": True, "data": mock_data, "msg": "文本解析成功"}
    except Exception as e:
        return {"ok": False, "data": None, "msg": str(e)}

# ==========================================
# 函数 2：解析图片记账（假数据版）
# ==========================================
def parse_image(image_path):
    try:
        # 你可以根据图片名字稍微区分一下，或者就固定给个小票的数据
        mock_data = {
            "amount": 20.5, 
            "category": "餐饮", 
            "spent_at": "2026-11-15", 
            "merchant": "拾味小馆", 
            "note": "图片识别出的账单", 
            "type": "支出"
        }
        return {"ok": True, "data": mock_data, "msg": "图片识别成功"}
    except Exception as e:
        return {"ok": False, "data": None, "msg": str(e)}
