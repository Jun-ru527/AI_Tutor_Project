@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动记账助手，浏览器会自动打开 http://localhost:8501
echo 关闭这个黑窗口就等于停止程序。
python -m streamlit run app.py
pause
