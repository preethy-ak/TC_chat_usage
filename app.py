import streamlit as st
import pandas as pd
import altair as alt
import requests
from datetime import datetime
import os
import io

st.set_page_config(
    page_title="BX Team & TC Usage Analyzer",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    div[data-testid="metric-container"] {
        background: white; border: 1px solid #eef0f8;
        border-radius: 10px; padding: 12px 18px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .section-title { font-size:1.1rem; font-weight:700; color:#1a1f36; margin:1.2rem 0 0.4rem; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 💬 BX & TC Analyzer")
    st.markdown("---")

    st.markdown("### 📁 File 1 — TC Logs")
    tc_file = st.file_uploader(
        "Upload GRAAS_CHATTR_LOGS CSV",
        type=["csv"], key="tc_upload",
        help="SQL export from GRAAS_CHATTR_LOGS (90-day query)"
    )

    st.markdown("### 📁 File 2 — Chat Enquiries")
    enq_file = st.file_uploader(
        "Upload Chat Enquiries Excel",
        type=["xlsx","xls"], key="enq_upload",
        help="Chat_enquiries Excel with all platform sheets (Feb → D-1)"
    )

    st.markdown("---")
    st.markdown("### ⚙️ Slack")
    slack_token   = st.text_input("Bot Token", type="password",
                                   value=os.environ.get("SLACK_BOT_TOKEN",""))
    slack_channel = st.text_input("Channel ID", value="C0AR6KRBUJC",
                                   help="#automation-jira-test")
    auto_send     = st.checkbox("Auto-send on upload", value=True)

    st.markdown("---")
    st.markdown("### 📅 Filters")

# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADERS
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data
def load_tc_logs(file_bytes):
    df = pd.read_csv(io.BytesIO(file_bytes))
    df.columns = df.columns.str.strip().str.upper()
    required = {"CONVERSATION_ID","ACTOR_TYPE","EVENT_TYPE","MERCHANT_ID","NICKNAME_ID","MESSAGE_ID"}
    missing = required - set(df.columns)
    if missing:
        st.error(f"TC file missing columns: {missing}. Found: {list(df.columns)}")
        st.stop()
    if "CREATED_AT" in df.columns:
        df["CREATED_AT"] = pd.to_datetime(df["CREATED_AT"], errors="coerce")
        df["TC_DATE"] = df["CREATED_AT"].dt.date
    df["ACTOR_TYPE"] = df["ACTOR_TYPE"].str.strip().str.lower()
    df["EVENT_TYPE"]  = df["EVENT_TYPE"].str.strip().str.upper()
    return df

@st.cache_data
def load_enquiries(file_bytes):
    xl = pd.ExcelFile(io.BytesIO(file_bytes))
    dfs = []
    for sheet in xl.sheet_names:
        try:
            df = xl.parse(sheet)
            df.columns = df.columns.str.strip().str.upper()
            df["_SHEET"] = sheet

            # Normalise date column
            for c in df.columns:
                if any(k in c for k in ["TIME","DATE","TS"]) and c not in ("MESSAGE_TYPE","BUYER_ID"):
                    try:
                        parsed = pd.to_datetime(df[c], errors="coerce")
                        if parsed.notna().sum() > len(df)*0.5:
                            df["MSG_DATE"] = parsed.dt.date
                            df["MSG_DT"]   = parsed
                            break
                    except: pass

            # Normalise message text col
            for c in ["MESSAGE_PARSED","MESSAGE","MESSAGE_TEXT"]:
                if c in df.columns:
                    df["_MSG"] = df[c]
                    break

            dfs.append(df)
        except Exception as e:
            st.warning(f"Skipped sheet '{sheet}': {e}")

    combined = pd.concat(dfs, ignore_index=True)
    combined.columns = combined.columns.str.strip().str.upper()

    # IS_ANSWERED — normalise to bool
    if "IS_ANSWERED" in combined.columns:
        combined["IS_ANSWERED"] = combined["IS_ANSWERED"].astype(str).str.strip().str.lower()
        combined["IS_ANSWERED"] = combined["IS_ANSWERED"].isin(["true","1","yes"])

    # Platform from SITE_NICK_NAME_ID
    if "SITE_NICK_NAME_ID" in combined.columns:
        combined["PLATFORM"] = combined["SITE_NICK_NAME_ID"].str.extract(r"^(\w+)-")[0].str.lower()
    else:
        combined["PLATFORM"] = "unknown"

    return combined

def build_conv_df(enq_df):
    """One row per CONVERSATION_ID, keeping first occurrence for meta."""
    date_col = "MSG_DT" if "MSG_DT" in enq_df.columns else None
    keep = ["CONVERSATION_ID","STORE_CODE","SITE_NICK_NAME_ID","CHANNEL_NAME",
            "COUNTRY_CODE","IS_ANSWERED","PLATFORM","_SHEET"]
    if date_col:
        enq_df = enq_df.sort_values(date_col)
        keep.append("MSG_DATE")
    available = [c for c in keep if c in enq_df.columns]
    conv = enq_df[available].drop_duplicates(subset=["CONVERSATION_ID"], keep="first")
    return conv

def build_tc_conv(tc_df):
    """Per-conversation TC summary."""
    agg = tc_df.groupby("CONVERSATION_ID").agg(
        tc_seller_msgs  = ("ACTOR_TYPE", lambda x: (x == "seller").sum()),
        tc_ai_msgs      = ("ACTOR_TYPE", lambda x: (x == "chattr").sum()),
        tc_total_msgs   = ("MESSAGE_ID", "nunique"),
        store_code      = ("MERCHANT_ID", "first"),
        nickname        = ("NICKNAME_ID", "first"),
    ).reset_index()
    agg["tc_replied"]   = True
    agg["tc_ai_only"]   = (agg["tc_seller_msgs"] == 0) & (agg["tc_ai_msgs"] > 0)
    agg["tc_human"]     = agg["tc_seller_msgs"] > 0
    return agg

# ─────────────────────────────────────────────────────────────────────────────
# SLACK
# ─────────────────────────────────────────────────────────────────────────────
def send_slack_report(summary, top_stores, token, channel):
    if not token or not token.startswith("xoxb-"):
        return False, "Invalid token"

    total   = summary["total_conversations"]
    tc      = summary["tc_conversations"]
    mp      = summary["mp_conversations"]
    unans   = summary["unanswered"]
    ai_rep  = summary["tc_ai_replies"]
    sel_rep = summary["tc_seller_replies"]

    tc_pct   = round(tc/total*100,1)   if total else 0
    mp_pct   = round(mp/total*100,1)   if total else 0
    un_pct   = round(unans/total*100,1) if total else 0
    ai_pct   = round(ai_rep/tc*100,1)  if tc else 0

    store_rows = ""
    for _, r in top_stores.iterrows():
        store_rows += f"\n• *{r['store_code']} ({r['nickname']})* — TC: {int(r['tc_conversations'])} | AI: {int(r['tc_ai_replies'])} | Seller: {int(r['tc_seller_replies'])} | MP: {int(r['mp_conversations'])} | Unanswered: {int(r['unanswered'])}"

    msg = f"""📊 *BX Team & TC Usage Report*
_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} SGT_

━━━━━━━━━━━━━━━━━━━━━━
*Overall Conversation Summary*
💬 Total Conversations: *{total:,}*
✅ TC Handled: *{tc:,}* ({tc_pct}%)
🏪 MP Direct: *{mp:,}* ({mp_pct}%)
❌ Unanswered: *{unans:,}* ({un_pct}%)

*TC Usage Breakdown*
🤖 TC AI Replies: *{ai_rep:,}* ({ai_pct}% of TC)
👤 TC Seller Replies: *{sel_rep:,}*

━━━━━━━━━━━━━━━━━━━━━━
*Top Stores Performance*{store_rows}"""

    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"channel": channel, "text": msg, "mrkdwn": True}
    )
    d = resp.json()
    return (True, "Sent ✓") if d.get("ok") else (False, d.get("error","Unknown"))

# ─────────────────────────────────────────────────────────────────────────────
# LANDING
# ─────────────────────────────────────────────────────────────────────────────
st.title("💬 BX Team & TC Usage Analyzer")

if not tc_file or not enq_file:
    st.info("👈 Upload **both files** in the sidebar to begin.")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""**File 1 — TC Logs CSV**
Export from `GRAAS_CHATTR_LOGS` (90-day SQL query).
Identifies which conversations were handled by TC and whether by AI or seller.""")
    with col2:
        st.markdown("""**File 2 — Chat Enquiries Excel**
All platform sheets (Lazada, Shopee, TikTok) from Feb → D-1.
Provides total conversation volume and answered/unanswered status.""")
    st.markdown("""
| Metric | How it's calculated |
|---|---|
| Total Conversations | All unique CONVERSATION_IDs in Chat Enquiries |
| TC Handled | Conversations found in TC Logs |
| TC AI Replies | TC conversations with `chattr` actor type |
| TC Seller Replies | TC conversations with `seller` actor type |
| MP Replied | Answered (IS_ANSWERED=True) but NOT in TC Logs |
| Unanswered | IS_ANSWERED=False |
""")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# LOAD
# ─────────────────────────────────────────────────────────────────────────────
with st.spinner("Loading files…"):
    tc_df   = load_tc_logs(tc_file.read())
    enq_df  = load_enquiries(enq_file.read())

conv_df  = build_conv_df(enq_df)
tc_conv  = build_tc_conv(tc_df)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR FILTERS
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    platforms = sorted(conv_df["PLATFORM"].dropna().unique()) if "PLATFORM" in conv_df.columns else []
    sel_platform = st.multiselect("Platform", options=platforms, placeholder="All")

    stores = sorted(conv_df["STORE_CODE"].dropna().unique()) if "STORE_CODE" in conv_df.columns else []
    sel_store = st.multiselect("Store Code", options=stores, placeholder="All")

    if "MSG_DATE" in conv_df.columns:
        min_d = conv_df["MSG_DATE"].min()
        max_d = conv_df["MSG_DATE"].max()
        date_from = st.date_input("From", value=min_d, min_value=min_d, max_value=max_d)
        date_to   = st.date_input("To",   value=max_d, min_value=min_d, max_value=max_d)
    else:
        date_from = date_to = None

# ─────────────────────────────────────────────────────────────────────────────
# APPLY FILTERS
# ─────────────────────────────────────────────────────────────────────────────
fconv = conv_df.copy()
if sel_platform and "PLATFORM" in fconv.columns:
    fconv = fconv[fconv["PLATFORM"].isin(sel_platform)]
if sel_store and "STORE_CODE" in fconv.columns:
    fconv = fconv[fconv["STORE_CODE"].isin(sel_store)]
if date_from and "MSG_DATE" in fconv.columns:
    fconv = fconv[(fconv["MSG_DATE"] >= date_from) & (fconv["MSG_DATE"] <= date_to)]

if fconv.empty:
    st.warning("No data for selected filters.")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# MERGE & METRICS
# ─────────────────────────────────────────────────────────────────────────────
merged = fconv.merge(
    tc_conv[["CONVERSATION_ID","tc_replied","tc_seller_msgs","tc_ai_msgs","tc_total_msgs","tc_ai_only","tc_human","store_code","nickname"]],
    on="CONVERSATION_ID", how="left"
)
merged["tc_replied"]    = merged["tc_replied"].fillna(False)
merged["tc_seller_msgs"]= merged["tc_seller_msgs"].fillna(0)
merged["tc_ai_msgs"]    = merged["tc_ai_msgs"].fillna(0)
merged["tc_ai_only"]    = merged["tc_ai_only"].fillna(False)
merged["tc_human"]      = merged["tc_human"].fillna(False)

# Derive categories
is_answered = merged["IS_ANSWERED"] if "IS_ANSWERED" in merged.columns else pd.Series([True]*len(merged))
merged["answered"]         = is_answered
merged["tc_handled"]       = merged["tc_replied"]
merged["mp_replied"]       = merged["answered"] & ~merged["tc_replied"]
merged["unanswered"]       = ~merged["answered"]

total       = len(merged)
tc_total    = int(merged["tc_handled"].sum())
mp_total    = int(merged["mp_replied"].sum())
unanswered  = int(merged["unanswered"].sum())
tc_ai       = int(merged["tc_ai_only"].sum())
tc_seller   = int(merged["tc_human"].sum())
tc_both     = tc_total - tc_ai - tc_seller  # has both

summary = {
    "total_conversations": total,
    "tc_conversations":    tc_total,
    "mp_conversations":    mp_total,
    "unanswered":          unanswered,
    "tc_ai_replies":       tc_ai,
    "tc_seller_replies":   tc_seller,
}

# ─────────────────────────────────────────────────────────────────────────────
# AUTO SLACK
# ─────────────────────────────────────────────────────────────────────────────
if auto_send and slack_token and "sent_key" not in st.session_state:
    st.session_state["sent_key"] = f"{tc_file.name}_{enq_file.name}"
    top_s = (
        merged[merged["tc_handled"]].groupby(["store_code","nickname"]).agg(
            tc_conversations=("CONVERSATION_ID","count"),
            tc_ai_replies=("tc_ai_only","sum"),
            tc_seller_replies=("tc_human","sum"),
            mp_conversations=("mp_replied","sum"),
            unanswered=("unanswered","sum"),
        ).sort_values("tc_conversations", ascending=False).head(8).reset_index()
    )
    ok, msg = send_slack_report(summary, top_s, slack_token, slack_channel)
    st.toast("📤 Report sent to Slack!" if ok else f"Slack: {msg}", icon="✅" if ok else "⚠️")

# ─────────────────────────────────────────────────────────────────────────────
# KPI ROW
# ─────────────────────────────────────────────────────────────────────────────
tc_pct  = round(tc_total/total*100,1) if total else 0
mp_pct  = round(mp_total/total*100,1) if total else 0
un_pct  = round(unanswered/total*100,1) if total else 0
ai_pct  = round(tc_ai/tc_total*100,1) if tc_total else 0

c1,c2,c3,c4,c5,c6,c7 = st.columns(7)
c1.metric("💬 Total Chats",     f"{total:,}")
c2.metric("✅ TC Handled",      f"{tc_total:,}",  f"{tc_pct}%")
c3.metric("🏪 MP Replied",     f"{mp_total:,}",  f"{mp_pct}%")
c4.metric("❌ Unanswered",      f"{unanswered:,}", f"{un_pct}%")
c5.metric("🤖 TC AI Replies",   f"{tc_ai:,}",     f"{ai_pct}% of TC")
c6.metric("👤 TC Seller",       f"{tc_seller:,}")
c7.metric("🔀 TC AI+Seller",    f"{tc_both:,}")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# CHARTS ROW 1 — Overall breakdown + Platform split
# ─────────────────────────────────────────────────────────────────────────────
col_a, col_b, col_c = st.columns([1,1,1])

with col_a:
    st.markdown('<div class="section-title">Overall Reply Source</div>', unsafe_allow_html=True)
    pie_df = pd.DataFrame({
        "type":  ["TC AI Only","TC Seller","MP Replied","Unanswered"],
        "count": [tc_ai, tc_seller, mp_total, unanswered]
    }).query("count > 0")
    pie = (alt.Chart(pie_df).mark_arc(innerRadius=50)
           .encode(theta=alt.Theta("count:Q"),
                   color=alt.Color("type:N", scale=alt.Scale(
                       domain=["TC AI Only","TC Seller","MP Replied","Unanswered"],
                       range=["#a855f7","#f59e0b","#3b82f6","#ef4444"])),
                   tooltip=["type:N","count:Q"])
           .properties(height=260))
    st.altair_chart(pie, use_container_width=True)

with col_b:
    st.markdown('<div class="section-title">By Platform</div>', unsafe_allow_html=True)
    if "PLATFORM" in merged.columns:
        plat = merged.groupby("PLATFORM").agg(
            TC=("tc_handled","sum"), MP=("mp_replied","sum"), Unanswered=("unanswered","sum")
        ).reset_index()
        plat_long = plat.melt(id_vars="PLATFORM", var_name="type", value_name="count")
        bar_plat = (alt.Chart(plat_long).mark_bar()
                    .encode(x=alt.X("PLATFORM:N", title="Platform"),
                            y=alt.Y("count:Q", title="Conversations"),
                            color=alt.Color("type:N", scale=alt.Scale(
                                domain=["TC","MP","Unanswered"],
                                range=["#a855f7","#3b82f6","#ef4444"])),
                            tooltip=["PLATFORM:N","type:N","count:Q"])
                    .properties(height=260))
        st.altair_chart(bar_plat, use_container_width=True)

with col_c:
    st.markdown('<div class="section-title">TC Usage — AI vs Seller</div>', unsafe_allow_html=True)
    tc_type_df = pd.DataFrame({
        "type":  ["AI Only","Seller Only","Both AI+Seller"],
        "count": [tc_ai, tc_seller, tc_both]
    }).query("count > 0")
    bar_tc = (alt.Chart(tc_type_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
              .encode(x=alt.X("type:N", title=""),
                      y=alt.Y("count:Q", title="Conversations"),
                      color=alt.Color("type:N", scale=alt.Scale(
                          domain=["AI Only","Seller Only","Both AI+Seller"],
                          range=["#a855f7","#f59e0b","#22c55e"])),
                      tooltip=["type:N","count:Q"])
              .properties(height=260))
    st.altair_chart(bar_tc, use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# CHART ROW 2 — Daily trend
# ─────────────────────────────────────────────────────────────────────────────
if "MSG_DATE" in merged.columns:
    st.markdown('<div class="section-title">📈 Daily Conversation Trend</div>', unsafe_allow_html=True)
    daily = merged.groupby("MSG_DATE").agg(
        TC=("tc_handled","sum"), MP=("mp_replied","sum"), Unanswered=("unanswered","sum")
    ).reset_index()
    daily["MSG_DATE"] = pd.to_datetime(daily["MSG_DATE"])
    daily_long = daily.melt(id_vars="MSG_DATE", var_name="type", value_name="count")
    trend = (alt.Chart(daily_long).mark_line(point=True)
             .encode(x=alt.X("MSG_DATE:T", title="Date", axis=alt.Axis(labelAngle=-35)),
                     y=alt.Y("count:Q", title="Conversations"),
                     color=alt.Color("type:N", scale=alt.Scale(
                         domain=["TC","MP","Unanswered"],
                         range=["#a855f7","#3b82f6","#ef4444"])),
                     tooltip=["MSG_DATE:T","type:N","count:Q"])
             .properties(height=280))
    st.altair_chart(trend, use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# CHART ROW 3 — BX Store Performance
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">🏪 BX Team Performance by Store</div>', unsafe_allow_html=True)

store_perf = merged.groupby(["STORE_CODE","PLATFORM"]).agg(
    total_conversations = ("CONVERSATION_ID","count"),
    tc_conversations    = ("tc_handled","sum"),
    tc_ai_replies       = ("tc_ai_only","sum"),
    tc_seller_replies   = ("tc_human","sum"),
    mp_conversations    = ("mp_replied","sum"),
    unanswered          = ("unanswered","sum"),
).reset_index()
store_perf["tc_pct"]      = (store_perf["tc_conversations"] / store_perf["total_conversations"] * 100).round(1)
store_perf["unanswered_pct"] = (store_perf["unanswered"] / store_perf["total_conversations"] * 100).round(1)
store_perf = store_perf.sort_values("total_conversations", ascending=False)

col_left, col_right = st.columns([3,2])
with col_left:
    top12 = store_perf.head(12)
    top12_long = top12.melt(
        id_vars=["STORE_CODE","PLATFORM"],
        value_vars=["tc_conversations","mp_conversations","unanswered"],
        var_name="type", value_name="count"
    )
    top12_long["type"] = top12_long["type"].map({
        "tc_conversations":"TC","mp_conversations":"MP","unanswered":"Unanswered"
    })
    store_bar = (alt.Chart(top12_long).mark_bar()
                 .encode(x=alt.X("count:Q", title="Conversations"),
                         y=alt.Y("STORE_CODE:N", sort="-x", title="Store"),
                         color=alt.Color("type:N", scale=alt.Scale(
                             domain=["TC","MP","Unanswered"],
                             range=["#a855f7","#3b82f6","#ef4444"])),
                         tooltip=["STORE_CODE:N","type:N","count:Q"])
                 .properties(height=360))
    st.altair_chart(store_bar, use_container_width=True)

with col_right:
    # TC % bubble
    bubble = (alt.Chart(store_perf.head(15))
              .mark_circle()
              .encode(x=alt.X("tc_pct:Q", title="TC Handled %", scale=alt.Scale(domain=[0,105])),
                      y=alt.Y("unanswered_pct:Q", title="Unanswered %"),
                      size=alt.Size("total_conversations:Q", scale=alt.Scale(range=[60,1000])),
                      color=alt.Color("PLATFORM:N"),
                      tooltip=["STORE_CODE:N","PLATFORM:N","total_conversations:Q",
                                "tc_pct:Q","unanswered_pct:Q"])
              .properties(title="TC% vs Unanswered% (bubble = volume)", height=360))
    st.altair_chart(bubble, use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# STORE DETAIL TABLE
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">📋 Store Detail Table</div>', unsafe_allow_html=True)
disp = store_perf.copy()
disp.columns = [c.replace("_"," ").title() for c in disp.columns]
st.dataframe(disp, use_container_width=True, height=320, hide_index=True)

# ─────────────────────────────────────────────────────────────────────────────
# MONTHLY SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
if "MSG_DATE" in merged.columns:
    st.markdown('<div class="section-title">📅 Monthly Summary</div>', unsafe_allow_html=True)
    merged["month"] = pd.to_datetime(merged["MSG_DATE"]).dt.to_period("M").astype(str)
    monthly = merged.groupby("month").agg(
        total=("CONVERSATION_ID","count"),
        tc=("tc_handled","sum"),
        mp=("mp_replied","sum"),
        unanswered=("unanswered","sum"),
        tc_ai=("tc_ai_only","sum"),
        tc_seller=("tc_human","sum"),
    ).reset_index()
    monthly["tc_pct"] = (monthly["tc"]/monthly["total"]*100).round(1)
    monthly["unanswered_pct"] = (monthly["unanswered"]/monthly["total"]*100).round(1)
    monthly.columns = [c.replace("_"," ").title() for c in monthly.columns]
    st.dataframe(monthly, use_container_width=True, hide_index=True)

# ─────────────────────────────────────────────────────────────────────────────
# DOWNLOAD
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
dl1, dl2 = st.columns(2)
with dl1:
    csv1 = store_perf.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Store Performance CSV", csv1, "store_performance.csv", "text/csv")
with dl2:
    csv2 = merged[["CONVERSATION_ID","STORE_CODE","PLATFORM","IS_ANSWERED",
                    "tc_handled","mp_replied","unanswered","tc_ai_only","tc_human"]].to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Conversation Detail CSV", csv2, "conversation_detail.csv", "text/csv")

# ─────────────────────────────────────────────────────────────────────────────
# MANUAL SLACK
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("### 📤 Send Report to Slack")
c1, c2 = st.columns([3,1])
with c1:
    st.caption(f"Posts summary to `{slack_channel}` (#automation-jira-test)")
with c2:
    if st.button("Send Now 🚀", type="primary", use_container_width=True):
        if not slack_token:
            st.error("Add Slack Bot Token in sidebar.")
        else:
            top_s = (
                store_perf.rename(columns={"STORE_CODE":"store_code","tc_ai_replies":"tc_ai_replies",
                                           "tc_seller_replies":"tc_seller_replies","mp_conversations":"mp_conversations",
                                           "unanswered":"unanswered","tc_conversations":"tc_conversations"})
                .assign(nickname=store_perf.get("SITE_NICK_NAME_ID", store_perf["STORE_CODE"]))
                .sort_values("tc_conversations", ascending=False).head(8)
            )
            with st.spinner("Sending…"):
                ok, msg = send_slack_report(summary, top_s, slack_token, slack_channel)
            st.success("✅ Sent to #automation-jira-test!") if ok else st.error(f"Failed: {msg}")
