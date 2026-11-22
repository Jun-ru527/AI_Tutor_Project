@echo off
chcp 936 >nul
title 记账助手
cd /d "C:\Users\赵君如\Documents\AI_Tutor_Project"
echo ============================================
echo    个人记账助手 正在启动
echo    浏览器会自动打开 http://localhost:8501
echo    关闭这个黑窗口 = 停止程序
echo ============================================
echo.
python -m streamlit run app.py
echo.
echo 程序已停止，按任意键关闭。
pause >nul