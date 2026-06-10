import streamlit as st
import pandas as pd
import altair as alt
import requests
from datetime import datetime
import os
import io

st.set_page_config(
    page_title="TC Chat Usage Dashboard",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    div[data-testid="metric-container"] {
        border-radius: 10px; padding: 14px 18px;
        border: 1px solid rgba(128,128,128,0.2);
        box-shadow: 0 1px 4px rgba(0,0,0,0.07);
    }
    .section-title {
        font-size: 1rem; font-weight: 700;
        margin: 1.2rem 0 0.4rem;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 💬 TC Usage Dashboard")
    st.markdown("---")
    uploaded = st.file_uploader(
        "Upload TC Usage CSV",
        type=["csv"],
        help="CSV with columns: MERCHANT_ID, DATE, BUYER_MESSAGE_COUNT, MP_REPLY_COUNT, TC_REPLY_COUNT, TOTAL_SELLER_REPLY_COUNT, TC_REPLY_PCT"
    )
    st.markdown("---")
    st.markdown("### ⚙️ Slack")
    slack_token   = st.text_input("Bot Token", type="password",
                                   value=os.environ.get("SLACK_BOT_TOKEN", ""))
    slack_channel = st.text_input("Channel ID", value="C0AR6KRBUJC",
                                   help="#automation-jira-test")
    auto_send     = st.checkbox("Auto-send on upload", value=True)

# ─────────────────────────────────────────────────────────────────────────────
# LANDING
# ─────────────────────────────────────────────────────────────────────────────
st.title("💬 TC Chat Usage Dashboard")

if not uploaded:
    st.info("👈 Upload your TC Usage CSV from the sidebar.")
    st.markdown("""
**Expected columns:**

| Column | Description |
|---|---|
| `MERCHANT_ID` | Store / merchant code |
| `DATE` | Date (YYYY-MM-DD) |
| `BUYER_MESSAGE_COUNT` | Inbound buyer messages |
| `MP_REPLY_COUNT` | Replies sent directly from marketplace |
| `TC_REPLY_COUNT` | Replies sent via TC (The Chattr) |
| `TOTAL_SELLER_REPLY_COUNT` | Total seller replies (TC + MP) |
| `TC_REPLY_PCT` | TC reply % |
""")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# LOAD
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data
def load(file_bytes):
    df = pd.read_csv(io.BytesIO(file_bytes))
    df.columns = df.columns.str.strip().str.upper()

    # Only these are truly required
    required = {"MERCHANT_ID","DATE","BUYER_MESSAGE_COUNT","MP_REPLY_COUNT","TC_REPLY_COUNT"}
    missing = required - set(df.columns)
    if missing:
        st.error(f"Missing columns: {missing}. Found: {list(df.columns)}")
        st.stop()

    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
    df["DATE_ONLY"] = df["DATE"].dt.date

    for c in ["BUYER_MESSAGE_COUNT","MP_REPLY_COUNT","TC_REPLY_COUNT"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)

    # Compute TOTAL_SELLER_REPLY_COUNT if not present
    if "TOTAL_SELLER_REPLY_COUNT" not in df.columns:
        df["TOTAL_SELLER_REPLY_COUNT"] = df["TC_REPLY_COUNT"] + df["MP_REPLY_COUNT"]
    else:
        df["TOTAL_SELLER_REPLY_COUNT"] = pd.to_numeric(df["TOTAL_SELLER_REPLY_COUNT"], errors="coerce").fillna(0).astype(int)

    # Compute TC_REPLY_PCT if not present
    if "TC_REPLY_PCT" not in df.columns:
        df["TC_REPLY_PCT"] = (df["TC_REPLY_COUNT"] / df["TOTAL_SELLER_REPLY_COUNT"].replace(0,1) * 100).round(1)
    else:
        df["TC_REPLY_PCT"] = pd.to_numeric(df["TC_REPLY_PCT"], errors="coerce").fillna(0).round(1)

    # CHANNEL — use column if present, else derive from NICKNAME_ID, else mark Unknown
    if "CHANNEL" not in df.columns:
        if "NICKNAME_ID" in df.columns:
            df["CHANNEL"] = df["NICKNAME_ID"].astype(str).str.extract(r"^(\w+)-")[0].str.capitalize()
        else:
            df["CHANNEL"] = "Unknown"

    df["CHANNEL"] = df["CHANNEL"].astype(str).str.strip()
    return df

df_raw = load(uploaded.read())

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR FILTERS
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("---")
    st.markdown("### 📅 Date Range")
    min_d = df_raw["DATE_ONLY"].min()
    max_d = df_raw["DATE_ONLY"].max()
    date_from = st.date_input("From", value=min_d, min_value=min_d, max_value=max_d)
    date_to   = st.date_input("To",   value=max_d, min_value=min_d, max_value=max_d)

    st.markdown("### 📡 Channel")
    all_channels = sorted(df_raw["CHANNEL"].unique())
    sel_channels = st.multiselect("Channel", all_channels,
                                   placeholder="All channels",
                                   help="Filter by Lazada, Shopee, TikTok etc.")

    st.markdown("### 🏪 Merchant")
    # Merchant list updates based on channel selection
    merch_pool = df_raw[df_raw["CHANNEL"].isin(sel_channels)] if sel_channels else df_raw
    merchants = sorted(merch_pool["MERCHANT_ID"].unique())
    sel_merchants = st.multiselect("Merchant ID", merchants, placeholder="All merchants")

# ─────────────────────────────────────────────────────────────────────────────
# FILTER
# ─────────────────────────────────────────────────────────────────────────────
df = df_raw[(df_raw["DATE_ONLY"] >= date_from) & (df_raw["DATE_ONLY"] <= date_to)].copy()
if sel_channels:
    df = df[df["CHANNEL"].isin(sel_channels)]
if sel_merchants:
    df = df[df["MERCHANT_ID"].isin(sel_merchants)]

if df.empty:
    st.warning("No data for selected filters.")
    st.stop()

# Active filter banner
parts = [f"📅 {date_from} → {date_to}"]
if sel_channels:  parts.append(f"Channel: {', '.join(sel_channels)}")
if sel_merchants: parts.append(f"Merchants: {', '.join(sel_merchants)}")
st.info("  |  ".join(parts))

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY METRICS
# ─────────────────────────────────────────────────────────────────────────────
total_buyer   = int(df["BUYER_MESSAGE_COUNT"].sum())
total_mp      = int(df["MP_REPLY_COUNT"].sum())
total_tc      = int(df["TC_REPLY_COUNT"].sum())
total_replies = int(df["TOTAL_SELLER_REPLY_COUNT"].sum())
tc_pct        = round(total_tc / total_replies * 100, 1) if total_replies else 0
mp_pct        = round(total_mp / total_replies * 100, 1) if total_replies else 0
reply_rate    = round(total_replies / total_buyer * 100, 1) if total_buyer else 0

c1,c2,c3,c4,c5,c6 = st.columns(6)
c1.metric("📨 Buyer Messages",    f"{total_buyer:,}")
c2.metric("📤 Total Replies",     f"{total_replies:,}", f"{reply_rate}% reply rate")
c3.metric("✅ TC Replies",        f"{total_tc:,}",      f"{tc_pct}% of replies")
c4.metric("🏪 MP Replies",        f"{total_mp:,}",      f"{mp_pct}% of replies")
c5.metric("📊 TC Reply %",        f"{tc_pct}%")
c6.metric("📅 Days",              f"{df['DATE_ONLY'].nunique()}")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# TC ADOPTION TREND  — monthly MoM view
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">📈 TC Adoption Trend — Month on Month</div>', unsafe_allow_html=True)

# Always use full unfiltered data for the MoM trend (so Feb-Jun always visible)
monthly_raw = df_raw.copy()
monthly_raw["MONTH"] = pd.to_datetime(monthly_raw["DATE_ONLY"]).dt.to_period("M")
monthly_agg = monthly_raw.groupby("MONTH").agg(
    tc=("TC_REPLY_COUNT","sum"),
    total=("TOTAL_SELLER_REPLY_COUNT","sum")
).reset_index()
monthly_agg["tc_pct"] = (monthly_agg["tc"] / monthly_agg["total"].replace(0,1) * 100).round(1)
monthly_agg["month_label"] = monthly_agg["MONTH"].dt.strftime("%b %Y")
monthly_agg["MONTH_DT"] = monthly_agg["MONTH"].dt.to_timestamp()

# Per-merchant monthly table
merch_monthly = monthly_raw.groupby(["MERCHANT_ID","MONTH"]).agg(
    tc=("TC_REPLY_COUNT","sum"),
    total=("TOTAL_SELLER_REPLY_COUNT","sum")
).reset_index()
merch_monthly["tc_pct"] = (merch_monthly["tc"] / merch_monthly["total"].replace(0,1) * 100).round(1)
merch_monthly["month_label"] = merch_monthly["MONTH"].dt.strftime("%b")

# Pivot to wide format for the table
pivot = merch_monthly.pivot_table(
    index="MERCHANT_ID", columns="month_label", values="tc_pct", aggfunc="mean"
).round(1).reset_index()
# Sort months correctly
month_order = ["Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec","Jan"]
present_months = [m for m in month_order if m in pivot.columns]
pivot = pivot[["MERCHANT_ID"] + present_months].sort_values(
    present_months[-1] if present_months else "MERCHANT_ID", ascending=False
)

# Latest vs prev month KPIs
if len(monthly_agg) >= 2:
    latest_pct = monthly_agg.iloc[-1]["tc_pct"]
    prev_pct   = monthly_agg.iloc[-2]["tc_pct"]
    latest_label = monthly_agg.iloc[-1]["month_label"]
    prev_label   = monthly_agg.iloc[-2]["month_label"]
else:
    latest_pct = monthly_agg.iloc[-1]["tc_pct"] if len(monthly_agg) else 0
    prev_pct = 0; latest_label = "Latest"; prev_label = "Prev"

ka, kb, kc = st.columns([1,1,4])
ka.metric(f"TC Adoption ({latest_label})", f"{latest_pct}%",
          f"+{round(latest_pct - prev_pct,1)}% vs {prev_label}")
kb.metric(f"TC Adoption ({prev_label})",   f"{prev_pct}%")

with kc:
    # Annotated line chart
    base = alt.Chart(monthly_agg).encode(
        x=alt.X("MONTH_DT:T", title="Month",
                axis=alt.Axis(format="%b %Y", labelAngle=0, labelColor="#ccc", titleColor="#ccc")),
        y=alt.Y("tc_pct:Q", title="TC Adoption %",
                axis=alt.Axis(labelColor="#ccc", titleColor="#ccc"))
    )
    line   = base.mark_line(color="#f97316", strokeWidth=3)
    points = base.mark_point(color="#f97316", size=100, filled=True)
    labels = base.mark_text(dy=-14, color="#f97316", fontWeight="bold", fontSize=13).encode(
        text=alt.Text("tc_pct:Q", format=".1f")
    )
    st.altair_chart(
        (line + points + labels).properties(height=260, background="transparent"),
        use_container_width=True
    )

# Seller Adoption table
st.markdown("**Seller Adoption by Month (%)**")
def fmt(v):
    if pd.isna(v): return "—"
    return f"{v:.1f}%"
styled = pivot.copy()
for m in present_months:
    styled[m] = styled[m].apply(fmt)
styled = styled.rename(columns={"MERCHANT_ID":"Seller"})
st.dataframe(styled, use_container_width=True, hide_index=True)

st.caption("🎯 Target: ≥50% TC adoption per seller by Q3 2026")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# ROW 1 — Daily trend + Breakdown donut
# ─────────────────────────────────────────────────────────────────────────────
col_l, col_r = st.columns([3, 1])

with col_l:
    st.markdown('<div class="section-title">📈 Daily Reply Trend</div>', unsafe_allow_html=True)
    daily = df.groupby("DATE_ONLY")[["BUYER_MESSAGE_COUNT","TC_REPLY_COUNT","MP_REPLY_COUNT"]].sum().reset_index()
    daily["DATE_ONLY"] = pd.to_datetime(daily["DATE_ONLY"])
    daily_long = daily.melt(id_vars="DATE_ONLY", var_name="type", value_name="count")
    daily_long["type"] = daily_long["type"].map({
        "BUYER_MESSAGE_COUNT": "Buyer Messages",
        "TC_REPLY_COUNT":      "TC Replies",
        "MP_REPLY_COUNT":      "MP Replies"
    })
    AXIS = alt.Axis(labelColor="#ccc", titleColor="#ccc", gridColor="rgba(255,255,255,0.1)")
    st.altair_chart(
        alt.Chart(daily_long).mark_line(point=alt.OverlayMarkDef(size=60))
        .encode(
            x=alt.X("DATE_ONLY:T", title="Date", axis=alt.Axis(labelAngle=-35, labelColor="#ccc", titleColor="#ccc")),
            y=alt.Y("count:Q", title="Count", axis=AXIS),
            color=alt.Color("type:N", scale=alt.Scale(
                domain=["Buyer Messages","TC Replies","MP Replies"],
                range=["#94a3b8","#c084fc","#60a5fa"]),
                legend=alt.Legend(labelColor="#ccc", titleColor="#ccc")),
            tooltip=["DATE_ONLY:T","type:N","count:Q"]
        ).properties(height=300, background="transparent"),
        use_container_width=True
    )

with col_r:
    st.markdown('<div class="section-title">Reply Source</div>', unsafe_allow_html=True)
    pie_df = pd.DataFrame({
        "type":  ["TC Replies", "MP Replies"],
        "count": [total_tc, total_mp]
    }).query("count > 0")
    st.altair_chart(
        alt.Chart(pie_df).mark_arc(innerRadius=55)
        .encode(
            theta="count:Q",
            color=alt.Color("type:N", scale=alt.Scale(
                domain=["TC Replies","MP Replies"],
                range=["#c084fc","#60a5fa"]),
                legend=alt.Legend(labelColor="#ccc", titleColor="#ccc")),
            tooltip=["type:N","count:Q"]
        ).properties(height=300, background="transparent"),
        use_container_width=True
    )

# ─────────────────────────────────────────────────────────────────────────────
# ROW 2 — Merchant performance
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">🏪 Merchant Performance</div>', unsafe_allow_html=True)

merch = df.groupby("MERCHANT_ID").agg(
    buyer_messages      = ("BUYER_MESSAGE_COUNT","sum"),
    tc_replies          = ("TC_REPLY_COUNT","sum"),
    mp_replies          = ("MP_REPLY_COUNT","sum"),
    total_replies       = ("TOTAL_SELLER_REPLY_COUNT","sum"),
).reset_index()
merch["tc_pct"]    = (merch["tc_replies"] / merch["total_replies"].replace(0,1) * 100).round(1)
merch["reply_rate"] = (merch["total_replies"] / merch["buyer_messages"].replace(0,1) * 100).round(1)
merch = merch.sort_values("total_replies", ascending=False)

col_a, col_b = st.columns([3, 2])

with col_a:
    merch_long = merch.melt(
        id_vars="MERCHANT_ID",
        value_vars=["tc_replies","mp_replies"],
        var_name="type", value_name="count"
    )
    merch_long["type"] = merch_long["type"].map({"tc_replies":"TC","mp_replies":"MP"})
    BAR_AXIS = dict(labelColor="#ccc", titleColor="#ccc")
    st.altair_chart(
        alt.Chart(merch_long).mark_bar()
        .encode(
            x=alt.X("count:Q", title="Replies", axis=alt.Axis(**BAR_AXIS)),
            y=alt.Y("MERCHANT_ID:N", sort="-x", title="Merchant", axis=alt.Axis(**BAR_AXIS)),
            color=alt.Color("type:N", scale=alt.Scale(
                domain=["TC","MP"], range=["#c084fc","#60a5fa"]),
                legend=alt.Legend(labelColor="#ccc", titleColor="#ccc")),
            tooltip=["MERCHANT_ID:N","type:N","count:Q"]
        ).properties(height=360, background="transparent"),
        use_container_width=True
    )

with col_b:
    st.altair_chart(
        alt.Chart(merch).mark_bar(color="#c084fc", cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("MERCHANT_ID:N", sort="-y", title="Merchant",
                    axis=alt.Axis(labelAngle=-45, labelColor="#ccc", titleColor="#ccc")),
            y=alt.Y("tc_pct:Q", title="TC Reply %", scale=alt.Scale(domain=[0,100]),
                    axis=alt.Axis(labelColor="#ccc", titleColor="#ccc")),
            tooltip=["MERCHANT_ID:N","tc_pct:Q","tc_replies:Q","total_replies:Q"]
        ).properties(title=alt.TitleParams("TC Reply % by Merchant", color="#ccc"),
                     height=360, background="transparent"),
        use_container_width=True
    )

# ─────────────────────────────────────────────────────────────────────────────
# ROW 3 — Daily TC% trend per merchant (top 8 by TC replies)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">📈 Daily TC% Trend — Top Merchants</div>', unsafe_allow_html=True)

top_merchants = merch.nlargest(8, "tc_replies")["MERCHANT_ID"].tolist()
trend_df = df[df["MERCHANT_ID"].isin(top_merchants)].copy()
trend_df["DATE_ONLY"] = pd.to_datetime(trend_df["DATE_ONLY"])

col_t1, col_t2 = st.columns([2, 1])

with col_t1:
    st.altair_chart(
        alt.Chart(trend_df).mark_line(point=alt.OverlayMarkDef(size=40))
        .encode(
            x=alt.X("DATE_ONLY:T", title="Date", axis=alt.Axis(labelAngle=-35, labelColor="#ccc", titleColor="#ccc")),
            y=alt.Y("TC_REPLY_PCT:Q", title="TC Reply %",
                    axis=alt.Axis(labelColor="#ccc", titleColor="#ccc")),
            color=alt.Color("MERCHANT_ID:N",
                            legend=alt.Legend(labelColor="#ccc", titleColor="#ccc")),
            tooltip=["MERCHANT_ID:N","DATE_ONLY:T","TC_REPLY_PCT:Q","TC_REPLY_COUNT:Q","MP_REPLY_COUNT:Q"]
        ).properties(height=320, background="transparent"),
        use_container_width=True
    )

with col_t2:
    # Daily total TC vs MP stacked bar
    daily_totals = df.groupby("DATE_ONLY")[["TC_REPLY_COUNT","MP_REPLY_COUNT"]].sum().reset_index()
    daily_totals["DATE_ONLY"] = pd.to_datetime(daily_totals["DATE_ONLY"])
    daily_totals_long = daily_totals.melt(id_vars="DATE_ONLY", var_name="type", value_name="count")
    daily_totals_long["type"] = daily_totals_long["type"].map({"TC_REPLY_COUNT":"TC","MP_REPLY_COUNT":"MP"})
    st.altair_chart(
        alt.Chart(daily_totals_long).mark_bar()
        .encode(
            x=alt.X("DATE_ONLY:T", title="Date", axis=alt.Axis(labelAngle=-35, labelColor="#ccc", titleColor="#ccc")),
            y=alt.Y("count:Q", title="Replies", stack=True, axis=alt.Axis(labelColor="#ccc", titleColor="#ccc")),
            color=alt.Color("type:N", scale=alt.Scale(
                domain=["TC","MP"], range=["#c084fc","#60a5fa"]),
                legend=alt.Legend(labelColor="#ccc", titleColor="#ccc")),
            tooltip=["DATE_ONLY:T","type:N","count:Q"]
        ).properties(title=alt.TitleParams("Daily TC vs MP Replies", color="#ccc"),
                     height=320, background="transparent"),
        use_container_width=True
    )

# ─────────────────────────────────────────────────────────────────────────────
# DETAIL TABLE
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f'<div class="section-title">📋 Merchant Summary — {date_from} → {date_to}</div>', unsafe_allow_html=True)
disp = merch.copy()
disp.columns = ["Merchant","Buyer Messages","TC Replies","MP Replies","Total Replies","TC %","Reply Rate %"]
st.dataframe(disp, use_container_width=True, hide_index=True)

st.markdown(f'<div class="section-title">📋 Daily Detail — {date_from} → {date_to}</div>', unsafe_allow_html=True)
daily_detail = df[["DATE_ONLY","MERCHANT_ID","BUYER_MESSAGE_COUNT","TC_REPLY_COUNT",
                    "MP_REPLY_COUNT","TOTAL_SELLER_REPLY_COUNT","TC_REPLY_PCT"]].sort_values(
    ["DATE_ONLY","MERCHANT_ID"], ascending=[False,True])
daily_detail.columns = ["Date","Merchant","Buyer Msgs","TC Replies","MP Replies","Total Replies","TC%"]
st.dataframe(daily_detail, use_container_width=True, height=300, hide_index=True)

# ─────────────────────────────────────────────────────────────────────────────
# DOWNLOAD
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
d1, d2 = st.columns(2)
with d1:
    st.download_button("⬇️ Merchant Summary CSV",
                       merch.to_csv(index=False).encode(), "merchant_summary.csv", "text/csv")
with d2:
    st.download_button("⬇️ Daily Detail CSV",
                       df.to_csv(index=False).encode(), "daily_detail.csv", "text/csv")

# ─────────────────────────────────────────────────────────────────────────────
# SLACK
# ─────────────────────────────────────────────────────────────────────────────
def send_slack(token, channel):
    top = merch.head(8)
    rows = ""
    for _, r in top.iterrows():
        rows += f"\n• *{r['MERCHANT_ID']}* — TC: {int(r['tc_replies'])} ({r['tc_pct']}%) | MP: {int(r['mp_replies'])} | Total: {int(r['total_replies'])}"
    msg = f"""📊 *TC Chat Usage Report*
📅 Period: `{date_from}` → `{date_to}`
_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} SGT_

━━━━━━━━━━━━━━━━━━━━━━
*Overall Summary*
📨 Buyer Messages: *{total_buyer:,}*
📤 Total Replies: *{total_replies:,}* ({reply_rate}% reply rate)
✅ TC Replies: *{total_tc:,}* ({tc_pct}%)
🏪 MP Replies: *{total_mp:,}* ({mp_pct}%)

━━━━━━━━━━━━━━━━━━━━━━
*Merchant Breakdown*{rows}"""
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"channel": channel, "text": msg, "mrkdwn": True}
    )
    d = resp.json()
    return (True, "Sent ✓") if d.get("ok") else (False, d.get("error","Unknown"))

# Auto-send on new upload
file_key = uploaded.name
if auto_send and slack_token and st.session_state.get("sent_key") != file_key:
    st.session_state["sent_key"] = file_key
    ok, msg = send_slack(slack_token, slack_channel)
    st.toast("📤 Report sent to Slack!" if ok else f"Slack: {msg}", icon="✅" if ok else "⚠️")

st.markdown("### 📤 Send Report to Slack")
sc1, sc2 = st.columns([3, 1])
with sc1:
    st.caption(f"Posts to `{slack_channel}` (#automation-jira-test) · {date_from} → {date_to}")
with sc2:
    if st.button("Send Now 🚀", type="primary", use_container_width=True):
        if not slack_token:
            st.error("Add Slack Bot Token in sidebar.")
        else:
            with st.spinner("Sending…"):
                ok, msg = send_slack(slack_token, slack_channel)
            if ok:
                st.success("✅ Sent to #automation-jira-test!")
            else:
                st.error(f"Failed: {msg}")
