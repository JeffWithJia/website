# !/usr/bin/env python3
import csv
import html
import sys
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# ================= 配置区域 =================
# 客户发给你的反馈，算作哪一天的增量？在此修改（例如 "2026-05-14"）
# 如果设为 None，则自动使用运行脚本时的当天日期
MANUAL_FEEDBACK_DATE = None
# ===========================================

# 尝试引入拼音库用于生成拼音搜索索引，如果未安装则静默退化为纯中文搜索
try:
    import pypinyin
except ImportError:
    pypinyin = None

INTERNAL_PASS = {"质检合格", "质检优秀"}
INTERNAL_BAD = {"质检不通过", "异常数据", "数据错误--"}

SOP_ORDER = {
    "SOP 1.0": 1,
    "SOP 2.0": 2,
    "SOP 2.0.1": 3,
    "SOP 3.0": 4,
    "SOP 3.0.1": 5,
    "未匹配/其他": 99,
}

SCENE_SOP_MAP = {
    "产线货物分拣": ("SOP 1.0", "产线货物分拣"),
    "物流分拣": ("SOP 1.0", "物流分拣"),
    "铲取爆米花装入盒子": ("SOP 1.0", "铲取爆米花装入盒子"),
    "用胶囊咖啡机冲泡胶囊咖啡": ("SOP 1.0", "用胶囊咖啡机冲泡胶囊咖啡"),
    "茶几整理": ("SOP 1.0", "茶几整理"),
    "沙发衣物收纳入右侧脏衣篓": ("SOP 1.0", "沙发衣物收纳入右侧脏衣篓"),
    "床上衣物收纳入右侧脏衣篓": ("SOP 1.0", "床上衣物收纳入右侧脏衣篓"),
    "货架补货": ("SOP 1.0", "货架补货"),
    "沙发衣物收纳入左侧脏衣篓": ("SOP 1.0", "沙发衣物收纳入左侧脏衣篓"),
    "拿取货物": ("SOP 1.0", "拿取货物"),
    "物流分拣-扫码0320": ("SOP 1.0", "物流分拣-扫码0320"),
    "床上衣物收纳入左侧脏衣篓": ("SOP 1.0", "床上衣物收纳入左侧脏衣篓"),
    "产线货物分拣-0320": ("SOP 1.0", "产线货物分拣-0320"),
    "沙发-衣服收纳": ("SOP 1.0", "沙发-衣服收纳"),
    "泡咖啡": ("SOP 1.0", "泡咖啡"),
    "茶几整理-0320": ("SOP 1.0", "茶几整理-0320"),
    "货架补货-星尘": ("SOP 1.0", "货架补货-星尘"),
    "铲取爆米花装入盒子-补采": ("SOP 2.0", "铲取爆米花装入盒子-补采"),
    "Scoop popcorn into a box 2.0": ("SOP 2.0", "Scoop popcorn into a box 2.0"),
    "Logistics sorting - Scanning 2.0": ("SOP 2.0", "Logistics sorting - Scanning 2.0"),
    "用抹布擦除洗手盆上的水渍": ("SOP 2.0", "用抹布擦除洗手盆上的水渍"),
    "补充开放式冷藏柜的易拉罐饮料": ("SOP 2.0", "补充开放式冷藏柜的易拉罐饮料"),
    "物流分拣-补采": ("SOP 2.0", "物流分拣-补采"),
    "用马桶刷清洁马桶": ("SOP 2.0", "用马桶刷清洁马桶"),
    "冲泡咖啡": ("SOP 2.0.1", "冲泡咖啡"),
    "商超收银操作区": ("SOP 2.0.1", "商超收银操作区"),
    "床上折叠衣服": ("SOP 2.0.1", "床上折叠衣服"),
    "床上折叠衣物": ("SOP 2.0.1", "床上折叠衣物"),
    "桌面文具整理": ("SOP 2.0.1", "桌面文具整理"),
    "清理桌面垃圾": ("SOP 2.0.1", "清理桌面垃圾"),
    "清理桌面干垃圾": ("SOP 2.0.1", "清理桌面干垃圾"),
    "茶几收纳": ("SOP 2.0.1", "茶几收纳"),
    "茶餐厅倒水": ("SOP 2.0.1", "茶餐厅倒水"),
    "试管分拣": ("SOP 2.0.1", "试管分拣"),
    "餐桌倒水": ("SOP 2.0.1", "餐桌倒水"),
    "微波置盘": ("SOP 3.0", "微波置盘"),
    "整理床铺物品收纳": ("SOP 3.0", "整理床铺物品收纳"),
    "沙发整理": ("SOP 3.0", "沙发整理"),
    "洗漱台整理": ("SOP 3.0", "洗漱台整理"),
    "化妆品收纳": ("SOP 3.0", "化妆品收纳"),
}

TEMPLATE_CHINESE_MAP = {
    "Clean up the trash on the desktop": "清理桌面垃圾",
    "Coffee Preparation at a Commercial Bar 2.0": "冲泡咖啡",
    "Desktop stationary organization": "桌面文具整理",
    "Folding clothes on the bed": "床上折叠衣服",
    "Organize the coffee table 2.0": "茶几收纳",
    "Pouring water in a tea restaurant": "茶餐厅倒水",
    "Test tube sorting": "试管分拣",
}


def get_report_date():
    return MANUAL_FEEDBACK_DATE if MANUAL_FEEDBACK_DATE else datetime.now().strftime("%Y-%m-%d")


def split_scene(title):
    title = (title or "").strip()
    if not title:
        return ""
    parts = title.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else title


def should_exclude_scene(scene):
    scene = (scene or "").strip()
    return scene == "产线分拣-橙蓝物品" or "（待确认）" in scene or "(待确认)" in scene


def classify_scene(scene):
    scene = (scene or "").strip()
    if not scene: return ("未匹配/其他", "<空>")
    if scene in SCENE_SOP_MAP: return SCENE_SOP_MAP[scene]
    if "3.0.1" in scene: return ("SOP 3.0.1", scene)
    if "3.0" in scene: return ("SOP 3.0", scene)
    if "0320" in scene: return ("SOP 1.0", scene)
    if "2.0.1" in scene or any(k in scene for k in ["倒水", "文具", "折叠"]): return ("SOP 2.0.1", scene)
    if "2.0" in scene or "补采" in scene: return ("SOP 2.0", scene)
    return ("SOP 1.0", scene)


DATA_PATH = Path("records.csv")
OUT_PATH = Path("records.html")

CUSTOMER_PASS = {"Approve", "Perfect", "Imperfect"}
CUSTOMER_REJECT = "Reject"
EMPTY = "<空>"

ISSUE_FIELDS = [
    "不通过原因", "原因（未出现选项）", "消息频率校验", "人脸", "夹取稳定性",
    "画面停滞", "失败次数", "画面微暗", "夹取时机", "任务状态",
    "冗余动作占比", "碰撞次数", "消息定义校验",
]

NEUTRAL_ISSUES = {"", "无", "通过", "稳定", "未出现人脸", "完成任务", "合适时机伸手"}


def clean(value):
    value = (value or "").strip()
    return value if value else EMPTY


def clean_val(v):
    if v is None: return ""
    return str(v).replace('"', '').replace("'", "").replace('\n', '').replace('\r', '').strip()


def esc(value): return html.escape(str(value), quote=True)


def pct(part, total): return None if not total else part / total


def fmt_int(value): return f"{int(value):,}"


def fmt_pct(value): return "-" if value is None else f"{value * 100:.1f}%"


def fmt_seconds(value): return f"{value:,.0f}"


def fmt_hours(seconds): return f"{seconds / 3600:,.1f}"


def fmt_duration_hours(hours): return "-" if hours is None else f"{hours:,.1f} 小时"


def fmt_storage(bytes_value):
    bytes_value = bytes_value or 0
    tib = bytes_value / (1024 ** 4)
    if tib >= 1: return f"{tib:,.2f}T"
    return f"{bytes_value / (1024 ** 3):,.2f}G"


def parse_number(value, default=0.0):
    try:
        return float((value or "").strip() or default)
    except ValueError:
        return default


def parse_int(value, default=0):
    try:
        return int(float((value or "").strip() or default))
    except ValueError:
        return default


def parse_dt(value):
    value = (value or "").strip()
    if not value: return None
    if value.endswith("Z"): value = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def date_key(value):
    parsed = parse_dt(value)
    return parsed.date().isoformat() if parsed else None


def get_pinyin_index(text):
    if not pypinyin: return ""
    try:
        full = "".join([p[0] for p in pypinyin.pinyin(text, style=pypinyin.Style.NORMAL)])
        initials = "".join([p[0] for p in pypinyin.pinyin(text, style=pypinyin.Style.FIRST_LETTER)])
        return f"{full} {initials}"
    except:
        return ""


def empty_bucket():
    return {
        "total": 0, "duration": 0.0, "bytes": 0, "internal": Counter(), "customer": Counter(),
        "cross": Counter(), "customer_pass_duration": 0.0, "customer_pass_bytes": 0,
        "customer_reject_duration": 0.0, "customer_reject_bytes": 0, "customer_pending_count": 0,
        "customer_pending_duration": 0.0, "customer_pending_bytes": 0, "internal_pass_duration": 0.0,
        "internal_pass_bytes": 0, "internal_bad_duration": 0.0, "internal_bad_bytes": 0,
        "qa_latency_hours": 0.0, "qa_latency_count": 0, "release_customer_done": 0, "release_customer_reject": 0,
    }


def empty_production_bucket():
    return {
        "collected_count": 0, "collected_duration": 0.0, "reviewed_count": 0,
        "reviewed_duration": 0.0, "review_pass_count": 0, "review_pass_duration": 0.0,
    }


def add_collection(bucket, duration):
    bucket["collected_count"] += 1
    bucket["collected_duration"] += duration


def add_review(bucket, internal, duration):
    bucket["reviewed_count"] += 1
    bucket["reviewed_duration"] += duration
    if internal in INTERNAL_PASS:
        bucket["review_pass_count"] += 1
        bucket["review_pass_duration"] += duration


def merge_production_bucket(target, source):
    for key, value in source.items(): target[key] += value


def production_metrics(bucket):
    return {**bucket, "review_pass_rate": pct(bucket["review_pass_count"], bucket["reviewed_count"])}


def add_record(bucket, internal, customer, duration, byte_size, qa_latency_hours):
    bucket["total"] += 1
    bucket["duration"] += duration
    bucket["bytes"] += byte_size
    bucket["internal"][internal] += 1
    bucket["customer"][customer] += 1
    bucket["cross"][(internal, customer)] += 1

    if customer in CUSTOMER_PASS:
        bucket["customer_pass_duration"] += duration
        bucket["customer_pass_bytes"] += byte_size
    if customer == CUSTOMER_REJECT:
        bucket["customer_reject_duration"] += duration
        bucket["customer_reject_bytes"] += byte_size
    if internal in INTERNAL_PASS and customer == EMPTY:
        bucket["customer_pending_count"] += 1
        bucket["customer_pending_duration"] += duration
        bucket["customer_pending_bytes"] += byte_size
    if internal in INTERNAL_PASS:
        bucket["internal_pass_duration"] += duration
        bucket["internal_pass_bytes"] += byte_size
    if internal in INTERNAL_BAD:
        bucket["internal_bad_duration"] += duration
        bucket["internal_bad_bytes"] += byte_size
    if internal in INTERNAL_PASS and customer != EMPTY:
        bucket["release_customer_done"] += 1
    if internal in INTERNAL_PASS and customer == CUSTOMER_REJECT:
        bucket["release_customer_reject"] += 1
    if qa_latency_hours is not None:
        bucket["qa_latency_hours"] += qa_latency_hours
        bucket["qa_latency_count"] += 1


def bucket_metrics(bucket):
    total = bucket["total"]
    internal_done = total - bucket["internal"][EMPTY]
    internal_pass = sum(bucket["internal"][status] for status in INTERNAL_PASS)
    internal_bad = sum(bucket["internal"][status] for status in INTERNAL_BAD)

    customer_empty = bucket["customer"][EMPTY]
    customer_done = total - customer_empty
    customer_pass = sum(bucket["customer"][status] for status in CUSTOMER_PASS)
    customer_reject = bucket["customer"][CUSTOMER_REJECT]
    customer_other = customer_done - customer_pass - customer_reject
    avg_qa_latency = (bucket["qa_latency_hours"] / bucket["qa_latency_count"] if bucket["qa_latency_count"] else None)

    return {
        "total": total, "duration": bucket["duration"], "avg_duration": pct(bucket["duration"], total),
        "bytes": bucket["bytes"], "avg_bytes": pct(bucket["bytes"], total), "internal_done": internal_done,
        "internal_pending": bucket["internal"][EMPTY], "internal_pass": internal_pass,
        "internal_pass_rate": pct(internal_pass, internal_done), "internal_bad": internal_bad,
        "internal_bad_rate": pct(internal_bad, internal_done), "customer_done": customer_done,
        "customer_pending": bucket["customer_pending_count"], "customer_pass": customer_pass,
        "customer_pass_rate": pct(customer_pass, customer_done), "customer_reject": customer_reject,
        "customer_reject_rate": pct(customer_reject, customer_done), "customer_other": customer_other,
        "internal_pass_customer_reject": bucket["release_customer_reject"],
        "internal_pass_customer_done": bucket["release_customer_done"],
        "internal_pass_customer_reject_rate": pct(bucket["release_customer_reject"], bucket["release_customer_done"]),
        "internal_bad_customer_pass": sum(
            bucket["cross"][(internal, customer)] for internal in INTERNAL_BAD for customer in CUSTOMER_PASS),
        "internal_bad_customer_done": sum(
            bucket["cross"][(internal, customer)] for internal in INTERNAL_BAD for customer in bucket["customer"] if
            customer != EMPTY),
        "customer_pass_duration": bucket["customer_pass_duration"],
        "customer_pass_bytes": bucket["customer_pass_bytes"],
        "customer_reject_duration": bucket["customer_reject_duration"],
        "customer_reject_bytes": bucket["customer_reject_bytes"],
        "customer_pending_duration": bucket["customer_pending_duration"],
        "customer_pending_bytes": bucket["customer_pending_bytes"],
        "internal_pass_duration": bucket["internal_pass_duration"],
        "internal_pass_bytes": bucket["internal_pass_bytes"],
        "internal_bad_duration": bucket["internal_bad_duration"], "internal_bad_bytes": bucket["internal_bad_bytes"],
        "avg_qa_latency_hours": avg_qa_latency, "qa_latency_count": bucket["qa_latency_count"],
        "release_customer_done": bucket["release_customer_done"],
        "release_customer_reject": bucket["release_customer_reject"],
        "release_customer_reject_rate": pct(bucket["release_customer_reject"], bucket["release_customer_done"]),
    }


def qa_latency_hours(row):
    qc_time = parse_dt(row.get("质检时间"))
    if qc_time is None: return None
    collection_time = parse_dt(row.get("结束录制时间")) or parse_dt(row.get("CREATE TIME"))
    if collection_time is None: return None
    delta = qc_time - collection_time
    hours = delta.total_seconds() / 3600
    if hours < 0: return None
    return hours


def issue_labels(row):
    labels = []
    for field in ISSUE_FIELDS:
        value = clean(row.get(field))
        if value in NEUTRAL_ISSUES or value == EMPTY: continue
        labels.append(f"{field}: {value}")
    return labels or ["未填写原因"]


def collect_feedback_stats(feedback_path):
    """解析增量数据，强制统一反馈日期"""
    inc_records = []
    temp_counts = defaultdict(int)
    report_date = get_report_date()

    for encoding in ['utf-8-sig', 'gbk', 'utf-8']:
        try:
            with feedback_path.open("r", encoding=encoding) as f:
                reader = csv.DictReader(f)
                dec_col = next((h for h in reader.fieldnames if 'decision' in h.lower()), None)
                temp_col = next((h for h in reader.fieldnames if 'template' in h.lower()), None)
                if not dec_col: continue

                for row in reader:
                    dec = clean_val(row.get(dec_col))
                    tmp = clean_val(row.get(temp_col))
                    if any(kw in dec.lower() for kw in ["approve", "imperfect", "perfect"]):
                        chinese_scene = TEMPLATE_CHINESE_MAP.get(tmp, tmp)
                        temp_counts[chinese_scene] += 1

                for scene, count in temp_counts.items():
                    sop_type, _ = classify_scene(scene)
                    inc_records.append({"sop": sop_type, "scene": scene, "count": count, "date": report_date})
                return inc_records
        except:
            continue
    return inc_records


def collect_data(data_path):
    collectors = defaultdict(empty_bucket)
    reviewers = defaultdict(empty_bucket)
    scenes = defaultdict(empty_bucket)
    sop_groups = defaultdict(empty_bucket)
    sop_tasks = defaultdict(empty_bucket)
    sop_collectors = defaultdict(empty_bucket)
    overall = empty_bucket()
    cross = Counter()
    collector_daily = defaultdict(Counter)
    reviewer_daily = defaultdict(Counter)
    production_daily = defaultdict(empty_production_bucket)
    production_scene_daily = defaultdict(lambda: defaultdict(empty_production_bucket))
    customer_daily_overall = defaultdict(empty_bucket)
    customer_daily_sop_tasks = defaultdict(lambda: defaultdict(empty_bucket))
    customer_result_dates = Counter()
    leak_by_collector = defaultdict(int)
    leak_by_reviewer = defaultdict(int)
    leak_by_scene = defaultdict(int)
    issue_all = Counter()
    issue_customer_reject = Counter()
    issue_internal_bad = Counter()
    excluded_scenes = Counter()
    unmatched_scenes = Counter()

    detail_records = defaultdict(int)

    raw_duration = 0.0
    raw_bytes = 0
    included_duration = 0.0
    included_bytes = 0

    with data_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        required = {"TITLE", "采集员", "质检员", "质检结果", "客户质检结果", "PLAY DURATION", "BYTE SIZE", "质检时间",
                    "结束录制时间"}
        missing = required - set(fieldnames)
        if missing: raise ValueError(f"{data_path} 缺少字段: {', '.join(sorted(missing))}")

        row_count = 0
        for row in reader:
            row_count += 1
            duration = parse_number(row.get("PLAY DURATION"))
            byte_size = parse_int(row.get("BYTE SIZE"))
            raw_duration += duration
            raw_bytes += byte_size

            scene = split_scene(row.get("TITLE"))
            if should_exclude_scene(scene):
                excluded_scenes[scene] += 1
                continue

            internal = clean(row.get("质检结果"))
            customer = clean(row.get("客户质检结果"))
            collector = clean(row.get("采集员"))
            reviewer = clean(row.get("质检员"))
            sop_type, sop_task = classify_scene(scene)
            latency = qa_latency_hours(row)
            collection_date = date_key(row.get("开始录制时间")) or date_key(row.get("CREATE TIME"))
            review_date = date_key(row.get("质检时间"))
            customer_date = date_key(row.get("结束录制时间")) or date_key(row.get("CREATE TIME"))

            included_duration += duration
            included_bytes += byte_size

            if internal in INTERNAL_PASS and customer == EMPTY and collection_date:
                detail_records[(sop_type, sop_task, collection_date)] += 1

            for bucket in (overall, collectors[collector], scenes[scene], sop_groups[sop_type],
                           sop_tasks[(sop_type, sop_task)], sop_collectors[(sop_type, collector)]):
                add_record(bucket, internal, customer, duration, byte_size, latency)

            if reviewer != EMPTY:
                add_record(reviewers[reviewer], internal, customer, duration, byte_size, latency)

            if collection_date:
                collector_daily[collection_date][collector] += 1
                add_collection(production_daily[collection_date], duration)
                add_collection(production_scene_daily[collection_date][scene], duration)
            if review_date and reviewer != EMPTY:
                reviewer_daily[review_date][reviewer] += 1
                add_review(production_daily[review_date], internal, duration)
                add_review(production_scene_daily[review_date][scene], internal, duration)
            if customer_date:
                add_record(customer_daily_overall[customer_date], internal, customer, duration, byte_size, latency)
                add_record(customer_daily_sop_tasks[customer_date][(sop_type, sop_task)], internal, customer, duration,
                           byte_size, latency)
                if customer != EMPTY: customer_result_dates[customer_date] += 1

            cross[(internal, customer)] += 1
            if sop_type == "未匹配/其他": unmatched_scenes[scene] += 1

            is_internal_bad = internal in INTERNAL_BAD
            is_customer_reject = customer == CUSTOMER_REJECT
            if is_internal_bad or is_customer_reject:
                for label in issue_labels(row):
                    issue_all[label] += 1
                    if is_internal_bad: issue_internal_bad[label] += 1
                    if is_customer_reject: issue_customer_reject[label] += 1

            if internal in INTERNAL_PASS and customer == CUSTOMER_REJECT:
                leak_by_collector[collector] += 1
                leak_by_scene[scene] += 1
                if reviewer != EMPTY: leak_by_reviewer[reviewer] += 1

    return {
        "fieldnames": fieldnames, "row_count": row_count, "raw_duration": raw_duration, "raw_bytes": raw_bytes,
        "included_duration": included_duration, "included_bytes": included_bytes, "overall": overall,
        "collectors": collectors, "reviewers": reviewers, "collector_daily": collector_daily,
        "reviewer_daily": reviewer_daily, "production_daily": production_daily,
        "production_scene_daily": production_scene_daily, "customer_daily_overall": customer_daily_overall,
        "customer_daily_sop_tasks": customer_daily_sop_tasks, "customer_result_dates": customer_result_dates,
        "scenes": scenes, "sop_groups": sop_groups, "sop_tasks": sop_tasks, "sop_collectors": sop_collectors,
        "cross": cross, "leak_by_collector": leak_by_collector, "leak_by_reviewer": leak_by_reviewer,
        "leak_by_scene": leak_by_scene, "issue_all": issue_all, "issue_customer_reject": issue_customer_reject,
        "issue_internal_bad": issue_internal_bad, "excluded_scenes": excluded_scenes,
        "unmatched_scenes": unmatched_scenes, "detail_records": detail_records,
    }


def cell(value, css_class=""):
    return f'<td class="{esc(css_class)}">{value}</td>' if css_class else f"<td>{value}</td>"


def table(headers, rows, classes=""):
    head = "".join(f"<th>{esc(header)}</th>" for header in headers)
    body = ""
    for row in rows:
        if isinstance(row, str) and row.startswith("<tr"):
            body += row
        else:
            body += "<tr>" + "".join(row) + "</tr>"
    return f'<table class="{esc(classes)}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def status_class(rate, reverse=False):
    if rate is None: return "neutral"
    score = 1 - rate if reverse else rate
    if score >= 0.9: return "good"
    if score >= 0.75: return "warn"
    return "bad"


def metric_bar(rate, css="blue"):
    width = 0 if rate is None else max(0, min(rate * 100, 100))
    return f'<div class="rate"><span>{esc(fmt_pct(rate))}</span><i><b class="{esc(css)}" style="width:{width:.1f}%"></b></i></div>'


def card(label, value, note):
    return f'<article class="card"><div class="label">{esc(label)}</div><div class="value">{esc(value)}</div><div class="note-text">{esc(note)}</div></article>'


def top_rate(items, metric_key, min_done_key, min_done=100, reverse=True):
    eligible = [item for item in items if item[1][metric_key] is not None and item[1][min_done_key] >= min_done]
    return sorted(eligible, key=lambda item: item[1][metric_key], reverse=reverse)


def bar_list(title, items, metric_key, value_formatter, limit=8, max_value=None):
    selected = items[:limit]
    if max_value is None: max_value = max((item[1][metric_key] or 0 for item in selected), default=0)
    rows = []
    for name, metric in selected:
        value = metric[metric_key] or 0
        width = 0 if not max_value else max(0, min(value / max_value * 100, 100))
        rows.append(
            f'<div class="bar-row"><div class="bar-name">{esc(name)}</div><div class="bar-track"><div class="bar-fill" style="width:{width:.1f}%"></div></div><div class="bar-number">{esc(value_formatter(value))}</div></div>')
    return f'<article class="top-panel"><h2>{esc(title)}</h2><div class="bar-list">{"".join(rows)}</div></article>'


def build_top_panels(collector_metrics):
    customer_reject_items = top_rate(collector_metrics, "customer_reject_rate", "customer_done", min_done=1000)[:8]
    internal_bad_items = top_rate(collector_metrics, "internal_bad_rate", "internal_done", min_done=1000)[:8]
    volume_items = sorted(collector_metrics, key=lambda item: item[1]["total"], reverse=True)[:8]
    volume_max = max((metric["total"] for _, metric in volume_items), default=0)
    return f'<section class="top-grid">{bar_list("客户 Reject 率 Top 8（客户已填 ≥ 1000）", customer_reject_items, "customer_reject_rate", fmt_pct, max_value=1)}{bar_list("内检不通过/异常率 Top 8（内检已填 ≥ 1000）", internal_bad_items, "internal_bad_rate", fmt_pct, max_value=1)}{bar_list("任务量 Top 8", volume_items, "total", lambda value: fmt_int(value), max_value=volume_max)}</section>'


def build_collector_table(collectors):
    rows = []
    for name, bucket in sorted(collectors.items(), key=lambda item: bucket_metrics(item[1])["total"], reverse=True):
        m = bucket_metrics(bucket)
        rows.append(
            [cell(esc(name)), cell(fmt_int(m["total"])), cell(fmt_hours(m["duration"])), cell(fmt_storage(m["bytes"])),
             cell(metric_bar(m["internal_pass_rate"], "green"), status_class(m["internal_pass_rate"])),
             cell(metric_bar(m["internal_bad_rate"], "red"), status_class(m["internal_bad_rate"], reverse=True)),
             cell(fmt_int(m["customer_done"])), cell(fmt_int(m["customer_pass"])),
             cell(fmt_hours(m["customer_pass_duration"])),
             cell(metric_bar(m["customer_pass_rate"], "green"), status_class(m["customer_pass_rate"])),
             cell(fmt_int(m["customer_reject"])),
             cell(metric_bar(m["customer_reject_rate"], "red"), status_class(m["customer_reject_rate"], reverse=True)),
             cell(fmt_int(m["customer_pending"])), cell(fmt_duration_hours(m["avg_qa_latency_hours"]))])
    return table(
        ["采集员", "产量", "总时长(小时)", "总数据量", "内部通过率", "内部不通过/异常率", "客户已填", "客户通过数",
         "客户通过时长(小时)", "客户通过率", "客户 Reject 数", "客户 Reject 率", "待客户验收", "平均采集到质检耗时"],
        rows, "data-table")


def build_reviewer_table(reviewers):
    rows = []
    for name, bucket in sorted(reviewers.items(),
                               key=lambda item: (sum(item[1]["internal"][s] for s in INTERNAL_PASS), item[1]["total"]),
                               reverse=True):
        m = bucket_metrics(bucket)
        release_count = m["internal_pass"]
        rows.append([cell(esc(name)), cell(fmt_int(m["total"])), cell(fmt_hours(m["duration"])),
                     cell(fmt_seconds(m["avg_duration"] or 0)), cell(fmt_storage(m["bytes"])),
                     cell(fmt_int(release_count)),
                     cell(metric_bar(m["internal_pass_rate"], "green"), status_class(m["internal_pass_rate"])),
                     cell(fmt_int(m["release_customer_done"])), cell(fmt_int(m["release_customer_reject"])),
                     cell(metric_bar(m["release_customer_reject_rate"], "red"),
                          status_class(m["release_customer_reject_rate"], reverse=True)),
                     cell(fmt_hours(m["customer_pass_duration"])), cell(fmt_storage(m["customer_pass_bytes"])),
                     cell(fmt_hours(m["internal_pass_duration"])), cell(fmt_storage(m["internal_pass_bytes"])),
                     cell(fmt_hours(m["internal_bad_duration"])), cell(fmt_storage(m["internal_bad_bytes"])),
                     cell(fmt_hours(m["customer_reject_duration"])), cell(fmt_storage(m["customer_reject_bytes"])),
                     cell(fmt_duration_hours(m["avg_qa_latency_hours"]))])
    return table(["质检员", "质检量", "质检数据时长(小时)", "平均时长(秒/条)", "质检数据量", "内部放行量", "内部放行率",
                  "放行且客户已填", "放行后客户 Reject", "放行后客户 Reject 率", "客户通过时长(小时)", "客户通过数据量",
                  "内部通过时长(小时)", "内部通过数据量", "内部拒绝时长(小时)", "内部拒绝数据量",
                  "客户 Reject 时长(小时)", "客户 Reject 数据量", "平均采集到质检耗时"], rows, "data-table")


def build_sop_group_table(sop_groups):
    rows = []
    for sop_type, bucket in sorted(sop_groups.items(), key=lambda item: SOP_ORDER.get(item[0], 99)):
        m = bucket_metrics(bucket)
        cells = [cell(esc(sop_type)), cell(fmt_int(m["total"])), cell(fmt_int(m["customer_done"])),
                 cell(fmt_int(m["customer_pass"])), cell(fmt_hours(m["customer_pass_duration"])),
                 cell(metric_bar(m["customer_pass_rate"], "green"), status_class(m["customer_pass_rate"])),
                 cell(fmt_int(m["customer_reject"])), cell(metric_bar(m["customer_reject_rate"], "red"),
                                                           status_class(m["customer_reject_rate"], reverse=True)),
                 cell(fmt_int(m["internal_bad"])),
                 cell(metric_bar(m["internal_bad_rate"], "red"), status_class(m["internal_bad_rate"], reverse=True)),
                 cell(fmt_hours(m["duration"])), cell(fmt_seconds(m["avg_duration"] or 0)),
                 cell(fmt_storage(m["bytes"])), cell(fmt_storage(m["avg_bytes"] or 0)),
                 cell(fmt_storage(m["customer_pass_bytes"])), cell(fmt_hours(m["internal_pass_duration"])),
                 cell(fmt_storage(m["internal_pass_bytes"])), cell(fmt_hours(m["internal_bad_duration"])),
                 cell(fmt_storage(m["internal_bad_bytes"])), cell(fmt_hours(m["customer_reject_duration"])),
                 cell(fmt_storage(m["customer_reject_bytes"])), cell(fmt_duration_hours(m["avg_qa_latency_hours"]))]
        rows.append(f'<tr data-sop="{esc(sop_type)}">{"".join(cells)}</tr>')
    return table(["SOP 类型", "记录数", "客户已填", "客户通过数", "客户通过时长(小时)", "客户通过率", "客户 Reject 数",
                  "客户 Reject 率", "内部不通过/异常数", "内部不通过/异常率", "总时长(小时)", "平均时长(秒/条)",
                  "总数据量", "平均数据量/条", "客户通过数据量", "内部通过时长(小时)", "内部通过数据量",
                  "内部拒绝时长(小时)", "内部拒绝数据量", "客户 Reject 时长(小时)", "客户 Reject 数据量",
                  "平均采集到质检耗时"], rows, "data-table")


def build_sop_task_table(sop_tasks):
    rows = []
    ranked = sorted(sop_tasks.items(),
                    key=lambda item: (SOP_ORDER.get(item[0][0], 99), -bucket_metrics(item[1])["customer_reject"],
                                      -(bucket_metrics(item[1])["customer_reject_rate"] or 0), item[0][1]))
    for (sop_type, sop_task), bucket in ranked:
        m = bucket_metrics(bucket)
        cells = [cell(esc(sop_type)), cell(esc(sop_task)), cell(fmt_int(m["total"])), cell(fmt_int(m["customer_done"])),
                 cell(fmt_int(m["customer_pass"])), cell(fmt_hours(m["customer_pass_duration"])),
                 cell(metric_bar(m["customer_pass_rate"], "green"), status_class(m["customer_pass_rate"])),
                 cell(fmt_int(m["customer_reject"])), cell(metric_bar(m["customer_reject_rate"], "red"),
                                                           status_class(m["customer_reject_rate"], reverse=True)),
                 cell(fmt_int(m["internal_bad"])),
                 cell(metric_bar(m["internal_bad_rate"], "red"), status_class(m["internal_bad_rate"], reverse=True)),
                 cell(fmt_int(m["customer_pending"])), cell(fmt_hours(m["duration"])),
                 cell(fmt_seconds(m["avg_duration"] or 0)), cell(fmt_storage(m["bytes"])),
                 cell(fmt_storage(m["avg_bytes"] or 0)), cell(fmt_storage(m["customer_pass_bytes"])),
                 cell(fmt_hours(m["internal_pass_duration"])), cell(fmt_storage(m["internal_pass_bytes"])),
                 cell(fmt_hours(m["internal_bad_duration"])), cell(fmt_storage(m["internal_bad_bytes"])),
                 cell(fmt_hours(m["customer_reject_duration"])), cell(fmt_storage(m["customer_reject_bytes"]))]
        rows.append(f'<tr data-sop="{esc(sop_type)}">{"".join(cells)}</tr>')
    return table(
        ["SOP 类型", "SOP 任务/场景归类", "记录数", "客户已填", "客户通过数", "客户通过时长(小时)", "客户通过率",
         "客户 Reject 数", "客户 Reject 率", "内部不通过/异常数", "内部不通过/异常率", "待客户验收", "总时长(小时)",
         "平均时长(秒/条)", "总数据量", "平均数据量/条", "客户通过数据量", "内部通过时长(小时)", "内部通过数据量",
         "内部拒绝时长(小时)", "内部拒绝数据量", "客户 Reject 时长(小时)", "客户 Reject 数据量"], rows, "data-table")


def build_sop_collector_table(sop_collectors):
    rows = []
    ranked = sorted(sop_collectors.items(),
                    key=lambda item: (SOP_ORDER.get(item[0][0], 99), -bucket_metrics(item[1])["customer_reject"],
                                      item[0][1]))
    for (sop_type, collector), bucket in ranked:
        m = bucket_metrics(bucket)
        cells = [cell(esc(sop_type)), cell(esc(collector)), cell(fmt_int(m["total"])), cell(fmt_hours(m["duration"])),
                 cell(fmt_seconds(m["avg_duration"] or 0)), cell(fmt_storage(m["bytes"])),
                 cell(fmt_storage(m["avg_bytes"] or 0)), cell(fmt_hours(m["customer_pass_duration"])),
                 cell(fmt_storage(m["customer_pass_bytes"])), cell(fmt_hours(m["internal_pass_duration"])),
                 cell(fmt_storage(m["internal_pass_bytes"])), cell(fmt_hours(m["internal_bad_duration"])),
                 cell(fmt_storage(m["internal_bad_bytes"])), cell(fmt_hours(m["customer_reject_duration"])),
                 cell(fmt_storage(m["customer_reject_bytes"])), cell(fmt_int(m["customer_done"])),
                 cell(fmt_int(m["customer_reject"])), cell(metric_bar(m["customer_reject_rate"], "red"),
                                                           status_class(m["customer_reject_rate"], reverse=True)),
                 cell(fmt_int(m["internal_done"])),
                 cell(metric_bar(m["internal_bad_rate"], "red"), status_class(m["internal_bad_rate"], reverse=True))]
        rows.append(f'<tr data-sop="{esc(sop_type)}">{"".join(cells)}</tr>')
    return table(["SOP 类型", "采集员", "记录数", "总时长(小时)", "平均时长(秒/条)", "总数据量", "平均数据量/条",
                  "客户通过时长(小时)", "客户通过数据量", "内部通过时长(小时)", "内部通过数据量", "内部拒绝时长(小时)",
                  "内部拒绝数据量", "客户 Reject 时长(小时)", "客户 Reject 数据量", "客户已填", "客户 Reject 数",
                  "客户 Reject 率", "内检已填", "内检不通过/异常率"], rows, "data-table")


def build_discrepancy_table(collectors):
    rows = []
    ranked = sorted(collectors.items(),
                    key=lambda item: (bucket_metrics(item[1])["internal_pass_customer_reject_rate"] or -1,
                                      bucket_metrics(item[1])["internal_pass_customer_reject"]), reverse=True)
    for collector, bucket in ranked:
        m = bucket_metrics(bucket)
        rows.append([cell(esc(collector)), cell(fmt_int(m["internal_pass_customer_reject"])),
                     cell(fmt_int(m["internal_pass_customer_done"])),
                     cell(metric_bar(m["internal_pass_customer_reject_rate"], "red"),
                          status_class(m["internal_pass_customer_reject_rate"], reverse=True))])
    return table(["采集员", "内检通过但客户 Reject", "内检通过且客户已填", "偏差率"], rows, "data-table")


def build_reason_table(issue_all, issue_internal_bad, issue_customer_reject):
    rows = []
    for label, count in issue_all.most_common(30): rows.append(
        [cell(esc(label)), cell(fmt_int(count)), cell(fmt_int(issue_internal_bad[label])),
         cell(fmt_int(issue_customer_reject[label]))])
    return table(["失败原因", "总出现次数", "内部不通过/异常", "客户 Reject"], rows, "data-table")


def build_cross_table(cross):
    internal_order = ["质检优秀", "质检合格", "质检不通过", "异常数据", "数据错误--", EMPTY]
    customer_order = ["Perfect", "Approve", "Imperfect", "Reject", EMPTY]
    rows = []
    for internal in internal_order:
        counts = [cross[(internal, customer)] for customer in customer_order]
        rows.append([cell(esc(internal))] + [cell(fmt_int(count)) for count in counts] + [cell(fmt_int(sum(counts)))])
    return table(["质检结果"] + customer_order + ["合计"], rows, "data-table")


def build_leak_table(leak_by_reviewer, reviewers):
    rows = []
    for reviewer, leak_count in sorted(leak_by_reviewer.items(), key=lambda item: item[1], reverse=True):
        m = bucket_metrics(reviewers[reviewer])
        rows.append([cell(esc(reviewer)), cell(fmt_int(m["internal_pass"])), cell(fmt_int(m["release_customer_done"])),
                     cell(fmt_int(leak_count)), cell(metric_bar(m["release_customer_reject_rate"], "red"),
                                                     status_class(m["release_customer_reject_rate"], reverse=True))])
    return table(["质检员", "内部放行量", "放行且客户已填", "放行后客户 Reject", "放行后客户 Reject 率"], rows,
                 "data-table")


def build_counter_table(title, counter, headers):
    rows = [[cell(esc(name)), cell(fmt_int(count))] for name, count in counter.most_common()]
    return f'<section class="panel"><h2>{esc(title)}</h2><div class="table-wrap">{table(headers, rows, "data-table compact")}</div></section>'


def recent_seven_dates(*daily_counters):
    dates = set()
    for counter in daily_counters: dates.update(counter.keys())
    if not dates: return []
    today = datetime.now().date()
    parsed_dates = [datetime.fromisoformat(day).date() for day in dates]
    valid_dates = [day for day in parsed_dates if day <= today]
    end_date = max(valid_dates or parsed_dates)
    return [(end_date - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]


def build_daily_matrix_table(daily_counter, dates, person_header):
    totals = Counter()
    for date in dates: totals.update(daily_counter.get(date, {}))
    people = sorted(totals, key=lambda name: (-totals[name], name))
    rows = []
    for person in people:
        row_total = sum(daily_counter.get(date, {}).get(person, 0) for date in dates)
        rows.append(
            [cell(esc(person)), cell(fmt_int(row_total))] + [cell(fmt_int(daily_counter.get(date, {}).get(person, 0)))
                                                             for date in dates])
    total_row = [cell("<strong>合计</strong>"), cell(f"<strong>{fmt_int(sum(totals.values()))}</strong>")] + [
        cell(f"<strong>{fmt_int(sum(daily_counter.get(date, {}).values()))}</strong>") for date in dates]
    rows.insert(0, total_row)
    return table([person_header, "7天合计"] + dates, rows, "data-table daily-table")


def build_recent_tabs(data):
    dates = recent_seven_dates(data["collector_daily"], data["reviewer_daily"])
    if not dates: return '<section class="panel"><h2>最近 7 天产能</h2><p class="empty-state">没有可解析的采集或质检日期。</p></section>'
    collector_total = sum(sum(data["collector_daily"].get(date, {}).values()) for date in dates)
    reviewer_total = sum(sum(data["reviewer_daily"].get(date, {}).values()) for date in dates)
    return f'<section class="panel"><h2>最近 7 天产能</h2><p class="section-note">采集量按开始录制时间统计，缺失时使用 CREATE TIME；质检量按质检时间统计。日期范围：{esc(dates[0])} 至 {esc(dates[-1])}。</p><div class="tabs"><input type="radio" name="recent-tabs" id="tab-collectors" checked><input type="radio" name="recent-tabs" id="tab-reviewers"><div class="tab-labels"><label for="tab-collectors">采集员采集量（{fmt_int(collector_total)}）</label><label for="tab-reviewers">质检员质检量（{fmt_int(reviewer_total)}）</label></div><div class="tab-panel collector-panel"><div class="table-wrap">{build_daily_matrix_table(data["collector_daily"], dates, "采集员")}</div></div><div class="tab-panel reviewer-panel"><div class="table-wrap">{build_daily_matrix_table(data["reviewer_daily"], dates, "质检员")}</div></div></div></section>'


def current_and_previous_dates(production_daily):
    dates = recent_seven_dates(production_daily)
    return dates[-2:] if len(dates) >= 2 else dates


def production_cells(bucket):
    m = production_metrics(bucket)
    return [cell(fmt_int(m["collected_count"])), cell(fmt_hours(m["collected_duration"])),
            cell(fmt_int(m["reviewed_count"])), cell(fmt_hours(m["reviewed_duration"])),
            cell(fmt_int(m["review_pass_count"])), cell(fmt_hours(m["review_pass_duration"])),
            cell(metric_bar(m["review_pass_rate"], "green"), status_class(m["review_pass_rate"]))]


def build_today_summary_table(production_daily, dates):
    rows = []
    labels = ["前一天", "当天"] if len(dates) == 2 else ["当天"]
    for label, date in zip(labels, dates): rows.append(
        [cell(esc(label)), cell(esc(date))] + production_cells(production_daily.get(date, empty_production_bucket())))
    return table(["日期类型", "日期", "采集条数", "采集时长(小时)", "质检条数", "质检时长(小时)", "质检通过条数",
                  "质检通过时长(小时)", "质检通过率"], rows, "data-table compact")


def scene_total_for_dates(scene_daily, scene, dates):
    total = empty_production_bucket()
    for date in dates: merge_production_bucket(total, scene_daily.get(date, {}).get(scene, empty_production_bucket()))
    return total


def build_today_scene_table(production_scene_daily, dates):
    scenes = set()
    for date in dates: scenes.update(production_scene_daily.get(date, {}).keys())
    ranked = sorted(scenes,
                    key=lambda scene: (scene_total_for_dates(production_scene_daily, scene, dates)["collected_count"],
                                       scene_total_for_dates(production_scene_daily, scene, dates)["reviewed_count"],
                                       scene), reverse=True)
    headers = ["场景"]
    date_labels = ["前一天", "当天"] if len(dates) == 2 else ["当天"]
    for label, date in zip(date_labels, dates): headers.extend(
        [f"{label}({date})采集条数", f"{label}采集时长(小时)", f"{label}质检条数", f"{label}质检时长(小时)",
         f"{label}质检通过条数", f"{label}质检通过时长(小时)", f"{label}质检通过率"])
    rows = []
    for scene in ranked:
        row = [cell(esc(scene))]
        for date in dates: row.extend(
            production_cells(production_scene_daily.get(date, {}).get(scene, empty_production_bucket())))
        rows.append(row)
    return table(headers, rows, "data-table daily-table")


def build_today_tabs(data):
    dates = current_and_previous_dates(data["production_daily"])
    if not dates: return '<section class="panel"><h2>当天/前一天产能</h2><p class="empty-state">没有可解析的采集或质检日期。</p></section>'
    return f'<section class="panel"><h2>当天/前一天产能</h2><p class="section-note">当天按报告生成日及之前的最新有效日期取值；采集用开始录制时间，缺失时用 CREATE TIME；质检用质检时间。当前对比日期：{esc(" / ".join(dates))}。</p><div class="tabs two-day-tabs"><input type="radio" name="two-day-tabs" id="tab-two-day-summary" checked><input type="radio" name="two-day-tabs" id="tab-two-day-scenes"><div class="tab-labels"><label for="tab-two-day-summary">总览</label><label for="tab-two-day-scenes">按场景</label></div><div class="tab-panel two-day-summary-panel"><div class="table-wrap">{build_today_summary_table(data["production_daily"], dates)}</div></div><div class="tab-panel two-day-scenes-panel"><div class="table-wrap">{build_today_scene_table(data["production_scene_daily"], dates)}</div></div></div></section>'


def customer_quality_rate_cell(rate, color, reverse=False): return cell(metric_bar(rate, color),
                                                                        f"quality-rate-cell {status_class(rate, reverse=reverse)}")


def customer_quality_cells(bucket):
    m = bucket_metrics(bucket)
    return [cell(fmt_int(m["total"])), cell(fmt_hours(m["duration"])), cell(fmt_int(m["internal_done"])),
            cell(fmt_int(m["internal_pass"])), cell(fmt_hours(m["internal_pass_duration"])),
            cell(metric_bar(m["internal_pass_rate"], "green"), status_class(m["internal_pass_rate"])),
            cell(fmt_int(m["internal_bad"])), cell(fmt_hours(m["internal_bad_duration"])),
            cell(metric_bar(m["internal_bad_rate"], "red"), status_class(m["internal_bad_rate"], reverse=True)),
            cell(fmt_int(m["customer_done"])), cell(fmt_int(m["customer_pass"])),
            cell(fmt_hours(m["customer_pass_duration"])), customer_quality_rate_cell(m["customer_pass_rate"], "green"),
            cell(fmt_int(m["customer_reject"])), cell(fmt_hours(m["customer_reject_duration"])),
            customer_quality_rate_cell(m["customer_reject_rate"], "red", reverse=True),
            cell(fmt_int(m["customer_pending"]))]


def build_customer_quality_table(overall_bucket, sop_task_buckets):
    rows = [
        f'<tr data-sop="总值">{cell("<strong>总值</strong>")} {cell("")} {"".join(customer_quality_cells(overall_bucket))}</tr>']
    ranked = sorted(sop_task_buckets.items(),
                    key=lambda item: (SOP_ORDER.get(item[0][0], 99), -bucket_metrics(item[1])["customer_done"],
                                      -bucket_metrics(item[1])["customer_reject"], item[0][1]))
    for (sop_type, sop_task), bucket in ranked:
        cells = [cell(esc(sop_type)), cell(esc(sop_task))] + customer_quality_cells(bucket)
        rows.append(f'<tr data-sop="{esc(sop_type)}">{"".join(cells)}</tr>')
    return table(["SOP 类型", "SOP 任务/场景归类", "当天采集数", "当天采集时长(小时)", "内部质检数", "内部通过数",
                  "内部通过时长(小时)", "内部通过率", "内部不通过/异常数", "内部不通过/异常时长(小时)", "内部拒绝率",
                  "客户已填", "客户通过数", "客户通过时长(小时)", "客户通过率", "客户 Reject 数",
                  "客户 Reject 时长(小时)", "客户 Reject 率", "待客户验收"], rows, "data-table customer-quality-table")


def build_customer_quality_by_date(data, sop_options):
    dates = sorted(data["customer_result_dates"])
    if not dates: return '<section class="panel"><h2>客户质检质量（按日期）</h2><p class="empty-state">没有客户质检结果已填写且可解析日期的记录。</p></section>'
    default_date = dates[-1]
    options = "".join(
        f'<option value="{esc(date)}"{" selected" if date == default_date else ""}>{esc(date)}</option>' for date in
        reversed(dates))
    panels = "".join([
        f'<div class="customer-quality-panel" data-customer-date="{esc(date)}"{" hidden" if date != default_date else ""}><div class="table-wrap">{build_customer_quality_table(data["customer_daily_overall"][date], data["customer_daily_sop_tasks"][date])}</div></div>'
        for date in dates])
    return f'<section class="panel customer-quality-section"><div class="panel-heading-row"><div><h2 style="margin:0;">客户质检质量（按日期）</h2><p class="section-note">日期按结束录制时间统计，缺失时使用 CREATE TIME；表内采集和内部质检指标统计当天全部记录，客户指标统计其中客户质检结果已填写的记录。</p></div><div style="display:flex;gap:10px;"><select id="customer-quality-sop-filter" class="date-picker" onchange="applyPanelSopFilter(this)"><option value="all">-- 所有 SOP 版本 --</option>{sop_options}</select><label class="date-picker-label" for="customer-quality-date">日期 <select id="customer-quality-date" class="date-picker">{options}</select></label></div></div>{panels}</section>'


def build_filter_html(prefix, scenes):
    scene_options = "".join([
        f'<label data-pinyin="{esc(get_pinyin_index(s))}"><input type="checkbox" class="{prefix}-cb" value="{esc(s)}" onchange="window.apply{prefix}Filters()"> {esc(s)}</label>'
        for s in sorted(scenes)])
    return f"""
    <div class="multi-select-wrapper">
        <div class="multi-select-btn" onclick="toggleDrop('{prefix}-drop')">筛选场景任务 <span style="font-size:10px;">▼</span></div>
        <div class="multi-select-dropdown" id="{prefix}-drop">
            <div class="dropdown-search"><input type="text" placeholder="拼音或首字母检索..." onkeyup="filterList(this.value, '{prefix}-list')"></div>
            <div id="{prefix}-list">
                <label><input type="checkbox" id="{prefix}-all" checked onchange="handleAllClick('{prefix}')"> -- 全部场景 --</label>
                {scene_options}
            </div>
        </div>
    </div>
    """


def build_html(data, data_path, inc_data):
    overall = bucket_metrics(data["overall"])
    collectors_metrics = [(name, bucket_metrics(bucket)) for name, bucket in data["collectors"].items()]
    reviewers_metrics = [(name, bucket_metrics(bucket)) for name, bucket in data["reviewers"].items()]
    scenes_metrics = [(name, bucket_metrics(bucket)) for name, bucket in data["scenes"].items()]

    top_collector_reject = top_rate(collectors_metrics, "customer_reject_rate", "customer_done")[:1]
    top_reviewer_leak = sorted(data["leak_by_reviewer"].items(), key=lambda item: item[1], reverse=True)[:1]
    top_scene_reject = sorted(scenes_metrics,
                              key=lambda item: (item[1]["customer_reject"], item[1]["customer_reject_rate"] or 0),
                              reverse=True)[:1]

    insight_1 = f"{top_collector_reject[0][0]}：客户 Reject 率 {fmt_pct(top_collector_reject[0][1]['customer_reject_rate'])}，Reject {fmt_int(top_collector_reject[0][1]['customer_reject'])} 条。" if top_collector_reject else "暂无客户已填数量超过阈值的采集员。"
    insight_2 = f"{top_reviewer_leak[0][0]}：放行后客户 Reject {fmt_int(top_reviewer_leak[0][1])} 条。" if top_reviewer_leak else "暂无内部放行后客户 Reject 的质检员记录。"
    insight_3 = f"{top_scene_reject[0][0]}：客户 Reject {fmt_int(top_scene_reject[0][1]['customer_reject'])} 条，Reject 率 {fmt_pct(top_scene_reject[0][1]['customer_reject_rate'])}。" if top_scene_reject else "暂无客户 Reject 场景。"

    cards = [
        card("CSV 原始行数", fmt_int(data["row_count"]), f"字段数 {len(data['fieldnames'])}"),
        card("纳入统计的 records 数", fmt_int(overall["total"]), f"剔除 {sum(data['excluded_scenes'].values()):,} 条"),
        card("总时长", f"{fmt_hours(overall['duration'])} 小时", "PLAY DURATION 按秒汇总"),
        card("总数据量", fmt_storage(overall["bytes"]), "BYTE SIZE 按 1024 进制展示"),
        card("内部质检数量", fmt_int(overall["internal_done"]), "质检结果已填写"),
        card("内部质检通过数量", fmt_int(overall["internal_pass"]), "质检合格 + 质检优秀"),
        card("内部质检通过时长", f"{fmt_hours(overall['internal_pass_duration'])} 小时",
             "内部通过 records 的 PLAY DURATION"),
        card("内部质检通过大小", fmt_storage(overall["internal_pass_bytes"]), "内部通过 records 的 BYTE SIZE"),
        card("内部质检拒绝数量", fmt_int(overall["internal_bad"]), "质检不通过 + 异常数据 + 数据错误--"),
        card("内部质检拒绝时长", f"{fmt_hours(overall['internal_bad_duration'])} 小时",
             "内部不通过/异常 records 的 PLAY DURATION"),
        card("内部质检拒绝大小", fmt_storage(overall["internal_bad_bytes"]), "内部不通过/异常 records 的 BYTE SIZE"),
        card("客户质检数量", fmt_int(overall["customer_done"]), "客户质检结果已填写"),
        card("客户通过时长", f"{fmt_hours(overall['customer_pass_duration'])} 小时", "三种通过状态合计"),
        card("客户通过大小", fmt_storage(overall["customer_pass_bytes"]), "Approve + Perfect + Imperfect"),
        card("客户质检拒绝数量", fmt_int(overall["customer_reject"]), "客户 Reject"),
        card("客户质检拒绝时长", f"{fmt_hours(overall['customer_reject_duration'])} 小时",
             "客户 Reject records 的 PLAY DURATION"),
        card("客户质检拒绝大小", fmt_storage(overall["customer_reject_bytes"]), "客户 Reject records 的 BYTE SIZE"),
        card("待客户验收数量", fmt_int(overall["customer_pending"]), "客户质检结果为空"),
        card("待客户验收时长", f"{fmt_hours(overall['customer_pending_duration'])} 小时",
             "待客户验收 records 的 PLAY DURATION"),
        card("待客户验收大小", fmt_storage(overall["customer_pending_bytes"]), "待客户验收 records 的 BYTE SIZE"),
    ]

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ========= 新模块数据准备 =========
    master_detail_list = [{"sop": k[0], "scene": k[1], "date": k[2], "count": v} for k, v in
                          data["detail_records"].items()]
    inc_scenes = set(r['scene'] for r in inc_data)
    master_scenes = set(r['scene'] for r in master_detail_list)

    master_sops = sorted(list(set(r['sop'] for r in master_detail_list) | set(r['sop'] for r in inc_data)),
                         key=lambda x: SOP_ORDER.get(x, 99))
    if not master_sops: master_sops = sorted(list(SOP_ORDER.keys() - {"未匹配/其他"}),
                                             key=lambda x: SOP_ORDER.get(x, 99))
    sop_options = "".join([f'<option value="{esc(s)}">{esc(s)}</option>' for s in master_sops])

    total_inc = sum(r['count'] for r in inc_data)
    total_master = sum(r['count'] for r in master_detail_list)

    inc_rows = "".join([
        f'<tr data-sop="{esc(r["sop"])}" data-scene="{esc(r["scene"])}" data-count="{r["count"]}"><td>{r["sop"]}</td><td>{r["scene"]}</td><td><b style="color:var(--green)">+{r["count"]}</b></td><td>{r["date"]}</td></tr>'
        for r in sorted(inc_data, key=lambda x: -x['count'])])
    master_rows = "".join([
        f'<tr data-sop="{esc(r["sop"])}" data-scene="{esc(r["scene"])}" data-date="{esc(r["date"])}" data-count="{r["count"]}"><td>{r["sop"]}</td><td>{r["scene"]}</td><td><b style="color:var(--blue)">{r["count"]}</b></td><td>{r["date"]}</td></tr>'
        for r in
        sorted(master_detail_list, key=lambda x: (x['date'], -x['count']), reverse=True)])

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(data_path.stem)} 数据验收日报</title>
  <style>
    :root {{ --bg: #f0f2f5; --paper: #ffffff; --ink: #18212f; --muted: #687586; --line: #dde4ed; --blue: #2f6fbe; --green: #21855a; --red: #c4473d; --amber: #b77816; --soft-green: #edf8f2; --soft-red: #fff0ef; --soft-amber: #fff7e8; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; line-height: 1.5; }}
    header {{ background: #1f2d3d; color: white; padding: 25px 40px; box-shadow: 0 2px 10px rgba(0,0,0,0.2); }}
    h1 {{ margin: 0 0 8px; font-size: 26px; letter-spacing: 0; }}
    header p {{ margin: 0; color: #cdd7e3; font-size: 14px; opacity:0.9; }}
    main {{ max-width: 1360px; margin: 0 auto; padding: 26px 24px 44px; }}
    .method {{ background: var(--paper); border: 1px solid var(--line); border-left: 4px solid var(--blue); padding: 14px 16px; color: var(--muted); margin-bottom: 18px; font-size: 13px; }}
    .cards {{ display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }}
    .card {{ background: var(--paper); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .label {{ color: var(--muted); font-size: 12px; }}
    .value {{ margin-top: 3px; font-size: 24px; font-weight: 700; }}
    .note-text {{ margin-top: 4px; color: var(--muted); font-size: 12px; }}
    .insights {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-bottom: 18px; }}
    .insight, .panel {{ background: var(--paper); border: 1px solid var(--line); border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
    .top-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-bottom: 18px; }}
    .top-panel {{ background: var(--paper); border: 1px solid var(--line); border-radius: 8px; padding: 18px; }}
    .top-panel h2 {{ margin: 0 0 14px; font-size: 16px; }}
    .bar-row {{ display: grid; grid-template-columns: 72px 1fr 56px; gap: 10px; align-items: center; margin: 9px 0; font-size: 13px; }}
    .bar-name {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .bar-track {{ height: 10px; background: #edf1f5; border-radius: 999px; overflow: hidden; }}
    .bar-fill {{ height: 100%; background: var(--red); border-radius: 999px; }}
    .bar-number {{ text-align: right; color: #53657b; font-variant-numeric: tabular-nums; }}
    .insight {{ padding: 16px; }}
    .insight strong {{ display: block; margin-bottom: 6px; }}
    .insight p {{ margin: 0; color: var(--muted); font-size: 13px; }}
    .panel {{ padding: 22px; margin-bottom: 25px; }}
    .panel h2 {{ margin: 0 0 12px; font-size: 18px; }}
    .panel-heading-row {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 15px; flex-wrap: wrap; }}
    .panel-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; flex-wrap: wrap; gap: 15px; }}
    .panel-title {{ font-size: 18px; font-weight: bold; display: flex; align-items: center; gap: 8px; margin:0; }}
    .total-badge {{ font-size: 13px; font-weight: normal; margin-left: 10px; padding: 3px 10px; border-radius: 20px; border: 1px solid var(--line); background: #fafafa; color: #555; transition: all 0.2s; }}
    .filter-group {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
    .date-picker-label {{ display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 13px; white-space: nowrap; }}
    .date-picker {{ min-width: 140px; padding: 7px 12px; border: 1px solid var(--line); border-radius: 4px; outline: none; background:#fff; cursor: pointer; font-size:13px; color:var(--ink); }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 6px; position: relative; }}
    table {{ border-collapse: collapse; width: 100%; min-width: 980px; font-size: 13px; background: white; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 12px; text-align: left; vertical-align: middle; white-space: nowrap; }}
    th {{ position: sticky; top: 0; background: #f8f9fb; color: #444; font-size: 13px; z-index: 1; box-shadow: 0 1px 0 var(--line); }}
    tr:last-child td {{ border-bottom: 0; }}
    td.good {{ background: var(--soft-green); }}
    td.warn {{ background: var(--soft-amber); }}
    td.bad {{ background: var(--soft-red); }}
    .customer-quality-table tbody tr:first-child td {{ background: #f7f9fb; font-weight: 700; }}
    .rate {{ min-width: 108px; }}
    .rate span {{ display: inline-block; min-width: 42px; font-variant-numeric: tabular-nums; }}
    .rate i {{ display: inline-block; width: 52px; height: 7px; margin-left: 8px; background: #edf1f5; border-radius: 999px; overflow: hidden; vertical-align: middle; }}
    .rate b {{ display: block; height: 100%; border-radius: 999px; }}
    .blue {{ background: var(--blue); }}
    .green {{ background: var(--green); }}
    .red {{ background: var(--red); }}
    .compact {{ min-width: 760px; }}
    .section-note {{ margin: -4px 0 12px; color: var(--muted); font-size: 13px; }}
    .tabs > input {{ position: absolute; opacity: 0; pointer-events: none; }}
    .tab-labels {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }}
    .tab-labels label {{ border: 1px solid var(--line); border-radius: 6px; padding: 8px 12px; color: var(--muted); background: #f7f9fb; cursor: pointer; font-size: 13px; }}
    #tab-collectors:checked ~ .tab-labels label[for="tab-collectors"], #tab-reviewers:checked ~ .tab-labels label[for="tab-reviewers"], #tab-two-day-summary:checked ~ .tab-labels label[for="tab-two-day-summary"], #tab-two-day-scenes:checked ~ .tab-labels label[for="tab-two-day-scenes"] {{ background: var(--blue); border-color: var(--blue); color: #fff; }}
    .tab-panel {{ display: none; }}
    #tab-collectors:checked ~ .collector-panel, #tab-reviewers:checked ~ .reviewer-panel, #tab-two-day-summary:checked ~ .two-day-summary-panel, #tab-two-day-scenes:checked ~ .two-day-scenes-panel {{ display: block; }}
    .daily-table {{ min-width: 900px; }}
    .empty-state {{ margin: 0; color: var(--muted); }}
    .multi-select-wrapper {{ position: relative; width: 190px; }}
    .multi-select-btn {{ border: 1px solid var(--line); padding: 7px 12px; background: #fff; border-radius: 4px; cursor: pointer; display: flex; justify-content: space-between; font-size:13px; }}
    .multi-select-dropdown {{ display: none; position: absolute; background: #fff; border: 1px solid var(--line); width: 280px; max-height: 350px; overflow-y: auto; z-index: 1000; box-shadow: 0 8px 25px rgba(0,0,0,0.15); border-radius: 6px; margin-top: 5px; }}
    .multi-select-dropdown.show {{ display: block; }}
    .dropdown-search {{ position: sticky; top: 0; background: #fff; padding: 8px; border-bottom: 1px solid var(--line); }}
    .dropdown-search input {{ width: 100%; box-sizing: border-box; padding: 6px; border: 1px solid var(--line); border-radius: 4px; outline:none; }}
    .multi-select-dropdown label {{ display: block; padding: 8px 12px; cursor: pointer; font-size: 13px; margin:0; }}
    .multi-select-dropdown label:hover {{ background: #f0f7ff; }}
    footer {{ color: var(--muted); font-size: 12px; margin-top: 18px; }}
  </style>
</head>
<body>
  <header>
    <h1>{esc(data_path.stem)} 数据验收增量日报</h1>
    <p>生成时间：{esc(generated_at)} ｜ 统计包含：当日反馈新增 & 实时存量待验收</p>
  </header>
  <main>
    <section class="method">
      口径：客户通过 = Approve + Perfect + Imperfect；客户拒绝 = Reject；待客户验收 = 内部质检通过且客户质检结果为空。 
           内部通过 = 质检合格 + 质检优秀；内部不通过/异常 = 质检不通过 + 异常数据 + 数据错误--。 
           SOP 分类沿用已确认规则：优先按 TITLE 空格后的场景文案精确匹配；包含“补采”归入 SOP 2.0，包含“0320”归入 SOP 1.0， 包含“（3.0）/ (3.0)”归入 SOP 3.0，包含“（3.0.1）/ (3.0.1)”归入 SOP 3.0.1。 
           “产线分拣-橙蓝物品”和包含“（待确认）”的场景不纳入统计。
    </section>

    <section class="cards">
      {''.join(cards)}
    </section>

    <section class="panel" style="border-top: 5px solid var(--green);">
      <div class="panel-header">
        <div class="panel-title" style="color:var(--green);">
            🌟 每日验收通过增量 (反馈批次：{get_report_date()})
            <span class="total-badge" style="border-color: #b2dfc8; background: #f0f9f4;">当前显示: <b id="inc-total-span" style="color:var(--green); font-size:15px;">{total_inc}</b> 条</span>
        </div>
        <div class="filter-group">
          <select id="inc-sop-filter" class="date-picker" onchange="applyincFilters()">
              <option value="all">-- 所有 SOP 版本 --</option>
              {sop_options}
          </select>
          {build_filter_html('inc', inc_scenes)}
        </div>
      </div>
      <div class="table-wrap">
        <table id="inc-table" class="data-table">
          <thead><tr><th>SOP 版本</th><th>场景任务名称</th><th>新增通过数</th><th>反馈日期</th></tr></thead>
          <tbody id="inc-body">{inc_rows if inc_rows else '<tr><td colspan="4" style="text-align:center;padding:40px;color:#999;">暂未解析到反馈数据</td></tr>'}</tbody>
        </table>
      </div>
    </section>

    <section class="panel" style="border-top: 5px solid var(--blue);">
      <div class="panel-header">
        <div class="panel-title" style="color:var(--blue);">
            📋 实时待客户验收清单 (系统存量)
            <span class="total-badge" style="border-color: #b9d4f5; background: #f2f7fd;">当前显示: <b id="master-total-span" style="color:var(--blue); font-size:15px;">{total_master}</b> 条</span>
        </div>
        <div class="filter-group">
          <select id="master-sop-filter" class="date-picker" onchange="applymasterFilters()">
              <option value="all">-- 所有 SOP 版本 --</option>
              {sop_options}
          </select>
          {build_filter_html('master', master_scenes)}
          <select id="master-date-filter" class="date-picker" onchange="applymasterFilters()"><option value="all">-- 所有录制日期 --</option></select>
        </div>
      </div>
      <div class="table-wrap">
        <table id="master-table" class="data-table">
          <thead><tr><th>SOP 版本</th><th>场景任务名称</th><th>待验收数</th><th>数据录制日期</th></tr></thead>
          <tbody id="master-body">{master_rows}</tbody>
        </table>
      </div>
    </section>

    <section class="insights">
      <article class="insight"><strong>采集侧优先复盘</strong><p>{esc(insight_1)}</p></article>
      <article class="insight"><strong>质检放行风险</strong><p>{esc(insight_2)}</p></article>
      <article class="insight"><strong>场景问题集中度</strong><p>{esc(insight_3)}</p></article>
    </section>

    {build_top_panels(collectors_metrics)}

    <section class="panel">
      <div class="panel-heading-row" style="align-items:center;">
        <h2 style="margin:0;">SOP 类型质量</h2>
        <select class="date-picker" onchange="applyPanelSopFilter(this)">
            <option value="all">-- 所有 SOP 版本 --</option>
            {sop_options}
        </select>
      </div>
      <div class="table-wrap">{build_sop_group_table(data["sop_groups"])}</div>
    </section>

    <section class="panel">
      <div class="panel-heading-row" style="align-items:center;">
        <h2 style="margin:0;">SOP 任务/场景质量（全部）</h2>
        <select class="date-picker" onchange="applyPanelSopFilter(this)">
            <option value="all">-- 所有 SOP 版本 --</option>
            {sop_options}
        </select>
      </div>
      <div class="table-wrap">{build_sop_task_table(data["sop_tasks"])}</div>
    </section>

    <section class="panel">
      <div class="panel-heading-row" style="align-items:center;">
        <h2 style="margin:0;">SOP 类型 × 采集员</h2>
        <select class="date-picker" onchange="applyPanelSopFilter(this)">
            <option value="all">-- 所有 SOP 版本 --</option>
            {sop_options}
        </select>
      </div>
      <div class="table-wrap">{build_sop_collector_table(data["sop_collectors"])}</div>
    </section>

    {build_customer_quality_by_date(data, sop_options)}

    {build_recent_tabs(data)}

    {build_today_tabs(data)}

    <section class="panel"><h2>采集员表现</h2><div class="table-wrap">{build_collector_table(data["collectors"])}</div></section>
    <section class="panel"><h2>质检员表现</h2><div class="table-wrap">{build_reviewer_table(data["reviewers"])}</div></section>
    <section class="panel"><h2>失败原因与客户 Reject 关联</h2><div class="table-wrap">{build_reason_table(data["issue_all"], data["issue_internal_bad"], data["issue_customer_reject"])}</div></section>
    <section class="panel"><h2>内部质检与客户质检偏差</h2><div class="table-wrap">{build_discrepancy_table(data["collectors"])}</div></section>
    <section class="panel"><h2>质检放行后客户 Reject</h2><div class="table-wrap">{build_leak_table(data["leak_by_reviewer"], data["reviewers"])}</div></section>
    <section class="panel"><h2>内部质检 × 客户质检交叉表</h2><div class="table-wrap">{build_cross_table(data["cross"])}</div></section>

    {build_counter_table("未匹配/其他场景", data["unmatched_scenes"], ["场景", "记录数"])}
    {build_counter_table("已剔除场景", data["excluded_scenes"], ["场景", "记录数"])}

    <footer>该报告只包含聚合信息，不包含 record 级明细。</footer>
  </main>

  <script>
    // --- 核心模块：表格折叠/展开管理器 ---
    const tableManager = {{
        expandedTables: new Set(),

        init() {{
            document.querySelectorAll('table.data-table').forEach((table, index) => {{
                if (!table.id) table.id = 'dt-table-' + index;
                this.render(table.id);
            }});
        }},

        toggleExpand(tableId) {{
            if (this.expandedTables.has(tableId)) {{
                this.expandedTables.delete(tableId);
            }} else {{
                this.expandedTables.add(tableId);
            }}
            this.render(tableId);
        }},

        render(tableId) {{
            const table = document.getElementById(tableId);
            if (!table) return;
            const tbody = table.querySelector('tbody');
            if (!tbody) return;

            const rows = Array.from(tbody.querySelectorAll('tr'));
            const isExpanded = this.expandedTables.has(tableId);

            let visibleCount = 0;
            rows.forEach(row => {{
                if (row.getAttribute('data-filtered') === 'true') {{
                    row.style.display = 'none';
                }} else {{
                    visibleCount++;
                    if (!isExpanded && visibleCount > 10) {{
                        row.style.display = 'none';
                    }} else {{
                        row.style.display = '';
                    }}
                }}
            }});

            let btnWrapper = table.nextElementSibling;
            const hasBtnWrapper = btnWrapper && btnWrapper.classList.contains('expand-btn-wrapper');

            if (visibleCount > 10) {{
                if (!hasBtnWrapper) {{
                    btnWrapper = document.createElement('div');
                    btnWrapper.className = 'expand-btn-wrapper';
                    btnWrapper.style.cssText = 'text-align:center; padding:12px 0; border-top:1px dashed var(--line); background:#fcfdfe;';

                    const btn = document.createElement('button');
                    btn.style.cssText = 'background:none; border:none; color:var(--blue); cursor:pointer; font-size:13px; font-weight:bold; width:100%; display:block;';
                    btn.onclick = () => this.toggleExpand(tableId);

                    btnWrapper.appendChild(btn);
                    table.parentNode.insertBefore(btnWrapper, table.nextSibling);
                }}
                const btn = table.nextElementSibling.querySelector('button');
                if (isExpanded) {{
                    btn.innerHTML = `收起 <span style="font-size:10px;">▲</span>`;
                }} else {{
                    btn.innerHTML = `展开查看全部 (${{visibleCount}} 行) <span style="font-size:10px;">▼</span>`;
                }}
                table.nextElementSibling.style.display = 'block';
            }} else {{
                if (hasBtnWrapper) btnWrapper.style.display = 'none';
            }}
        }}
    }};

    // --- 客户质量面板特有逻辑 ---
    (function () {{
      var picker = document.getElementById("customer-quality-date");
      if (!picker) return;
      var section = picker.closest('.customer-quality-section');
      var panels = Array.prototype.slice.call(section.querySelectorAll("[data-customer-date]"));
      function updateCustomerQualityDate() {{
        panels.forEach(function (panel) {{
          panel.hidden = panel.getAttribute("data-customer-date") !== picker.value;
        }});

        // 切换日期后，重新应用当前 SOP 版本筛选，避免只切换日期但表格仍显示未过滤状态。
        var sopSelect = section.querySelector('#customer-quality-sop-filter');
        if (sopSelect && window.applyPanelSopFilter) {{
          window.applyPanelSopFilter(sopSelect);
        }}
      }}
      picker.addEventListener("change", updateCustomerQualityDate);
      updateCustomerQualityDate();
    }})();

    // --- 全局 SOP 筛选逻辑 ---
    function applyPanelSopFilter(selectElem) {{
        const sopVal = selectElem.value;
        const panel = selectElem.closest('.panel');
        if (!panel) return;

        // 普通面板只有一个 table；客户质检质量（按日期）面板有多个日期 table。
        // 这里必须处理全部 table，否则 SOP 筛选只会作用到第一个日期表，切换日期后看起来就像筛选失效。
        const tables = panel.querySelectorAll('table');
        if (!tables.length) return;

        tables.forEach(table => {{
            const rows = table.querySelectorAll('tbody tr');
            rows.forEach(tr => {{
                const sop = tr.getAttribute('data-sop');
                if (!sop) return;
                if (sopVal === 'all' || sop === '总值' || sop === sopVal) {{
                    tr.setAttribute('data-filtered', 'false');
                }} else {{
                    tr.setAttribute('data-filtered', 'true');
                }}
            }});
            if (table.id) tableManager.render(table.id);
        }});
    }}
    window.applyPanelSopFilter = applyPanelSopFilter;

    // --- 多选与拼音检索 ---
    function toggleDrop(id) {{ 
        const el = document.getElementById(id);
        const isShow = el.classList.contains('show');
        document.querySelectorAll('.multi-select-dropdown').forEach(d => d.classList.remove('show'));
        if(!isShow) el.classList.add('show');
    }}

    function filterList(q, listId) {{
        const labels = document.querySelectorAll('#' + listId + ' label');
        labels.forEach(label => {{
            if(label.innerText.includes('--')) return;
            const pinyin = label.getAttribute('data-pinyin') || "";
            const match = label.innerText.toLowerCase().includes(q.toLowerCase()) || pinyin.toLowerCase().includes(q.toLowerCase());
            label.style.display = match ? '' : 'none';
        }});
    }}

    function handleAllClick(prefix) {{
        if(document.getElementById(prefix + '-all').checked) {{
            document.querySelectorAll('.' + prefix + '-cb').forEach(c => c.checked = false);
        }}
        window['apply' + prefix + 'Filters']();
    }}

    document.addEventListener('change', e => {{
        if(e.target.type === 'checkbox' && !e.target.id.includes('all')) {{
            const prefix = e.target.className.split('-')[0];
            document.getElementById(prefix + '-all').checked = false;
            window['apply' + prefix + 'Filters']();
        }}
    }});

    // --- 增量表筛选与自动求和 ---
    function applyincFilters() {{
        const sopVal = document.getElementById('inc-sop-filter').value;
        const isAllScene = document.getElementById('inc-all').checked;
        const checkedScenes = Array.from(document.querySelectorAll('.inc-cb:checked')).map(c => c.value);

        let sum = 0;
        document.querySelectorAll('#inc-body tr').forEach(tr => {{
            const scene = tr.getAttribute('data-scene');
            const sop = tr.getAttribute('data-sop');
            if(!scene) return;

            const sMatch = isAllScene || checkedScenes.includes(scene);
            const sopMatch = sopVal === 'all' || sop === sopVal;

            const show = sMatch && sopMatch;
            tr.setAttribute('data-filtered', show ? 'false' : 'true');
            if(show) sum += parseInt(tr.getAttribute('data-count')) || 0;
        }});
        document.getElementById('inc-total-span').innerText = sum;
        tableManager.render('inc-table');
    }}

    // --- 待办表筛选与自动求和 ---
    function applymasterFilters() {{
        const dateVal = document.getElementById('master-date-filter').value;
        const sopVal = document.getElementById('master-sop-filter').value;
        const isAllScene = document.getElementById('master-all').checked;
        const checkedScenes = Array.from(document.querySelectorAll('.master-cb:checked')).map(c => c.value);

        let sum = 0;
        document.querySelectorAll('#master-body tr').forEach(tr => {{
            const scene = tr.getAttribute('data-scene');
            const date = tr.getAttribute('data-date');
            const sop = tr.getAttribute('data-sop');
            if(!scene) return;

            const sMatch = isAllScene || checkedScenes.includes(scene);
            const dMatch = dateVal === 'all' || date === dateVal;
            const sopMatch = sopVal === 'all' || sop === sopVal;

            const show = sMatch && dMatch && sopMatch;
            tr.setAttribute('data-filtered', show ? 'false' : 'true');
            if(show) sum += parseInt(tr.getAttribute('data-count')) || 0;
        }});
        document.getElementById('master-total-span').innerText = sum;
        tableManager.render('master-table');
    }}

    window.applyincFilters = applyincFilters;
    window.applymasterFilters = applymasterFilters;

    function initDates() {{
        const ds = new Set();
        document.querySelectorAll('#master-body tr').forEach(tr => {{
            const d = tr.getAttribute('data-date');
            if(d && d!=='null') ds.add(d);
        }});
        const sel = document.getElementById('master-date-filter');
        if (sel) {{
            Array.from(ds).sort().reverse().forEach(d => {{
                sel.insertAdjacentHTML('beforeend', `<option value="${{d}}">${{d}}</option>`);
            }});
        }}
    }}

    // --- 页面初始化 ---
    initDates();
    tableManager.init();

    window.onclick = e => {{ if(!e.target.closest('.multi-select-wrapper')) document.querySelectorAll('.multi-select-dropdown').forEach(d => d.classList.remove('show')); }}
  </script>
</body>
</html>
"""


def validate(data):
    errors = []
    overall = bucket_metrics(data["overall"])
    excluded = sum(data["excluded_scenes"].values())
    included_rows = data["row_count"] - excluded

    if overall["total"] != included_rows: errors.append(
        f"included_rows mismatch: overall={overall['total']} raw-excluded={included_rows}")
    if abs(overall["duration"] - data["included_duration"]) > 0.001: errors.append(
        "included duration aggregate mismatch")
    if overall["bytes"] != data["included_bytes"]: errors.append("included byte aggregate mismatch")

    customer_counter = data["overall"]["customer"]
    expected_customer_pass = sum(customer_counter[status] for status in CUSTOMER_PASS)
    if overall["customer_pass"] != expected_customer_pass: errors.append("customer pass definition mismatch")

    if errors: raise SystemExit("Validation failed:\n" + "\n".join(f"- {error}" for error in errors))


def main():
    print("🚀 正在生成完全体报表...")
    data_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_PATH
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT_PATH

    # 查找反馈表
    feedback_file = None
    for f in Path('.').glob('*.csv'):
        if "审核结果" in f.name and "Sheet1" in f.name:
            feedback_file = f
            break
    if not feedback_file: feedback_file = Path("feedback.csv")

    inc_data = []
    if feedback_file.exists():
        inc_data = collect_feedback_stats(feedback_file)
        print(f"✅ 成功提取反馈增量：{sum(r['count'] for r in inc_data)} 条通过数据")
    else:
        print("⚠️ 未找到有效反馈数据(feedback.csv)，增量表将为空。")

    if not data_path.exists():
        print(f"❌ 错误: 找不到总表输入文件 {data_path}")
        return

    print(f"正在读取总表数据: {data_path.name}...")
    data = collect_data(data_path)
    validate(data)

    print(f"正在构建 HTML...")
    html_content = build_html(data, data_path, inc_data)

    with out_path.open("w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"✨ 成功！请在浏览器中打开: {out_path.absolute()}")


if __name__ == "__main__":
    main()

