import streamlit as st
import pandas as pd
import altair as alt
import requests
from datetime import datetime
import os

st.set_page_config(
    page_title="TC Chattr Usage Dashboard",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    div[data-testid="metric-container"] {
        background: white;
        border: 1px solid #eef0f8;
        border-radius: 10px;
        padding: 12px 18px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 💬 Chattr Dashboard")
    st.markdown("---")
    uploaded_file = st.file_uploader("Upload Chattr CSV", type=["csv"])
    st.markdown("---")
    st.markdown("### ⚙️ Slack Settings")
    slack_token = st.text_input(
        "Slack Bot Token", type="password",
        value=os.environ.get("SLACK_BOT_TOKEN", ""),
        help="xoxb-... token from your Slack app"
    )
    slack_channel = st.text_input("Slack Channel ID", value="C0AR6KRBUJC",
                                   help="#automation-jira-test")
    auto_send = st.checkbox("Auto-send report on upload", value=True)
    st.markdown("---")
    st.markdown("### 📅 Filters")

# ── Data helpers ──────────────────────────────────────────────────────────────
@st.cache_data
def process_data(file_bytes):
    df = pd.read_csv(file_bytes)
    df.columns = df.columns.str.strip()
    df["CREATED_AT"] = pd.to_datetime(df["CREATED_AT"])
    df["date"] = df["CREATED_AT"].dt.date
    df["MERCHANT_ID"] = df["MERCHANT_ID"].fillna("").astype(str)
    df["NICKNAME_ID"] = df["NICKNAME_ID"].fillna("").astype(str)
    df["seller_id"] = df["NICKNAME_ID"] + " | " + df["MERCHANT_ID"]
    df["hour"] = df["CREATED_AT"].dt.hour
    df["dow"] = df["CREATED_AT"].dt.day_name()
    return df

def compute_metrics(df):
    conv = df.groupby("CONVERSATION_ID").agg(
        has_seller=("ACTOR_TYPE", lambda x: (x == "seller").any()),
        has_chattr=("ACTOR_TYPE", lambda x: (x == "chattr").any()),
    ).reset_index()
    conv["tc_handled"] = conv["has_seller"] | conv["has_chattr"]
    total_conv  = conv["CONVERSATION_ID"].nunique()
    tc_conv     = int(conv["tc_handled"].sum())
    return {
        "total_conversations": int(total_conv),
        "tc_conversations":    tc_conv,
        "mp_conversations":    int(total_conv - tc_conv),
        "total_replies":       int(df["MESSAGE_ID"].nunique()),
        "seller_replies":      int(df[df["ACTOR_TYPE"] == "seller"]["MESSAGE_ID"].nunique()),
        "chattr_replies":      int(df[df["ACTOR_TYPE"] == "chattr"]["MESSAGE_ID"].nunique()),
    }

def compute_daily(df):
    records = []
    for (date, acct, nick, merch), grp in df.groupby(
        ["date", "ACCOUNT_NUMBER", "NICKNAME_ID", "MERCHANT_ID"]
    ):
        total_conv = grp["CONVERSATION_ID"].nunique()
        tc_conv    = grp[grp["ACTOR_TYPE"].isin(["seller","chattr"])]["CONVERSATION_ID"].nunique()
        records.append({
            "date":               str(date),
            "account":            str(acct)[:12] + "…",
            "nickname":           nick,
            "merchant":           merch,
            "seller_id":          nick + " | " + merch,
            "total_conversations": total_conv,
            "tc_conversations":   tc_conv,
            "mp_conversations":   total_conv - tc_conv,
            "total_replies":      grp["MESSAGE_ID"].nunique(),
            "seller_replies":     grp[grp["ACTOR_TYPE"] == "seller"]["MESSAGE_ID"].nunique(),
            "chattr_replies":     grp[grp["ACTOR_TYPE"] == "chattr"]["MESSAGE_ID"].nunique(),
        })
    return pd.DataFrame(records)

# ── Slack ─────────────────────────────────────────────────────────────────────
def send_slack_report(metrics, daily_df, token, channel, date_from, date_to):
    if not token or not token.startswith("xoxb-"):
        return False, "Invalid or missing Slack bot token"
    seller_summary = (
        daily_df.groupby("seller_id")[["total_replies","seller_replies","chattr_replies","mp_conversations"]]
        .sum().sort_values("total_replies", ascending=False).head(8).reset_index()
    )
    rows = ""
    for _, r in seller_summary.iterrows():
        rows += f"\n• *{r['seller_id']}* — {int(r['total_replies'])} replies (Seller: {int(r['seller_replies'])} | TC AI: {int(r['chattr_replies'])} | MP: {int(r['mp_conversations'])})"
    k = metrics
    tc_pct = round(k["tc_conversations"] / k["total_conversations"] * 100, 1) if k["total_conversations"] else 0
    mp_pct = round(k["mp_conversations"] / k["total_conversations"] * 100, 1) if k["total_conversations"] else 0
    message = f"""📊 *TC Chattr Usage Report*
📅 Period: `{date_from}` → `{date_to}`
_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} SGT_

━━━━━━━━━━━━━━━━━━━━━━
*Conversation Summary*
💬 Total Conversations: *{k['total_conversations']:,}*
✅ TC Handled: *{k['tc_conversations']:,}* ({tc_pct}%)
🏪 MP Direct: *{k['mp_conversations']:,}* ({mp_pct}%)

*Reply Breakdown*
📨 Total Replies: *{k['total_replies']:,}*
👤 Seller Replies: *{k['seller_replies']:,}*
🤖 TC AI Replies: *{k['chattr_replies']:,}*

━━━━━━━━━━━━━━━━━━━━━━
*Top Sellers by Reply Volume*{rows}"""
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"channel": channel, "text": message, "mrkdwn": True}
    )
    data = resp.json()
    if data.get("ok"):
        return True, f"Sent ✓"
    return False, data.get("error", "Unknown error")

# ── Landing ───────────────────────────────────────────────────────────────────
st.title("💬 TC Chattr Usage Dashboard")

if uploaded_file is None:
    st.info("👈 Upload your Chattr CSV from the sidebar to get started.")
    st.markdown("""
| Metric | Definition |
|---|---|
| TC Conversations | Conversations where seller or TC AI replied |
| MP Conversations | Total conversations − TC conversations |
| Seller Replies | `ACTOR_TYPE = seller` messages |
| TC AI Replies | `ACTOR_TYPE = chattr` messages |
""")
    st.stop()

# ── Load & filter ─────────────────────────────────────────────────────────────
df_raw = process_data(uploaded_file)

with st.sidebar:
    min_date, max_date = df_raw["date"].min(), df_raw["date"].max()
    date_from = st.date_input("From", value=min_date, min_value=min_date, max_value=max_date)
    date_to   = st.date_input("To",   value=max_date, min_value=min_date, max_value=max_date)
    all_sellers = sorted(df_raw["seller_id"].unique())
    selected_sellers = st.multiselect("Seller / Store", options=all_sellers, placeholder="All sellers")
    platforms = st.multiselect("Platform", options=["lazada","shopee"], placeholder="All platforms")

df = df_raw[(df_raw["date"] >= date_from) & (df_raw["date"] <= date_to)].copy()
if selected_sellers:
    df = df[df["seller_id"].isin(selected_sellers)]
if platforms:
    df = df[df["NICKNAME_ID"].str.startswith(tuple(platforms))]
if df.empty:
    st.warning("No data for the selected filters.")
    st.stop()

metrics  = compute_metrics(df)
daily_df = compute_daily(df)

# ── Auto Slack ────────────────────────────────────────────────────────────────
if auto_send and slack_token and "last_sent_file" not in st.session_state:
    st.session_state["last_sent_file"] = uploaded_file.name
    ok, msg = send_slack_report(metrics, daily_df, slack_token, slack_channel, date_from, date_to)
    st.toast("📤 Report sent to Slack!" if ok else f"Slack failed: {msg}", icon="✅" if ok else "⚠️")

# ── KPIs ──────────────────────────────────────────────────────────────────────
k = metrics
tc_pct = round(k["tc_conversations"] / k["total_conversations"] * 100, 1) if k["total_conversations"] else 0
mp_pct = round(k["mp_conversations"] / k["total_conversations"] * 100, 1) if k["total_conversations"] else 0

c1,c2,c3,c4,c5,c6 = st.columns(6)
c1.metric("💬 Total Conversations", f"{k['total_conversations']:,}")
c2.metric("✅ TC Conversations",    f"{k['tc_conversations']:,}",  f"{tc_pct}% of total")
c3.metric("🏪 MP Conversations",   f"{k['mp_conversations']:,}",  f"{mp_pct}% of total")
c4.metric("📨 Total Replies",      f"{k['total_replies']:,}")
c5.metric("👤 Seller Replies",     f"{k['seller_replies']:,}")
c6.metric("🤖 TC AI Replies",      f"{k['chattr_replies']:,}")

st.markdown("---")

# ── Daily trend ───────────────────────────────────────────────────────────────
col_l, col_r = st.columns([2, 1])

with col_l:
    metric_opt = st.selectbox("Metric to chart", [
        "total_conversations","total_replies","seller_replies","chattr_replies","mp_conversations"
    ], format_func=lambda x: x.replace("_"," ").title())

    daily_agg = daily_df.groupby("date")[metric_opt].sum().reset_index()
    daily_agg["date"] = pd.to_datetime(daily_agg["date"])

    trend = (
        alt.Chart(daily_agg)
        .mark_bar(color="#4f6ef7", cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("date:T", title="Date", axis=alt.Axis(labelAngle=-35)),
            y=alt.Y(f"{metric_opt}:Q", title=metric_opt.replace("_"," ").title()),
            tooltip=["date:T", f"{metric_opt}:Q"]
        )
        .properties(title=f"Daily {metric_opt.replace('_',' ').title()}", height=300)
    )
    st.altair_chart(trend, use_container_width=True)

with col_r:
    pie_data = pd.DataFrame({
        "type":  ["Seller Replies", "TC AI Replies", "MP Conversations"],
        "count": [k["seller_replies"], k["chattr_replies"], k["mp_conversations"]]
    })
    pie = (
        alt.Chart(pie_data)
        .mark_arc(innerRadius=60)
        .encode(
            theta=alt.Theta("count:Q"),
            color=alt.Color("type:N", scale=alt.Scale(
                domain=["Seller Replies","TC AI Replies","MP Conversations"],
                range=["#f59e0b","#a855f7","#ef4444"]
            )),
            tooltip=["type:N","count:Q"]
        )
        .properties(title="Reply Type Breakdown", height=300)
    )
    st.altair_chart(pie, use_container_width=True)

# ── Seller stacked bar + Daily reply mix ──────────────────────────────────────
col_a, col_b = st.columns(2)

with col_a:
    seller_agg = (
        daily_df.groupby("seller_id")[["seller_replies","chattr_replies","mp_conversations"]]
        .sum().sort_values("seller_replies", ascending=False).head(12).reset_index()
    )
    seller_long = seller_agg.melt(id_vars="seller_id", var_name="type", value_name="count")
    seller_long["type"] = seller_long["type"].map({
        "seller_replies":"Seller","chattr_replies":"TC AI","mp_conversations":"MP"
    })
    bar = (
        alt.Chart(seller_long)
        .mark_bar()
        .encode(
            x=alt.X("seller_id:N", title="Seller", sort="-y", axis=alt.Axis(labelAngle=-35, labelLimit=100)),
            y=alt.Y("count:Q", title="Count"),
            color=alt.Color("type:N", scale=alt.Scale(
                domain=["Seller","TC AI","MP"], range=["#f59e0b","#a855f7","#ef4444"]
            )),
            tooltip=["seller_id:N","type:N","count:Q"]
        )
        .properties(title="Top Sellers by Reply Volume", height=320)
    )
    st.altair_chart(bar, use_container_width=True)

with col_b:
    stack_agg = daily_df.groupby("date")[["seller_replies","chattr_replies","mp_conversations"]].sum().reset_index()
    stack_agg["date"] = pd.to_datetime(stack_agg["date"])
    stack_long = stack_agg.melt(id_vars="date", var_name="type", value_name="count")
    stack_long["type"] = stack_long["type"].map({
        "seller_replies":"Seller","chattr_replies":"TC AI","mp_conversations":"MP"
    })
    stack = (
        alt.Chart(stack_long)
        .mark_bar()
        .encode(
            x=alt.X("date:T", title="Date", axis=alt.Axis(labelAngle=-35)),
            y=alt.Y("count:Q", title="Count"),
            color=alt.Color("type:N", scale=alt.Scale(
                domain=["Seller","TC AI","MP"], range=["#f59e0b","#a855f7","#ef4444"]
            )),
            tooltip=["date:T","type:N","count:Q"]
        )
        .properties(title="Daily Reply Mix", height=320)
    )
    st.altair_chart(stack, use_container_width=True)

# ── Heatmap ───────────────────────────────────────────────────────────────────
st.markdown("### 🔥 Activity Heatmap — Day × Hour")
dow_order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
heat_data = df.groupby(["dow","hour"]).size().reset_index(name="count")
heat = (
    alt.Chart(heat_data)
    .mark_rect()
    .encode(
        x=alt.X("hour:O", title="Hour of Day"),
        y=alt.Y("dow:O",  title="Day", sort=dow_order),
        color=alt.Color("count:Q", scale=alt.Scale(scheme="blues")),
        tooltip=["dow:N","hour:O","count:Q"]
    )
    .properties(height=220)
)
st.altair_chart(heat, use_container_width=True)

# ── Detail table ──────────────────────────────────────────────────────────────
st.markdown("### 📋 Daily Detail Table")
display_df = daily_df.sort_values(["date","total_conversations"], ascending=[False,False]).reset_index(drop=True)
display_df.columns = [c.replace("_"," ").title() for c in display_df.columns]
st.dataframe(display_df, use_container_width=True, height=340, hide_index=True)

csv_out = daily_df.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Download summary CSV", csv_out, "chattr_summary.csv", "text/csv")

# ── Manual Slack ──────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📤 Send Report to Slack")
c1, c2 = st.columns([3,1])
with c1:
    st.caption(f"Posts to `{slack_channel}` (#automation-jira-test)")
with c2:
    if st.button("Send Now 🚀", type="primary", use_container_width=True):
        if not slack_token:
            st.error("Add Slack Bot Token in the sidebar.")
        else:
            with st.spinner("Sending…"):
                ok, msg = send_slack_report(metrics, daily_df, slack_token, slack_channel, date_from, date_to)
            st.success("✅ Sent to #automation-jira-test!") if ok else st.error(f"Failed: {msg}")
