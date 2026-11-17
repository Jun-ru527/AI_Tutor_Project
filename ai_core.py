#君如负责ai框架模块
import os
import json
import prompts # 🚨 引入队友合并进来的提示词模块
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# 1. 初始化文本大模型（用你的智谱 Key）
client_text = OpenAI(
    api_key=os.getenv("ZHIPU_API_KEY"),
    base_url="https://open.bigmodel.cn/api/paas/v4/"
)

# 2. 初始化视觉大模型（如果你还要做图片识别）
client_vision = OpenAI(
    api_key=os.getenv("ZHIPU_API_KEY"),
    base_url="https://open.bigmodel.cn/api/paas/v4/"
)

# ==========================================
# 函数 1：真实解析文本记账
# ==========================================
def parse_text(text):
    try:
        # 🚨 直接调用她写好的函数！她第 5 行写了，传一句话进去，就能拿回模型要的格式
        messages = prompts.text_messages(text)
        
        response = client_text.chat.completions.create(
            model="glm-4-flash",
            messages=messages # 🚨 这里直接用她生成的 messages
        )
        
        raw_json_str = response.choices[0].message.content
        clean_str = raw_json_str.replace("```json", "").replace("```", "").strip()
        
        return {"ok": True, "data": json.loads(clean_str), "msg": "文本解析成功"}
        
    except Exception as e:
        return {"ok": False, "data": None, "msg": f"解析失败: {str(e)}"}

# ==========================================
# 函数 2：真实解析图片记账 (你需要自己补全图片的 Prompt)
# ==========================================
def parse_image(image_path):
    import base64
    try:
        with open(image_path, "rb") as f:
            img_base = base64.b64encode(f.read()).decode('utf-8')
            
        response = client_vision.chat.completions.create(
            model="glm-4v-flash", # 视觉模型
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "请提取金额、分类、日期、商户、备注、收支类型，只返回JSON。"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base}"}}
            ]}]
        )
        raw_json_str = response.choices[0].message.content
        clean_str = raw_json_str.replace("```json", "").replace("```", "").strip()
        return {"ok": True, "data": json.loads(clean_str), "msg": "图片解析成功"}
    except Exception as e:
        return {"ok": False, "data": None, "msg": f"解析失败: {str(e)}"}
if __name__ == "__main__":
    print(">>> 测试开始 <<<")  # 加上这句，如果这句没出来，说明程序根本没跑
    res = parse_text("打车花了32块")
    print(">>> 解析结果是：", res)
