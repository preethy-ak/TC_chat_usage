import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import json
from datetime import datetime, timedelta
import os

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TC Chattr Usage Dashboard",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { padding-top: 1rem; }
    .kpi-card {
        background: white;
        border-radius: 10px;
        padding: 16px 20px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.08);
        text-align: center;
    }
    .kpi-value { font-size: 2rem; font-weight: 700; margin: 4px 0; }
    .kpi-label { font-size: 0.75rem; color: #888; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
    .kpi-delta { font-size: 0.8rem; margin-top: 2px; }
    [data-testid="stMetricValue"] { font-size: 2rem; }
    .stAlert { border-radius: 8px; }
    div[data-testid="metric-container"] {
        background: white;
        border: 1px solid #f0f2f8;
        border-radius: 10px;
        padding: 12px 18px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://graas.ai/wp-content/uploads/2022/06/graas-logo.svg", width=120)
    st.markdown("### 💬 Chattr Usage Dashboard")
    st.markdown("---")

    uploaded_file = st.file_uploader(
        "Upload Chattr CSV",
        type=["csv"],
        help="Upload the GRAAS_CHATTR_LOGS export CSV"
    )

    st.markdown("---")
    st.markdown("### ⚙️ Slack Settings")
    slack_token = st.text_input(
        "Slack Bot Token",
        type="password",
        value=os.environ.get("SLACK_BOT_TOKEN", ""),
        help="xoxb-... token from your Slack app"
    )
    slack_channel = st.text_input(
        "Slack Channel ID",
        value="C0AR6KRBUJC",
        help="Channel ID for #automation-jira-test"
    )
    auto_send = st.checkbox(
        "Auto-send report on upload",
        value=True,
        help="Automatically post to Slack when a new file is uploaded"
    )

    st.markdown("---")
    st.markdown("### 📅 Filters")

# ── Data processing ───────────────────────────────────────────────────────────
@st.cache_data
def process_data(file_bytes):
    df = pd.read_csv(file_bytes)
    df.columns = df.columns.str.strip()
    df["CREATED_AT"] = pd.to_datetime(df["CREATED_AT"])
    df["date"] = df["CREATED_AT"].dt.date
    df["MERCHANT_ID"] = df["MERCHANT_ID"].fillna("").astype(str)
    df["NICKNAME_ID"] = df["NICKNAME_ID"].fillna("").astype(str)
    df["seller_id"] = df["NICKNAME_ID"] + " | " + df["MERCHANT_ID"]
    return df

def compute_metrics(df):
    """Compute all summary metrics from raw dataframe."""
    # Conversation-level
    conv = df.groupby("CONVERSATION_ID").agg(
        has_seller=("ACTOR_TYPE", lambda x: (x == "seller").any()),
        has_chattr=("ACTOR_TYPE", lambda x: (x == "chattr").any()),
    ).reset_index()
    conv["tc_handled"] = conv["has_seller"] | conv["has_chattr"]

    total_conv = conv["CONVERSATION_ID"].nunique()
    tc_conv = conv["tc_handled"].sum()
    mp_conv = total_conv - tc_conv

    # Message-level
    total_replies = df["MESSAGE_ID"].nunique()
    seller_replies = df[df["ACTOR_TYPE"] == "seller"]["MESSAGE_ID"].nunique()
    chattr_replies = df[df["ACTOR_TYPE"] == "chattr"]["MESSAGE_ID"].nunique()
    tc_total_replies = seller_replies + chattr_replies

    return {
        "total_conversations": int(total_conv),
        "tc_conversations": int(tc_conv),
        "mp_conversations": int(mp_conv),
        "total_replies": int(total_replies),
        "seller_replies": int(seller_replies),
        "chattr_replies": int(chattr_replies),
        "tc_total_replies": int(tc_total_replies),
    }

def compute_daily(df):
    """Daily metrics grouped by date × seller."""
    records = []
    for (date, account, nickname, merchant), grp in df.groupby(
        ["date", "ACCOUNT_NUMBER", "NICKNAME_ID", "MERCHANT_ID"]
    ):
        conv_ids = grp["CONVERSATION_ID"].unique()
        tc_conv_ids = grp[grp["ACTOR_TYPE"].isin(["seller", "chattr"])]["CONVERSATION_ID"].unique()
        total_conv = len(conv_ids)
        tc_conv = len(tc_conv_ids)
        records.append({
            "date": date,
            "account": str(account)[:12] + "…",
            "nickname": nickname,
            "merchant": merchant,
            "seller_id": nickname + " | " + merchant,
            "total_conversations": total_conv,
            "tc_conversations": tc_conv,
            "mp_conversations": total_conv - tc_conv,
            "total_replies": grp["MESSAGE_ID"].nunique(),
            "seller_replies": grp[grp["ACTOR_TYPE"] == "seller"]["MESSAGE_ID"].nunique(),
            "chattr_replies": grp[grp["ACTOR_TYPE"] == "chattr"]["MESSAGE_ID"].nunique(),
        })
    return pd.DataFrame(records)

# ── Slack report ──────────────────────────────────────────────────────────────
def send_slack_report(metrics, daily_df, token, channel, date_from, date_to):
    if not token or not token.startswith("xoxb-"):
        return False, "Invalid or missing Slack bot token"

    # Top sellers
    seller_summary = (
        daily_df.groupby("seller_id")[["total_replies", "seller_replies", "chattr_replies", "mp_conversations"]]
        .sum()
        .sort_values("total_replies", ascending=False)
        .head(8)
        .reset_index()
    )

    rows = ""
    for _, r in seller_summary.iterrows():
        rows += f"\n• *{r['seller_id']}* — {int(r['total_replies'])} replies (Seller: {int(r['seller_replies'])} | TC AI: {int(r['chattr_replies'])} | MP: {int(r['mp_conversations'])})"

    tc_pct = round(metrics["tc_conversations"] / metrics["total_conversations"] * 100, 1) if metrics["total_conversations"] else 0
    mp_pct = round(metrics["mp_conversations"] / metrics["total_conversations"] * 100, 1) if metrics["total_conversations"] else 0

    message = f"""📊 *TC Chattr Usage Report*
📅 Period: `{date_from}` → `{date_to}`
_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} SGT_

━━━━━━━━━━━━━━━━━━━━━━
*Conversation Summary*
💬 Total Conversations: *{metrics['total_conversations']:,}*
✅ TC Handled: *{metrics['tc_conversations']:,}* ({tc_pct}%)
🏪 MP Direct: *{metrics['mp_conversations']:,}* ({mp_pct}%)

*Reply Breakdown*
📨 Total Replies: *{metrics['total_replies']:,}*
👤 Seller Replies: *{metrics['seller_replies']:,}*
🤖 TC AI Replies: *{metrics['chattr_replies']:,}*

━━━━━━━━━━━━━━━━━━━━━━
*Top Sellers by Reply Volume*{rows}"""

    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"channel": channel, "text": message, "mrkdwn": True}
    )
    data = resp.json()
    if data.get("ok"):
        return True, f"Sent to Slack ✓ (ts: {data.get('ts')})"
    return False, data.get("error", "Unknown error")

# ── Main app ──────────────────────────────────────────────────────────────────
st.title("💬 TC Chattr Usage Dashboard")

if uploaded_file is None:
    st.info("👈 Upload your Chattr CSV from the sidebar to get started.")
    st.markdown("""
    **Expected columns:** `ACCOUNT_NUMBER`, `CONVERSATION_ID`, `ACTOR_TYPE`, `CREATED_AT`,
    `EVENT_TYPE`, `MERCHANT_ID`, `MESSAGE_ID`, `NICKNAME_ID`

    **Metric definitions:**
    | Metric | Definition |
    |---|---|
    | TC Conversations | Conversations where seller or TC AI replied |
    | MP Conversations | Total conversations − TC conversations |
    | Seller Replies | Messages with `ACTOR_TYPE = seller` |
    | TC AI Replies | Messages with `ACTOR_TYPE = chattr` |
    """)
    st.stop()

# Process
df_raw = process_data(uploaded_file)

# ── Sidebar filters ───────────────────────────────────────────────────────────
with st.sidebar:
    min_date = df_raw["date"].min()
    max_date = df_raw["date"].max()

    date_from = st.date_input("From", value=min_date, min_value=min_date, max_value=max_date)
    date_to = st.date_input("To", value=max_date, min_value=min_date, max_value=max_date)

    all_sellers = sorted(df_raw["seller_id"].unique())
    selected_sellers = st.multiselect(
        "Seller / Store",
        options=all_sellers,
        default=[],
        placeholder="All sellers"
    )

    platforms = st.multiselect(
        "Platform",
        options=["lazada", "shopee"],
        default=[],
        placeholder="All platforms"
    )

# ── Filter ────────────────────────────────────────────────────────────────────
df = df_raw[(df_raw["date"] >= date_from) & (df_raw["date"] <= date_to)].copy()
if selected_sellers:
    df = df[df["seller_id"].isin(selected_sellers)]
if platforms:
    df = df[df["NICKNAME_ID"].str.startswith(tuple(platforms))]

if df.empty:
    st.warning("No data for the selected filters.")
    st.stop()

# ── Compute ───────────────────────────────────────────────────────────────────
metrics = compute_metrics(df)
daily_df = compute_daily(df)

# ── Auto-send Slack ───────────────────────────────────────────────────────────
if auto_send and slack_token and "last_sent_file" not in st.session_state:
    st.session_state["last_sent_file"] = uploaded_file.name
    ok, msg = send_slack_report(metrics, daily_df, slack_token, slack_channel, date_from, date_to)
    if ok:
        st.toast("📤 Report sent to Slack!", icon="✅")
    else:
        st.toast(f"Slack send failed: {msg}", icon="⚠️")

# ── KPI row ───────────────────────────────────────────────────────────────────
k = metrics
tc_pct = round(k["tc_conversations"] / k["total_conversations"] * 100, 1) if k["total_conversations"] else 0
mp_pct = round(k["mp_conversations"] / k["total_conversations"] * 100, 1) if k["total_conversations"] else 0

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("💬 Total Conversations", f"{k['total_conversations']:,}")
c2.metric("✅ TC Conversations", f"{k['tc_conversations']:,}", f"{tc_pct}% of total")
c3.metric("🏪 MP Conversations", f"{k['mp_conversations']:,}", f"{mp_pct}% of total")
c4.metric("📨 Total Replies", f"{k['total_replies']:,}")
c5.metric("👤 Seller Replies", f"{k['seller_replies']:,}")
c6.metric("🤖 TC AI Replies", f"{k['chattr_replies']:,}")

st.markdown("---")

# ── Charts row 1 ──────────────────────────────────────────────────────────────
col_left, col_right = st.columns([2, 1])

with col_left:
    metric_opt = st.selectbox(
        "Metric to chart",
        ["total_conversations", "total_replies", "seller_replies", "chattr_replies", "mp_conversations"],
        format_func=lambda x: {
            "total_conversations": "Total Conversations",
            "total_replies": "Total Replies",
            "seller_replies": "Seller Replies",
            "chattr_replies": "TC AI Replies",
            "mp_conversations": "MP Conversations"
        }[x]
    )
    daily_agg = daily_df.groupby("date")[metric_opt].sum().reset_index()
    fig_trend = px.bar(
        daily_agg, x="date", y=metric_opt,
        title=f"Daily {metric_opt.replace('_', ' ').title()}",
        color_discrete_sequence=["#4f6ef7"],
        labels={"date": "Date", metric_opt: metric_opt.replace("_", " ").title()}
    )
    fig_trend.update_layout(
        plot_bgcolor="white", paper_bgcolor="white",
        showlegend=False, height=320,
        margin=dict(t=40, b=20, l=0, r=0),
        xaxis=dict(gridcolor="#f0f2f8"),
        yaxis=dict(gridcolor="#f0f2f8")
    )
    fig_trend.update_traces(marker_line_width=0)
    st.plotly_chart(fig_trend, use_container_width=True)

with col_right:
    pie_data = pd.DataFrame({
        "Type": ["Seller Replies", "TC AI Replies", "MP Conversations"],
        "Count": [k["seller_replies"], k["chattr_replies"], k["mp_conversations"]]
    })
    fig_pie = px.pie(
        pie_data, names="Type", values="Count",
        title="Reply Type Breakdown",
        color_discrete_sequence=["#f59e0b", "#a855f7", "#ef4444"],
        hole=0.45
    )
    fig_pie.update_layout(
        height=320, margin=dict(t=40, b=0, l=0, r=0),
        paper_bgcolor="white",
        legend=dict(orientation="h", y=-0.1, font_size=11)
    )
    st.plotly_chart(fig_pie, use_container_width=True)

# ── Charts row 2 ──────────────────────────────────────────────────────────────
col_a, col_b = st.columns(2)

with col_a:
    seller_agg = (
        daily_df.groupby("seller_id")[["seller_replies", "chattr_replies", "mp_conversations"]]
        .sum()
        .sort_values("seller_replies", ascending=False)
        .head(12)
        .reset_index()
    )
    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(name="Seller Replies", x=seller_agg["seller_id"], y=seller_agg["seller_replies"], marker_color="#f59e0b"))
    fig_bar.add_trace(go.Bar(name="TC AI Replies", x=seller_agg["seller_id"], y=seller_agg["chattr_replies"], marker_color="#a855f7"))
    fig_bar.add_trace(go.Bar(name="MP Conv.", x=seller_agg["seller_id"], y=seller_agg["mp_conversations"], marker_color="#ef4444"))
    fig_bar.update_layout(
        barmode="stack", title="Top Sellers by Reply Volume",
        height=340, plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(t=40, b=80, l=0, r=0),
        xaxis=dict(tickangle=-35, tickfont_size=10, gridcolor="#f0f2f8"),
        yaxis=dict(gridcolor="#f0f2f8"),
        legend=dict(orientation="h", y=-0.35, font_size=11)
    )
    st.plotly_chart(fig_bar, use_container_width=True)

with col_b:
    # Daily stacked by actor type
    daily_stack = daily_df.groupby("date")[["seller_replies", "chattr_replies", "mp_conversations"]].sum().reset_index()
    fig_stack = go.Figure()
    fig_stack.add_trace(go.Bar(name="Seller", x=daily_stack["date"], y=daily_stack["seller_replies"], marker_color="#f59e0b"))
    fig_stack.add_trace(go.Bar(name="TC AI", x=daily_stack["date"], y=daily_stack["chattr_replies"], marker_color="#a855f7"))
    fig_stack.add_trace(go.Bar(name="MP Conv.", x=daily_stack["date"], y=daily_stack["mp_conversations"], marker_color="#ef4444"))
    fig_stack.update_layout(
        barmode="stack", title="Daily Reply Mix",
        height=340, plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(t=40, b=40, l=0, r=0),
        xaxis=dict(tickangle=-35, tickfont_size=9, gridcolor="#f0f2f8"),
        yaxis=dict(gridcolor="#f0f2f8"),
        legend=dict(orientation="h", y=-0.25, font_size=11)
    )
    st.plotly_chart(fig_stack, use_container_width=True)

# ── Heatmap — activity by day of week × hour ──────────────────────────────────
st.markdown("### 🔥 Activity Heatmap (Day × Hour)")
df["hour"] = df["CREATED_AT"].dt.hour
df["dow"] = df["CREATED_AT"].dt.day_name()
dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
heat = df.groupby(["dow", "hour"]).size().reset_index(name="count")
heat_pivot = heat.pivot(index="dow", columns="hour", values="count").reindex(dow_order).fillna(0)
fig_heat = px.imshow(
    heat_pivot,
    labels=dict(x="Hour of Day", y="Day of Week", color="Messages"),
    color_continuous_scale="Blues",
    aspect="auto",
    title=""
)
fig_heat.update_layout(
    height=250, margin=dict(t=10, b=30, l=0, r=0),
    paper_bgcolor="white", plot_bgcolor="white"
)
st.plotly_chart(fig_heat, use_container_width=True)

# ── Detail table ──────────────────────────────────────────────────────────────
st.markdown("### 📋 Daily Detail Table")
display_df = daily_df.sort_values(["date", "total_conversations"], ascending=[False, False]).reset_index(drop=True)
display_df.columns = [c.replace("_", " ").title() for c in display_df.columns]
st.dataframe(
    display_df,
    use_container_width=True,
    height=350,
    hide_index=True
)

# ── Download ──────────────────────────────────────────────────────────────────
csv_out = daily_df.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Download summary CSV", csv_out, "chattr_summary.csv", "text/csv")

# ── Manual Slack send ─────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📤 Send Report to Slack")
col_s1, col_s2 = st.columns([3, 1])
with col_s1:
    st.caption(f"Will post to channel `{slack_channel}` (#automation-jira-test)")
with col_s2:
    if st.button("Send Now 🚀", type="primary", use_container_width=True):
        if not slack_token:
            st.error("Add your Slack Bot Token in the sidebar first.")
        else:
            with st.spinner("Sending…"):
                ok, msg = send_slack_report(metrics, daily_df, slack_token, slack_channel, date_from, date_to)
            if ok:
                st.success(f"✅ Report sent to #automation-jira-test!")
            else:
                st.error(f"Failed: {msg}")
