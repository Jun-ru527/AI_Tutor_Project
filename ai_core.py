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
def parse_text(text):
    """
    传一句话，拿回五个字段。
    根据契约，只返回 {ok, data, msg}
    """
    try:
        # 下面是假数据，严格按照五个字段的类型返回
        mock_data = {
            "amount": 25.0,                                   # 数字
            "category": "餐饮",                               # 文字
            "spent_at": datetime.now().strftime("%Y-%m-%d"),  # 文字，YYYY-MM-DD
            "merchant": "食堂",                               # 文字，可空
            "note": text                                      # 文字，原话
        }
        
        return {
            "ok": True,
            "data": mock_data,
            "msg": "文本解析成功"
        }
        
    except Exception as e:
        # 异常兜底，data 传 None
        return {
            "ok": False,
            "data": None,
            "msg": f"文本解析服务异常: {str(e)}"
        }

# ==========================================
# 函数 2：解析图片记账（严格按契约返回）
# ==========================================
def parse_image(image_path):
    """
    传图片路径，拿回五个字段。
    根据契约，只返回 {ok, data, msg}
    """
    try:
        # 基础防御：如果文件路径不存在，直接返回 False
        if not os.path.exists(image_path):
            return {
                "ok": False,
                "data": None,
                "msg": "图片文件不存在，请重新上传"
            }

        # 下面是假数据，严格按照五个字段的类型返回
        mock_data = {
            "amount": 20.5,            # 数字
            "category": "餐饮",        # 文字
            "spent_at": "2026-11-14",  # 文字，YYYY-MM-DD
            "merchant": "拾味小馆",    # 文字，可空
            "note": "牛肉拉面"         # 文字，原话
        }

        return {
            "ok": True,
            "data": mock_data,
            "msg": "图片识别成功"
        }
        
    except Exception as e:
        return {
            "ok": False,
            "data": None,
            "msg": f"图片解析服务异常: {str(e)}"
        }
