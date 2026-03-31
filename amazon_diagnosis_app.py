"""
亚马逊运营诊断助手 - Streamlit 应用
功能：根据单指标阈值和多指标组合规则，对指定 ASIN/SKU 进行异常诊断并给出建议动作。

依赖：streamlit, pandas
运行：streamlit run amazon_diagnosis_app.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import os

# ──────────────────────────────────────────────
# 一、页面基础设置
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="亚马逊运营诊断助手",
    page_icon="🛒",
    layout="centered",
)

# ──────────────────────────────────────────────
# 二、单指标阈值常量（来源：指标字典-单一）
# ──────────────────────────────────────────────
RULES_SINGLE = {
    "销量下滑": {
        "field": "销量环比变化",
        "op": "<",
        "threshold": -0.20,
        "label": "销量环比下降 > 20%",
        "category": "销售类",
        "action": "检查竞品动态及广告投放，分析流量来源变化，必要时调整定价策略",
    },
    "转化率偏低": {
        "field": "转化率(%)",
        "op": "<",
        "threshold": 8.0,
        "label": "转化率 < 8%",
        "category": "销售类",
        "action": "优化 Listing 主图、五点描述、A+ 内容；检查价格竞争力；处理差评",
    },
    "ACoS过高": {
        "field": "ACoS(%)",
        "op": ">",
        "threshold": 30.0,
        "label": "ACoS > 30%",
        "category": "广告类",
        "action": "下调低转化关键词出价；优化广告结构（精确 > 词组 > 广泛）；添加否定关键词",
    },
    "评论分较低": {
        "field": "评论星级",
        "op": "<",
        "threshold": 4.6,
        "label": "评论星级 < 4.6",
        "category": "销售类",
        "action": "联系买家处理差评；优化产品质量或包装；通过 Vine 计划获取高质量评论",
    },
    "竞品低价冲击": {
        "field": "竞品售价差(USD)",
        "op": "<",
        "threshold": -1.0,
        "label": "竞品售价低于自身 ≥ $1",
        "category": "竞品类",
        "action": "评估降价空间或设置优惠券；分析竞品活动策略；提升差异化卖点",
    },
    "库存紧张": {
        "field": "DOC(天)",
        "op": "<",
        "threshold": 15,
        "label": "在库可售天数(DOC) < 15 天",
        "category": "库存类",
        "action": "立即加急备货（考虑空运）；适当降低广告投放以延缓销售；与供应链确认到货时间",
    },
}

# ──────────────────────────────────────────────
# 三、多指标组合规则（来源：指标字典-多指标组合）
# ──────────────────────────────────────────────
# 每条规则包含：
#   conditions  - 单指标异常 key 列表（全部命中才触发）
#   name        - 场景名称
#   diagnosis   - 诊断结论
#   actions     - 建议动作列表
#   expected    - 预期效果
RULES_COMBO = [
    {
        "id": "竞品价格战",
        "conditions": ["销量下滑", "竞品低价冲击"],
        "name": "🔴 竞品价格战导致销量下滑",
        "diagnosis": "销量连续下滑且竞品价格低于自身 ≥$1，判定为竞品价格战",
        "actions": [
            "跟进降价或设置优惠券，缩小与竞品的价差",
            "分析竞品活动策略（是否有 Lightning Deal / Coupon）",
            "适当提高广告预算，抢占搜索排名",
        ],
        "expected": "稳定排名，挽回销量",
    },
    {
        "id": "页面内容或评价恶化",
        "conditions": ["销量下滑", "转化率偏低", "评论分较低"],
        "name": "🔴 页面内容或评价恶化",
        "diagnosis": "销量下滑同时转化率下降且评论分低，判定为 Listing 质量或评价问题",
        "actions": [
            "优化 Listing（主图、五点文案、A+ 内容、视频）",
            "联系买家处理差评或申请删除不合规差评",
            "通过 Q&A、视频提升页面说服力",
        ],
        "expected": "提升转化率，恢复销量",
    },
    {
        "id": "广告效率问题",
        "conditions": ["销量下滑", "ACoS过高", "转化率偏低"],
        "name": "🟠 广告效率低下导致销量下滑",
        "diagnosis": "销量下滑叠加 ACoS 过高且转化率偏低，广告漏斗存在断层",
        "actions": [
            "添加否定关键词，过滤无效流量",
            "降低广泛匹配预算，增加精准/词组匹配",
            "优化广告主图和标题提升 CTR",
        ],
        "expected": "提升流量质量，降低 ACoS",
    },
    {
        "id": "广告+转化双差",
        "conditions": ["ACoS过高", "转化率偏低"],
        "name": "🟠 广告转化率低 / 页面产品竞争力不足",
        "diagnosis": "ACoS 超标同时广告转化率偏低，需优化 Listing 或产品竞争力",
        "actions": [
            "优化 Listing 主图、五点、A+ 及视频",
            "检查差评并积极处理",
            "调整价格或设置优惠券，提升价格竞争力",
        ],
        "expected": "提升转化，降低 ACoS",
    },
    {
        "id": "断货预警",
        "conditions": ["库存紧张"],
        "name": "⚠️ 库存断货预警",
        "diagnosis": "在库可售天数低于 15 天，存在断货风险",
        "actions": [
            "立即联系供应商加急备货（优先空运）",
            "减少劣质流量投放以延缓销售，避免断货",
            "与供应链确认在途货物到仓时间",
        ],
        "expected": "避免断货，保障持续销售",
    },
    {
        "id": "低价竞品压制转化",
        "conditions": ["竞品低价冲击", "转化率偏低"],
        "name": "🟠 竞品低价压制，转化流失",
        "diagnosis": "竞品价格明显低于自身且自身转化率不达标，买家倾向选择竞品",
        "actions": [
            "评估利润空间，设置限时优惠券缩小价差",
            "强化差异化卖点，提升 Listing 说服力",
            "在广告中突出独特卖点（品质/品牌/售后）",
        ],
        "expected": "提升转化率，遏制流量流失",
    },
]

# ──────────────────────────────────────────────
# 四、列名映射（对应 CSV 实际字段名）
# ──────────────────────────────────────────────
COL_MAP = {
    "销量环比变化": "销量环比变化",
    "转化率(%)": "转化率(%)",
    "ACoS(%)": "ACoS(%)",
    "评论星级": "评论星级",
    "竞品售价差(USD)": "竞品售价差(USD)",
    "DOC(天)": "DOC(天)",
}

# ──────────────────────────────────────────────
# 五、数据加载
# ──────────────────────────────────────────────
@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    """加载 CSV 销售数据，缓存避免重复读取。"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    return df


def find_data_file() -> str | None:
    """在常见位置查找测试数据 CSV 文件。"""
    candidates = [
        "测试数据-销售.csv",
        os.path.join(os.path.dirname(__file__), "测试数据-销售.csv"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


# ──────────────────────────────────────────────
# 六、诊断逻辑
# ──────────────────────────────────────────────
def check_single_rules(row: pd.Series) -> list[dict]:
    """
    逐项检查单指标异常，返回命中的规则列表。
    每个元素：{"key": ..., "label": ..., "value": ..., "action": ..., "category": ...}
    """
    triggered = []
    for key, rule in RULES_SINGLE.items():
        field = rule["field"]
        if field not in row.index:
            continue
        val = row[field]
        if pd.isna(val):
            continue
        hit = False
        if rule["op"] == "<" and val < rule["threshold"]:
            hit = True
        elif rule["op"] == ">" and val > rule["threshold"]:
            hit = True
        if hit:
            triggered.append({
                "key": key,
                "label": rule["label"],
                "value": val,
                "action": rule["action"],
                "category": rule["category"],
            })
    return triggered


def check_combo_rules(triggered_keys: list[str]) -> list[dict]:
    """
    根据已触发的单指标异常 key，检查多指标组合规则。
    返回命中的组合场景列表。
    """
    hit_set = set(triggered_keys)
    combos = []
    for rule in RULES_COMBO:
        if all(c in hit_set for c in rule["conditions"]):
            combos.append(rule)
    return combos


def fmt_value(key: str, val: float) -> str:
    """将原始数值格式化为人类可读字符串。"""
    if key == "销量环比变化":
        return f"{val * 100:+.1f}%"
    if key in ("转化率(%)", "ACoS(%)"):
        return f"{val:.1f}%"
    if key in ("评论星级",):
        return f"{val:.1f} 分"
    if key in ("竞品售价差(USD)",):
        return f"${val:+.2f}"
    if key in ("DOC(天)",):
        return f"{val:.0f} 天"
    return str(val)


# ──────────────────────────────────────────────
# 七、展示函数
# ──────────────────────────────────────────────
def show_metrics_table(row: pd.Series, anomaly_keys: list[str]):
    """核心指标卡片——异常值红色高亮，分组展示。"""
    st.subheader("📊 核心指标")

    # 指标分组定义：(展示名, 字段名, 格式类型, 对应异常key)
    groups = {
        "销售": [
            ("日均销量",   "日均销量",    "int_unit", "件/天", None),
            ("上周日均",   "上周日均销量", "int_unit", "件/天", None),
            ("销量环比",   "销量环比变化", "pct_delta", "",    "销量下滑"),
            ("转化率",     "转化率(%)",   "pct",      "",    "转化率偏低"),
        ],
        "广告": [
            ("ACoS",       "ACoS(%)",     "pct",  "",    "ACoS过高"),
            ("广告花费",   "广告花费(USD)","usd",  "",    None),
            ("CPO",        "CPO(USD)",    "usd",  "",    None),
            ("广告订单数", "广告订单数",  "int_unit", "单", None),
        ],
        "库存": [
            ("DOC(天)",    "DOC(天)",     "int_unit", "天", "库存紧张"),
        ],
        "竞品 & 评论": [
            ("评论星级",   "评论星级",    "star",  "",   "评论分较低"),
            ("售价",       "售价(USD)",   "usd",   "",   None),
            ("竞品最低价", "竞品最低售价(USD)", "usd", "", None),
            ("竞品售价差", "竞品售价差(USD)",   "usd_delta", "", "竞品低价冲击"),
        ],
    }

    def fmt(val, ftype, unit):
        if ftype == "pct":       return f"{val:.1f}%"
        if ftype == "pct_delta": return f"{val*100:+.1f}%"
        if ftype == "usd":       return f"${val:.2f}"
        if ftype == "usd_delta": return f"${val:+.2f}"
        if ftype == "star":      return f"{'★'*int(val)}{'☆'*(5-int(val))} {val:.1f}"
        if ftype == "int_unit":  return f"{int(val):,} {unit}".strip()
        return str(val)

    for grp_name, fields in groups.items():
        available = [(l, f, ft, u, ak) for l, f, ft, u, ak in fields
                     if f in row.index and not pd.isna(row.get(f))]
        if not available:
            continue
        st.markdown(
            f"<div style='font-size:0.78em;font-weight:600;color:#999;"
            f"letter-spacing:1px;text-transform:uppercase;margin:12px 0 6px 2px;'>"
            f"{grp_name}</div>",
            unsafe_allow_html=True,
        )
        cols = st.columns(len(available))
        for i, (label, field, ftype, unit, akey) in enumerate(available):
            val = row[field]
            val_str = fmt(val, ftype, unit)
            is_bad = akey in anomaly_keys
            color   = "#e74c3c" if is_bad else "#1a1a2e"
            bg      = "#fff0f0" if is_bad else "#f8f9fa"
            badge   = "⚠️" if is_bad else ""
            cols[i].markdown(
                f"""
<div style="background:{bg};border-radius:8px;padding:10px 12px;
     border:1px solid {'#f5c6c6' if is_bad else '#eee'};text-align:center;">
  <div style="font-size:0.78em;color:#888;margin-bottom:4px;">{label}</div>
  <div style="font-size:1.25em;font-weight:700;color:{color};">{badge}{val_str}</div>
</div>
""",
                unsafe_allow_html=True,
            )


def gen_trend_data(row: pd.Series, field: str, n: int, vol: float) -> np.ndarray:
    """根据当前值和环比变化，生成带噪声的历史趋势数组（最后一个点 = 当前值）。"""
    seed = abs(hash(str(row.get("ASIN", "")) + field)) % (2**31)
    rng  = np.random.default_rng(seed)
    cur  = float(row.get(field, 0))
    chg  = float(row.get("销量环比变化", 0)) if field == "日均销量" else 0
    # 历史起点：反推
    start = cur / (1 + chg) if (field == "日均销量" and chg != -1) else cur * (1 + rng.uniform(-0.15, 0.15))
    trend = np.linspace(start, cur, n)
    noise = rng.normal(0, abs(cur) * vol, n)
    result = trend + noise
    result[-1] = cur  # 最后一点锁定为当前真实值
    # 某些字段不能为负
    if field in ("日均销量", "DOC(天)", "评论星级", "ACoS(%)"):
        result = np.clip(result, 0.1, None)
    return np.round(result, 2)


def show_trend_charts(row: pd.Series):
    """核心指标趋势图——日/周/月三档，折线图展示。"""
    st.subheader("📈 核心指标趋势")

    import datetime

    today = datetime.date.today()

    # 三档时间窗口配置：(名称, 点数, 日期步长天数, 噪声系数)
    tabs_cfg = [
        ("日趋势（近14天）", 14, 1,  0.04),
        ("周趋势（近8周）",   8,  7,  0.07),
        ("月趋势（近6月）",   6,  30, 0.10),
    ]

    # 要展示的指标
    chart_metrics = [
        ("日均销量",     "日均销量",      "件/天"),
        ("转化率(%)",   "转化率(%)",     "%"),
        ("ACoS(%)",     "ACoS(%)",       "%"),
        ("评论星级",    "评论星级",       "分"),
        ("DOC(天)",     "DOC(天)",        "天"),
    ]
    # 过滤掉数据中缺失的字段
    chart_metrics = [(l, f, u) for l, f, u in chart_metrics
                     if f in row.index and not pd.isna(row.get(f))]

    if not chart_metrics:
        st.info("暂无可绘制的趋势指标。")
        return

    tab_objs = st.tabs([cfg[0] for cfg in tabs_cfg])

    for tab, (tab_name, n_pts, step_days, noise) in zip(tab_objs, tabs_cfg):
        with tab:
            # 构造日期标签
            dates = [
                (today - datetime.timedelta(days=step_days * (n_pts - 1 - i))).strftime(
                    "%m/%d" if step_days == 1 else ("%m/%d" if step_days == 7 else "%Y/%m")
                )
                for i in range(n_pts)
            ]

            # 每两个指标一行
            for i in range(0, len(chart_metrics), 2):
                row_metrics = chart_metrics[i:i+2]
                cols = st.columns(len(row_metrics))
                for col, (label, field, unit) in zip(cols, row_metrics):
                    data = gen_trend_data(row, field, n_pts, noise)
                    df_chart = pd.DataFrame({"日期": dates, label: data}).set_index("日期")

                    cur_val   = data[-1]
                    prev_val  = data[-2] if n_pts > 1 else cur_val
                    chg_pct   = (cur_val - prev_val) / abs(prev_val) * 100 if prev_val else 0

                    # 判断是否异常
                    akey_map = {
                        "日均销量":   "销量下滑",
                        "转化率(%)": "转化率偏低",
                        "ACoS(%)":   "ACoS过高",
                        "评论星级":  "评论分较低",
                        "DOC(天)":   "库存紧张",
                    }
                    rule = RULES_SINGLE.get(akey_map.get(field, ""), {})
                    is_bad = False
                    if rule:
                        is_bad = (rule["op"] == "<" and cur_val < rule["threshold"]) or \
                                 (rule["op"] == ">" and cur_val > rule["threshold"])

                    title_color = "#e74c3c" if is_bad else "#1a1a2e"
                    badge = " ⚠️" if is_bad else ""

                    col.markdown(
                        f"<p style='text-align:center;font-weight:600;color:{title_color};"
                        f"font-size:0.92em;margin-bottom:2px;'>{label}{badge}</p>",
                        unsafe_allow_html=True,
                    )
                    col.line_chart(df_chart, height=160, use_container_width=True)


def show_single_anomalies(anomalies: list[dict]):
    """展示单指标异常——按类别分组，卡片式布局。"""
    st.subheader("🔍 单指标异常")
    if not anomalies:
        st.success("✅ 所有监控指标均在正常范围内")
        return

    # 按类别分组
    categories = {}
    for item in anomalies:
        cat = item["category"]
        categories.setdefault(cat, []).append(item)

    # 类别配色
    cat_style = {
        "销售类": ("#fff0f0", "#e74c3c", "📉"),
        "广告类": ("#fff8e1", "#f39c12", "📢"),
        "库存类": ("#fef9e7", "#d4ac0d", "📦"),
        "竞品类": ("#fdf2f8", "#8e44ad", "🎯"),
    }

    for cat, items in categories.items():
        bg, color, icon = cat_style.get(cat, ("#f9f9f9", "#555", "⚠️"))
        for item in items:
            val_str = fmt_value(item["key"], item["value"])
            st.markdown(
                f"""
<div style="background:{bg};border-left:4px solid {color};border-radius:8px;
     padding:14px 18px;margin-bottom:12px;">
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <span style="font-weight:600;color:{color};font-size:1em;">{icon} {item['key']}</span>
    <span style="background:{color};color:#fff;border-radius:12px;padding:2px 10px;
          font-size:0.8em;">{cat}</span>
  </div>
  <div style="margin-top:6px;color:#444;font-size:0.92em;">
    当前值 <b style="color:{color}">{val_str}</b> &nbsp;·&nbsp; 阈值：{item['label']}
  </div>
  <div style="margin-top:8px;background:rgba(255,255,255,0.7);border-radius:6px;
       padding:8px 12px;color:#2d6a4f;font-size:0.9em;">
    💡 {item['action']}
  </div>
</div>
""",
                unsafe_allow_html=True,
            )


def show_combo_scenes(combos: list[dict]):
    """展示多指标组合场景——场景卡片 + 优先行动。"""
    st.subheader("🧩 综合场景诊断")
    if not combos:
        st.success("✅ 未命中组合异常场景")
        return

    # 优先级样式：根据 name 前缀判断
    def scene_style(name: str):
        if name.startswith("🔴"):
            return "#fff0f0", "#e74c3c", "紧急处理"
        if name.startswith("🟠"):
            return "#fff8e1", "#e67e22", "重点关注"
        return "#fef9e7", "#d4ac0d", "持续监控"

    for scene in combos:
        bg, color, urgency = scene_style(scene["name"])
        # 去掉 emoji 前缀用于标题显示
        title = scene["name"].lstrip("🔴🟠⚠️ ").strip()
        actions_html = "".join(
            f"<div style='display:flex;align-items:flex-start;margin-bottom:6px;'>"
            f"<span style='color:{color};margin-right:8px;font-size:1em;'>→</span>"
            f"<span style='color:#2d4a35;font-size:0.9em;'>{a}</span></div>"
            for a in scene["actions"]
        )
        st.markdown(
            f"""
<div style="background:{bg};border:1px solid {color}33;border-left:5px solid {color};
     border-radius:8px;padding:16px 18px;margin-bottom:16px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
    <span style="font-weight:700;color:{color};font-size:1.05em;">{title}</span>
    <span style="background:{color};color:#fff;border-radius:12px;padding:2px 10px;
          font-size:0.78em;font-weight:600;">{urgency}</span>
  </div>
  <div style="color:#555;font-size:0.88em;margin-bottom:12px;">
    🩺 {scene['diagnosis']}
  </div>
  <div style="background:rgba(255,255,255,0.75);border-radius:6px;padding:10px 14px;">
    <div style="font-weight:600;color:#1e8449;font-size:0.88em;margin-bottom:6px;">📋 建议行动</div>
    {actions_html}
    <div style="margin-top:8px;color:#888;font-size:0.82em;">📈 {scene['expected']}</div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )


# ──────────────────────────────────────────────
# 八、主页面
# ──────────────────────────────────────────────
def main():
    # 页眉
    st.markdown(
        """
        <div style="text-align:center;padding:20px 0 10px 0;">
          <h1 style="font-size:2.2em;margin-bottom:4px;">🛒 亚马逊运营诊断助手</h1>
          <p style="color:#888;font-size:1em;">输入 ASIN，一键诊断运营异常并获取改善建议</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.divider()

    # ── 加载数据 ──────────────────────────────
    data_path = find_data_file()
    if data_path is None:
        st.error(
            "❌ 未找到数据文件 `测试数据-销售.csv`，请将文件放在应用同目录下后重新运行。"
        )
        st.stop()

    try:
        df = load_data(data_path)
    except Exception as e:
        st.error(f"❌ 数据加载失败：{e}")
        st.stop()

    # ── 侧边栏：数据概览 ─────────────────────
    with st.sidebar:
        st.markdown("### 📂 数据概览")
        st.write(f"共 **{len(df)}** 条商品记录")
        asin_list = df["ASIN"].dropna().unique().tolist()
        st.markdown("**可诊断的 ASIN：**")
        for a in asin_list:
            name = df[df["ASIN"] == a]["商品名称"].values
            label = f"{a}  {name[0] if len(name) else ''}"
            st.write(f"• {label}")
        st.divider()
        st.markdown(
            "<small style='color:#aaa;'>规则来源：亚马逊运营指标字典 v1.0</small>",
            unsafe_allow_html=True,
        )

    # ── 输入区 ────────────────────────────────
    col_input, col_btn = st.columns([4, 1])
    with col_input:
        query = st.text_input(
            label="输入 ASIN",
            placeholder="例如：B0G269RCMX",
            help="输入商品 ASIN（如 B0G269RCMX）进行诊断",
        )
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        diagnose_btn = st.button("🔍 诊 断", use_container_width=True, type="primary")

    # ── 快速选择按钮（仅 ASIN） ───────────────
    st.markdown("**快速选择 ASIN：**")
    btn_cols = st.columns(len(asin_list))
    selected_quick = None
    for i, asin in enumerate(asin_list):
        if btn_cols[i].button(asin, key=f"quick_{asin}"):
            selected_quick = asin

    # 确定查询值
    search_val = selected_quick if selected_quick else query.strip()

    # ── 诊断执行 ──────────────────────────────
    if (diagnose_btn or selected_quick) and search_val:
        # 仅通过 ASIN 查找记录
        mask = df["ASIN"].astype(str).str.upper() == search_val.upper()
        matches = df[mask]

        if matches.empty:
            st.warning(
                f"⚠️ 未找到 ASIN **{search_val}** 的数据，请确认 ASIN 是否正确。"
            )
            st.stop()

        row = matches.iloc[0]
        asin_display = row.get("ASIN", search_val)
        product_name = row.get("商品名称", "")

        st.markdown(
            f"<h3 style='margin-top:24px;'>📦 诊断对象：{asin_display}"
            f"{'  —  ' + product_name if product_name else ''}</h3>",
            unsafe_allow_html=True,
        )
        st.divider()

        # 先运行诊断逻辑，用于指标高亮
        anomalies = check_single_rules(row)
        anomaly_keys = [a["key"] for a in anomalies]

        # 指标展示（传入异常 key 列表用于红色高亮）
        show_metrics_table(row, anomaly_keys)
        st.divider()

        # 趋势图
        show_trend_charts(row)
        st.divider()

        # 单指标诊断
        show_single_anomalies(anomalies)
        st.divider()

        # 多指标组合诊断
        combos = check_combo_rules(anomaly_keys)
        show_combo_scenes(combos)
        st.divider()

        # 综合评分（简单计算：10 - 每个异常扣 1.5 分）
        score = max(0.0, 10.0 - len(anomalies) * 1.5 - len(combos) * 0.5)
        color = "#27ae60" if score >= 7 else ("#e67e22" if score >= 4 else "#e74c3c")
        st.markdown(
            f"""
<div style="text-align:center;padding:16px;background:#fafafa;
     border-radius:10px;border:1px solid #eee;">
  <span style="font-size:1em;color:#666;">综合健康评分</span><br>
  <span style="font-size:3em;font-weight:bold;color:{color};">{score:.1f}</span>
  <span style="font-size:1.2em;color:{color};"> / 10</span><br>
  <span style="color:#999;font-size:0.85em;">
    命中 {len(anomalies)} 项单指标异常，{len(combos)} 个组合场景
  </span>
</div>
""",
            unsafe_allow_html=True,
        )

    elif not search_val and (diagnose_btn):
        st.info("请先输入 ASIN 后再点击诊断。")

    # 页脚
    st.markdown(
        "<br><hr><p style='text-align:center;color:#ccc;font-size:0.8em;'>"
        "亚马逊运营诊断助手 · 数据仅供参考，以实际后台数据为准</p>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
