#文勤负责的SQL调用-db.py

import sqlite3
import datetime

#数据库文件，存放位置：当前目录。
DB_PATH="ledger.db"

#内部函数，用于获取conn
def _get_connection ():
    conn=sqlite3.connect(DB_PATH)
    conn.row_factory=sqlite3.Row 
    return conn

#初始化函数，建议程序启动时调用一次，避免因ledger.db文件不存在而报错。
#若ledger.db文件不存在，则创建该文件并创建bills、budgets、ai_logs表。
#正常返回True，异常返回False (可能数据库文件已损坏或被其他程序占用)
def init_db ():
    try:
        conn=_get_connection()
        cursor=conn.cursor()
        #创建bills表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount REAL,
                category TEXT NOT NULL,
                spent_at TEXT NOT NULL,
                merchant TEXT,
                note TEXT,
                type TEXT
            )
        """)
        #创建budgets表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL, 
                month TEXT NOT NULL,
                limit_amount REAL NOT NULL
            )
        """)
        #创建ai_logs表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_input TEXT, 
                ai_json TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        return True
    except sqlite3.DatabaseError:
        conn.close()
        return False


#向表bills添加一条消费记录，格式为：
# data={"amount":...,"category":...,"spent_at":...,"merchant":...,"note":...,"type":...}
# amount：  金额    （浮点数，比如 25.5）       不为空可为None
# category：分类    （文字，比如“餐饮”）        不为空
# spent_at：消费时间（文字，格式 YYYY-MM-DD）   不为空
# merchant：商户    （文字，比如“沙县小吃”）    不为空可为None
# note：    备注    （文字，用户说的话）        不为空可为None
# type：    收支类型（文字，如支付）            不为空可为None
#正常返回True，异常返回False (可能数据库文件已损坏或被其他程序占用)
def add_bill (data):
    try:
        conn=_get_connection()
        cursor=conn.cursor()
        cursor.execute(
            """INSERT INTO bills
                (amount,category,spent_at,merchant,note,type)
                VALUES
                (:amount,:category,:spent_at,:merchant,:note,:type)""",
            data
        )
        conn.commit()
        conn.close()
        return True
    except:
        conn.close()
        return False

#向表bills查询type类的所有消费记录，格式为：
# type：    收支类型（文字，如支付）    不为空可为None
#正常返回[{"amount":...,"category":...,"spent_at":...,"merchant":...,"note":...,"type":...},...]，
#异常返回None (可能数据库文件已损坏或被其他程序占用)
def list_records (type):
    try:
        conn=_get_connection()
        cursor=conn.cursor()
        cursor.execute(
            "SELECT*FROM bills WHERE type=? ORDER BY spent_at DESC,id DESC",
            [type]
        )
        rows=cursor.fetchall()
        conn.commit()
        conn.close()
        for i in range(len(rows)):
            rows[i]=dict(rows[i])
            rows[i].pop("id")
        return rows
    except:
        conn.close()
        return None

#向表bills查询type类的所有消费记录并按照category类分类，格式为：
# type：    收支类型（文字，如支付）    不为空可为None
#正常返回[{"category":...,"amount":...},...]，
#异常返回False (可能数据库文件已损坏或被其他程序占用)
def sum_by_category (type):
    try:
        conn=_get_connection()
        cursor=conn.cursor()
        cursor.execute(
            """SELECT category,SUM(amount) FROM bills WHERE type=?
            GROUP BY category ORDER BY amount DESC""",
            [type]
        )
        rows=cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except:
        conn.close()
        return False

#向表budgets添加一条预算记录，格式为：
# category：    分类    （文字）                不为空
# limit_amount：预算金额（浮点数）               不为空
# month：       月份    （文字，比如“2026-11”）  不为空
#正常返回True，异常返回False (可能数据库文件已损坏或被其他程序占用)
def set_budget (category,limit_amount,month):
    try:
        conn=_get_connection()
        cursor=conn.cursor()
        cursor.execute(
            "INSERT INTO budgets (category,limit_amount,month) VALUES (?,?,?)",
            (category,limit_amount,month)
        )
        conn.commit()
        conn.close()
        return True
    except:
        conn.close()
        return False

#向表budgets查询一条预算记录，格式为：
# category：    分类    （文字）                不为空
# month：       月份    （文字，比如“2026-11”）  不为空
#正常返回{"ok":...,"data":...,"msg":...}，
#异常返回False (可能数据库文件已损坏或被其他程序占用)
def get_budget (category,month):
    try:
        conn=_get_connection()
        cursor=conn.cursor()
        cursor.execute(
            "SELECT*FROM budgets WHERE category=? AND month=?",
            (category,month)
        )
        try:
            row=dict(cursor.fetchone())
            row.pop('id')
            json={"ok":True,"data":row,"msg":"查询成功"}
        except:
            json={"ok":False,"data":None,"msg":"该分类本月未设置预算"}
        conn.close()
        return json
    except:
        conn.close()
        return False

#向表ai_logs添加一条日志记录，格式为：
# json={"ok":...,"data":{"raw_input":...,"ai_json":...,"created_at":...},"msg":...}
# ok：        True_False（是否成功）              不为空           
# raw_input： 用户原话   （文字，比如“昨天打车32”） 不为空可为None
# ai_json：   AI        （返回的原始 JSON 文本）   不为空可为None
# created_at：时间戳    （YYYY-MM-DD HH:MM:SS）   不为空可为None
# msg：       日志      （日志）                  不为空
#正常返回True，异常返回False (可能数据库文件已损坏或被其他程序占用)
def log_ai (raw_input,ai_json):
    try:
        conn=_get_connection()
        cursor=conn.cursor()
        cursor.execute(
            "INSERT INTO ai_logs (raw_input,ai_json,created_at) VALUES (?,?,?)",
            (raw_input,ai_json,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )
        conn.commit()
        conn.close()
        return True
    except:
        conn.close()
        return False
