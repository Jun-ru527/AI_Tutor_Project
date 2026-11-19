#文勤负责的SQL调用-db.py

import os
import sqlite3
import datetime

# 数据库文件：以本文件所在目录为准的绝对路径。
# 以前写的是相对路径 "ledger.db"，从哪个文件夹启动 streamlit 就会在哪儿新建一个空库，
# 会出现"明明清空了、数据却还在"或者"凭空多出一个空库"的怪现象。
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ledger.db")

#内部函数，用于获取conn
def _get_connection ():
    # timeout=5：遇到别的连接正在写时，最多等 5 秒再报错，而不是立刻失败。
    # 没有这个参数，两个标签页同时操作会直接抛 "database is locked"。
    conn=sqlite3.connect(DB_PATH, timeout=5)
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
        # 老库补一列 is_demo（0=手记，1=演示数据）。幂等：已经有这一列就跳过。
        # 有了它，"清空演示数据"才不会把用户手记的记录一起删掉。
        cols=[row[1] for row in cursor.execute("PRAGMA table_info(bills)").fetchall()]
        if "is_demo" not in cols:
            cursor.execute(
                "ALTER TABLE bills ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0"
            )
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
    row=dict(data)
    row.setdefault("is_demo",0)   # 没传就按手记算，演示数据由界面显式传 1

    # 金额必须落在 (0, 100 万] 之内。
    # 界面上的 number_input 虽然限制了最小值，但函数本身也得守住：
    # 任何绕过界面的调用（批量导入、脚本、以后加的 API）都能写进 0 元、负数、
    # 甚至 1 亿元的记录，统计和图表会直接失真，而且很难查。
    try:
        amount=float(row.get("amount"))
    except (TypeError, ValueError):
        return False
    if not (0 < amount <= 1_000_000):
        return False

    conn=None
    try:
        conn=_get_connection()
        cursor=conn.cursor()
        cursor.execute(
            """INSERT INTO bills
                (amount,category,spent_at,merchant,note,type,is_demo)
                VALUES
                (:amount,:category,:spent_at,:merchant,:note,:type,:is_demo)""",
            row
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        if conn is not None:
            conn.close()

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


# ---------------------------------------------------------------------------
# 演示数据维护：让界面上的"导入演示数据"不再越点越多
# ---------------------------------------------------------------------------

def count_bills ():
    """返回 bills 表总条数；读不出来返回 None。"""
    conn=None
    try:
        conn=_get_connection()
        return conn.execute("SELECT COUNT(*) FROM bills").fetchone()[0]
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


def clear_demo ():
    """只删 is_demo=1 的演示数据，用户手记的一条不动。返回删掉的条数；失败返回 None。"""
    conn=None
    try:
        conn=_get_connection()
        cursor=conn.execute("DELETE FROM bills WHERE is_demo=1")
        deleted=cursor.rowcount
        conn.commit()
        return deleted
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


def clear_all_bills ():
    """清空整张 bills 表（含手记），用于"重置演示数据"。返回删掉的条数；失败返回 None。"""
    conn=None
    try:
        conn=_get_connection()
        cursor=conn.execute("DELETE FROM bills")
        deleted=cursor.rowcount
        conn.commit()
        return deleted
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


def reset_demo_bills (bills):
    """
    原子地重置演示数据：同一个事务里「先清空、再整批写入」。

    为什么不能像以前那样分成两次调用：
      清空和写入各开一个连接，两次之间没有锁。两个标签页一起点（或连点两下）时，
      就会出现 A 清空 → B 写入 16 → A 再写入 16，最后 31 笔/32 笔，而且清不干净。
      实测 16+15=31 就是这么来的（其中一笔在加锁时失败）。

    现在 BEGIN IMMEDIATE 先拿写锁，后到的那个只能排队等，等它拿到锁时先清空再做自己那批，
    所以无论几个人同时点，库里最后永远是 len(bills) 笔。

    返回 (写入数, 删除数)；失败返回 None（事务会回滚，不会留下半批数据）。
    """
    conn=None
    try:
        conn=_get_connection()
        conn.isolation_level=None            # 关掉 Python 的隐式事务，自己控制边界
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("BEGIN IMMEDIATE")      # 关键：先占写锁，并发请求在这里排队
        deleted=conn.execute("DELETE FROM bills").rowcount

        rows=[]
        for bill in bills:
            row=dict(bill)
            row.setdefault("is_demo",1)      # 这一批全部标记成演示数据
            rows.append(row)
        conn.executemany(
            """INSERT INTO bills
                (amount,category,spent_at,merchant,note,type,is_demo)
                VALUES
                (:amount,:category,:spent_at,:merchant,:note,:type,:is_demo)""",
            rows
        )
        conn.execute("COMMIT")
        return len(rows),deleted
    except Exception:
        if conn is not None:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
        return None
    finally:
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# AI 调用日志：写入靠 log_ai()，读取靠 get_ai_logs()（契约 6 节里本来就有这个名字）
# ---------------------------------------------------------------------------

def get_ai_logs (limit=20):
    """
    按时间倒序取最近 limit 条 AI 调用记录。

    返回 [{"raw_input":..., "ai_json":..., "created_at":...}, ...]；
    读不出来返回 None。界面据此展示"用户说了什么 / 模型返回了什么"，
    答辩被问"AI 调用有没有留痕"时可以直接翻给人看。
    """
    conn=None
    try:
        conn=_get_connection()
        rows=conn.execute(
            "SELECT raw_input, ai_json, created_at FROM ai_logs ORDER BY id DESC LIMIT ?",
            (int(limit),)
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


def clear_ai_logs ():
    """清空 ai_logs（答辩前清理调试痕迹）。返回删掉的条数；失败返回 None。"""
    conn=None
    try:
        conn=_get_connection()
        cursor=conn.execute("DELETE FROM ai_logs")
        deleted=cursor.rowcount
        conn.commit()
        return deleted
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()
