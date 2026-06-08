import streamlit as st
import pandas as pd
import altair as alt
import requests
from datetime import datetime
import os
import io
import zipfile
import xml.etree.ElementTree as ET
import re

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
    .section-title {
        font-size: 1.05rem; font-weight: 700;
        color: #1a1f36; margin: 1.2rem 0 0.3rem;
    }
</style>
""", unsafe_allow_html=True)

EXCEL_EPOCH = pd.Timestamp("1899-12-30")

# ─────────────────────────────────────────────────────────────────────────────
# STDLIB XLSX READER  (no openpyxl needed)
# ─────────────────────────────────────────────────────────────────────────────
def _col_num(ref):
    m = re.match(r"([A-Z]+)", ref.upper())
    if not m: return 0
    n = 0
    for c in m.group(1): n = n * 26 + (ord(c) - 64)
    return n - 1

def _read_xlsx(file_bytes):
    NS  = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        names = zf.namelist()
        sst = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{{{NS}}}si"):
                sst.append("".join(t.text or "" for t in si.iter(f"{{{NS}}}t")))
        wb   = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        id_path = {r.get("Id"): r.get("Target","") for r in rels}
        sheet_map = {}
        for sh in wb.findall(f".//{{{NS}}}sheet"):
            rid = sh.get(f"{{{RNS}}}id","")
            tgt = id_path.get(rid,"")
            path = ("xl/"+tgt) if not tgt.startswith("xl/") else tgt
            if path in names: sheet_map[sh.get("name","Sheet")] = path
        result = {}
        for sname, path in sheet_map.items():
            root = ET.fromstring(zf.read(path))
            grid = {}
            for row_el in root.findall(f".//{{{NS}}}row"):
                rn = int(row_el.get("r", 0))
                for c_el in row_el.findall(f"{{{NS}}}c"):
                    ref = c_el.get("r","")
                    if not ref: continue
                    ci = _col_num(ref)
                    t  = c_el.get("t","")
                    v  = c_el.find(f"{{{NS}}}v")
                    if v is not None and v.text is not None:
                        if t == "s":   val = sst[int(v.text)] if int(v.text) < len(sst) else ""
                        elif t == "b": val = v.text == "1"
                        else:
                            try: val = float(v.text)
                            except: val = v.text
                    else: val = None
                    grid.setdefault(rn, {})[ci] = val
            if not grid: continue
            srnums = sorted(grid)
            mc = max(max(r.keys(), default=0) for r in grid.values())
            hdrs = [str(grid[srnums[0]].get(i, f"col_{i}")) for i in range(mc+1)]
            rows = [{hdrs[i]: grid[rn].get(i) for i in range(mc+1)} for rn in srnums[1:]]
            result[sname] = pd.DataFrame(rows)
    return result

# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADERS
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data
def load_tc_logs(file_bytes):
    df = pd.read_csv(io.BytesIO(file_bytes))
    df.columns = df.columns.str.strip().str.upper()
    required = {"CONVERSATION_ID","ACTOR_TYPE","MERCHANT_ID","NICKNAME_ID","MESSAGE_ID"}
    missing = required - set(df.columns)
    if missing:
        st.error(f"TC file missing columns: {missing}. Found: {list(df.columns)}")
        st.stop()
    if "CREATED_AT" in df.columns:
        df["CREATED_AT"] = pd.to_datetime(df["CREATED_AT"], errors="coerce")
        df["TC_DATE"] = df["CREATED_AT"].dt.date
    df["ACTOR_TYPE"] = df["ACTOR_TYPE"].astype(str).str.strip().str.lower()
    return df

@st.cache_data
def load_enquiries(file_bytes):
    sheet_dict = _read_xlsx(file_bytes)
    dfs = []
    for sheet, df in sheet_dict.items():
        try:
            df = df.copy()
            df.columns = [str(c).strip().upper() for c in df.columns]
            df["_SHEET"] = sheet
            # Detect & parse date column
            for c in df.columns:
                if any(k in c for k in ["TIME","DATE","TS"]) and c not in ("MESSAGE_TYPE","BUYER_ID"):
                    try:
                        col = df[c]
                        if pd.api.types.is_numeric_dtype(col):
                            parsed = EXCEL_EPOCH + pd.to_timedelta(col.astype(float), unit="D")
                        else:
                            parsed = pd.to_datetime(col, errors="coerce")
                        if parsed.notna().sum() > len(df) * 0.5:
                            df["MSG_DT"]   = parsed
                            df["MSG_DATE"] = parsed.dt.date
                            break
                    except: pass
            dfs.append(df)
        except Exception as e:
            st.warning(f"Skipped sheet '{sheet}': {e}")

    combined = pd.concat(dfs, ignore_index=True)
    combined.columns = combined.columns.str.strip().str.upper()

    # Force MSG_DATE to pure datetime.date (eliminates float/mixed type errors)
    if "MSG_DATE" in combined.columns:
        combined["MSG_DATE"] = pd.to_datetime(combined["MSG_DATE"], errors="coerce").dt.date
    if "MSG_DT" in combined.columns:
        combined["MSG_DT"] = pd.to_datetime(combined["MSG_DT"], errors="coerce")

    # Platform
    if "SITE_NICK_NAME_ID" in combined.columns:
        combined["PLATFORM"] = (
            combined["SITE_NICK_NAME_ID"].str.extract(r"^(\w+)-")[0].str.lower()
        )
    else:
        combined["PLATFORM"] = "unknown"

    # SENDER normalise
    if "SENDER" in combined.columns:
        combined["SENDER"] = combined["SENDER"].astype(str).str.strip().str.lower()

    # platform_replied logic (per platform):
    #   Lazada / Shopee: IS_ANSWERED=True on ANY message → replied (platform flag is reliable)
    #   TikTok: IS_ANSWERED is ALWAYS False → use last-message sender instead
    REPLY_SENDERS = {"seller","system","robot"}

    if "IS_ANSWERED" in combined.columns:
        combined["_is_answered_bool"] = (
            combined["IS_ANSWERED"].astype(str).str.strip().str.lower()
            .isin(["true","1","yes"])
        )
    else:
        combined["_is_answered_bool"] = False

    # Conversations where IS_ANSWERED=True for at least one message
    is_answered_convs = set(
        combined[combined["_is_answered_bool"]]["CONVERSATION_ID"]
    )

    # For TikTok (IS_ANSWERED unreliable): last-message sender
    tiktok_msgs = combined[combined["PLATFORM"] == "tiktok"].copy()
    if "MSG_DT" in tiktok_msgs.columns and len(tiktok_msgs):
        last_tiktok = (
            tiktok_msgs.sort_values("MSG_DT")
            .drop_duplicates("CONVERSATION_ID", keep="last")[["CONVERSATION_ID","SENDER"]]
        )
        tiktok_replied = set(
            last_tiktok[last_tiktok["SENDER"].isin(REPLY_SENDERS)]["CONVERSATION_ID"]
        )
    else:
        tiktok_replied = set(
            tiktok_msgs[tiktok_msgs["SENDER"].isin(REPLY_SENDERS)]["CONVERSATION_ID"]
        )

    all_replied = is_answered_convs | tiktok_replied
    combined["platform_replied"] = combined["CONVERSATION_ID"].isin(all_replied)

    return combined

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def build_conv_df(enq_df):
    """One row per conversation — use earliest message for metadata, platform_replied from last msg."""
    keep = ["CONVERSATION_ID","STORE_CODE","SITE_NICK_NAME_ID","CHANNEL_NAME",
            "COUNTRY_CODE","platform_replied","PLATFORM","_SHEET","MSG_DATE"]
    cols = [c for c in keep if c in enq_df.columns]
    # Sort by time ascending, keep first occurrence for metadata (date, store etc.)
    if "MSG_DT" in enq_df.columns:
        enq_df = enq_df.sort_values("MSG_DT")
    return enq_df[cols].drop_duplicates(subset=["CONVERSATION_ID"], keep="first")

def build_tc_conv(tc_df):
    agg = tc_df.groupby("CONVERSATION_ID").agg(
        tc_seller_msgs = ("ACTOR_TYPE", lambda x: (x=="seller").sum()),
        tc_ai_msgs     = ("ACTOR_TYPE", lambda x: (x=="chattr").sum()),
        store_code     = ("MERCHANT_ID", "first"),
        nickname       = ("NICKNAME_ID", "first"),
    ).reset_index()
    agg["tc_replied"] = True
    agg["tc_ai_only"] = (agg["tc_seller_msgs"]==0) & (agg["tc_ai_msgs"]>0)
    agg["tc_human"]   = agg["tc_seller_msgs"] > 0
    return agg

def compute_summary(merged):
    total    = len(merged)
    tc       = int(merged["tc_handled"].sum())
    mp       = int(merged["mp_replied"].sum())
    unans    = int(merged["unanswered"].sum())
    tc_ai    = int(merged["tc_ai_only"].sum())
    tc_sel   = int(merged["tc_human"].sum())
    return dict(total_conversations=total, tc_conversations=tc,
                mp_conversations=mp, unanswered=unans,
                tc_ai_replies=tc_ai, tc_seller_replies=tc_sel)

# ─────────────────────────────────────────────────────────────────────────────
# SLACK
# ─────────────────────────────────────────────────────────────────────────────
def send_slack_report(summary, store_df, token, channel, date_from, date_to):
    if not token or not token.startswith("xoxb-"):
        return False, "Invalid token"
    k = summary
    tc_pct = round(k["tc_conversations"]/k["total_conversations"]*100,1) if k["total_conversations"] else 0
    mp_pct = round(k["mp_conversations"]/k["total_conversations"]*100,1) if k["total_conversations"] else 0
    un_pct = round(k["unanswered"]/k["total_conversations"]*100,1)       if k["total_conversations"] else 0
    ai_pct = round(k["tc_ai_replies"]/k["tc_conversations"]*100,1)       if k["tc_conversations"] else 0
    rows = ""
    for _, r in store_df.iterrows():
        rows += f"\n• *{r['STORE_CODE']} ({r.get('PLATFORM','')})* — Total: {int(r['total_conversations'])} | TC: {int(r['tc_conversations'])} | MP: {int(r['mp_conversations'])} | Unanswered: {int(r['unanswered'])}"
    msg = f"""📊 *BX Team & TC Usage Report*
📅 Period: `{date_from}` → `{date_to}`
_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} SGT_

━━━━━━━━━━━━━━━━━━━━━━
*Overall Summary*
💬 Total Conversations: *{k['total_conversations']:,}*
✅ TC Handled: *{k['tc_conversations']:,}* ({tc_pct}%)
🏪 MP Direct: *{k['mp_conversations']:,}* ({mp_pct}%)
❌ Unanswered: *{k['unanswered']:,}* ({un_pct}%)

*TC Breakdown*
🤖 AI Replies: *{k['tc_ai_replies']:,}* ({ai_pct}% of TC)
👤 Seller Replies: *{k['tc_seller_replies']:,}*

━━━━━━━━━━━━━━━━━━━━━━
*Store Performance*{rows}"""
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"channel": channel, "text": msg, "mrkdwn": True}
    )
    d = resp.json()
    return (True, "Sent ✓") if d.get("ok") else (False, d.get("error","Unknown"))

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 💬 BX & TC Analyzer")
    st.markdown("---")
    st.markdown("### 📁 File 1 — TC Logs (CSV)")
    tc_file  = st.file_uploader("GRAAS_CHATTR_LOGS export", type=["csv"], key="tc")
    st.markdown("### 📁 File 2 — Chat Enquiries (Excel)")
    enq_file = st.file_uploader("Chat_enquiries Excel", type=["xlsx","xls"], key="enq")
    st.markdown("---")
    st.markdown("### ⚙️ Slack")
    slack_token   = st.text_input("Bot Token", type="password",
                                   value=os.environ.get("SLACK_BOT_TOKEN",""))
    slack_channel = st.text_input("Channel ID", value="C0AR6KRBUJC")
    auto_send     = st.checkbox("Auto-send on upload", value=True)

# ─────────────────────────────────────────────────────────────────────────────
# LANDING PAGE
# ─────────────────────────────────────────────────────────────────────────────
st.title("💬 BX Team & TC Usage Analyzer")

if not tc_file or not enq_file:
    st.info("👈 Upload **both files** in the sidebar to begin.")
    st.markdown("""
| File | What it is | Key columns |
|---|---|---|
| TC Logs CSV | GRAAS_CHATTR_LOGS 90-day export | CONVERSATION_ID, ACTOR_TYPE, MERCHANT_ID |
| Chat Enquiries Excel | All platform chats Feb → D-1 | CONVERSATION_ID, IS_ANSWERED, STORE_CODE |

**Metrics logic:**
- **TC Handled** = Conversations found in TC Logs
- **MP Replied** = Has a seller/system reply in chat enquiries but NOT in TC Logs
- **Unanswered** = No seller/system reply anywhere (works correctly for TikTok too)
- **TC AI** = TC conversations where only `chattr` actor replied
- **TC Seller** = TC conversations where `seller` actor replied
""")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────────────────────────────────────
with st.spinner("Loading files…"):
    tc_df    = load_tc_logs(tc_file.read())
    enq_df   = load_enquiries(enq_file.read())

conv_df  = build_conv_df(enq_df)
tc_conv  = build_tc_conv(tc_df)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR FILTERS  (shown after data loads)
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("---")
    st.markdown("### 📅 Date Filter")
    has_dates = "MSG_DATE" in conv_df.columns and conv_df["MSG_DATE"].notna().any()
    if has_dates:
        valid_dates = conv_df["MSG_DATE"].dropna()
        min_d = valid_dates.min()
        max_d = valid_dates.max()
        date_from = st.date_input("From", value=min_d, min_value=min_d, max_value=max_d)
        date_to   = st.date_input("To",   value=max_d, min_value=min_d, max_value=max_d)
    else:
        date_from = date_to = None

    st.markdown("### 🏪 Store / Platform")
    all_platforms = sorted(conv_df["PLATFORM"].dropna().unique()) if "PLATFORM" in conv_df.columns else []
    sel_platform  = st.multiselect("Platform", all_platforms, placeholder="All")

    all_stores = sorted(conv_df["STORE_CODE"].dropna().unique()) if "STORE_CODE" in conv_df.columns else []
    sel_store  = st.multiselect("Store Code", all_stores, placeholder="All")

# ─────────────────────────────────────────────────────────────────────────────
# APPLY FILTERS — everything downstream uses `fconv` only
# ─────────────────────────────────────────────────────────────────────────────
fconv = conv_df.copy()

# Date filter
if date_from and has_dates:
    fconv = fconv[
        fconv["MSG_DATE"].notna() &
        (fconv["MSG_DATE"] >= date_from) &
        (fconv["MSG_DATE"] <= date_to)
    ]

# Platform filter
if sel_platform and "PLATFORM" in fconv.columns:
    fconv = fconv[fconv["PLATFORM"].isin(sel_platform)]

# Store filter
if sel_store and "STORE_CODE" in fconv.columns:
    fconv = fconv[fconv["STORE_CODE"].isin(sel_store)]

if fconv.empty:
    st.warning("No data matches the selected filters.")
    st.stop()

# Active filter banner
filter_parts = []
if date_from and has_dates:
    filter_parts.append(f"📅 {date_from} → {date_to}")
if sel_platform:
    filter_parts.append(f"Platform: {', '.join(sel_platform)}")
if sel_store:
    filter_parts.append(f"Store: {', '.join(sel_store)}")
if filter_parts:
    st.info("**Active filters:** " + "  |  ".join(filter_parts))

# ─────────────────────────────────────────────────────────────────────────────
# MERGE & CLASSIFY
# ─────────────────────────────────────────────────────────────────────────────
merged = fconv.merge(
    tc_conv[["CONVERSATION_ID","tc_replied","tc_ai_only","tc_human","store_code","nickname"]],
    on="CONVERSATION_ID", how="left"
)
for col in ["tc_replied","tc_ai_only","tc_human"]:
    merged[col] = merged[col].fillna(False).infer_objects(copy=False)

# Use platform_replied (SENDER-based) — correct for all platforms including TikTok
# IS_ANSWERED is unreliable (always False for TikTok)
plat_replied = merged["platform_replied"] if "platform_replied" in merged.columns \
               else pd.Series(True, index=merged.index)

merged["tc_handled"] = merged["tc_replied"]
merged["mp_replied"] = plat_replied & ~merged["tc_replied"]
merged["unanswered"] = ~plat_replied & ~merged["tc_replied"]

summary = compute_summary(merged)
k = summary

# ─────────────────────────────────────────────────────────────────────────────
# AUTO SLACK
# ─────────────────────────────────────────────────────────────────────────────
file_key = f"{tc_file.name}|{enq_file.name}"
if auto_send and slack_token and st.session_state.get("sent_key") != file_key:
    st.session_state["sent_key"] = file_key
    store_snap = merged.groupby(["STORE_CODE","PLATFORM"]).agg(
        total_conversations=("CONVERSATION_ID","count"),
        tc_conversations=("tc_handled","sum"),
        mp_conversations=("mp_replied","sum"),
        unanswered=("unanswered","sum"),
    ).sort_values("tc_conversations", ascending=False).head(8).reset_index()
    ok, msg = send_slack_report(summary, store_snap, slack_token, slack_channel,
                                 date_from or "–", date_to or "–")
    st.toast("📤 Report sent to Slack!" if ok else f"Slack: {msg}", icon="✅" if ok else "⚠️")

# ─────────────────────────────────────────────────────────────────────────────
# KPI ROW
# ─────────────────────────────────────────────────────────────────────────────
total = k["total_conversations"]
tc_pct = round(k["tc_conversations"]/total*100,1) if total else 0
mp_pct = round(k["mp_conversations"]/total*100,1) if total else 0
un_pct = round(k["unanswered"]/total*100,1)       if total else 0
ai_pct = round(k["tc_ai_replies"]/k["tc_conversations"]*100,1) if k["tc_conversations"] else 0

c1,c2,c3,c4,c5,c6,c7 = st.columns(7)
c1.metric("💬 Total Chats",    f"{total:,}")
c2.metric("✅ TC Handled",     f"{k['tc_conversations']:,}",  f"{tc_pct}%")
c3.metric("🏪 MP Replied",    f"{k['mp_conversations']:,}",  f"{mp_pct}%")
c4.metric("❌ Unanswered",     f"{k['unanswered']:,}",        f"{un_pct}%")
c5.metric("🤖 TC AI Replies",  f"{k['tc_ai_replies']:,}",    f"{ai_pct}% of TC")
c6.metric("👤 TC Seller",      f"{k['tc_seller_replies']:,}")
c7.metric("📊 TC+AI",          f"{k['tc_ai_replies']+k['tc_seller_replies']:,}")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# ROW 1 — Donut + Platform bar + TC type bar
# ─────────────────────────────────────────────────────────────────────────────
col_a, col_b, col_c = st.columns(3)

with col_a:
    st.markdown('<div class="section-title">Reply Source Breakdown</div>', unsafe_allow_html=True)
    pie_df = pd.DataFrame({
        "type":  ["TC AI Only","TC Seller","MP Replied","Unanswered"],
        "count": [k["tc_ai_replies"], k["tc_seller_replies"], k["mp_conversations"], k["unanswered"]]
    }).query("count > 0")
    st.altair_chart(
        alt.Chart(pie_df).mark_arc(innerRadius=55)
        .encode(theta="count:Q",
                color=alt.Color("type:N", scale=alt.Scale(
                    domain=["TC AI Only","TC Seller","MP Replied","Unanswered"],
                    range=["#a855f7","#f59e0b","#3b82f6","#ef4444"])),
                tooltip=["type:N","count:Q"])
        .properties(height=270),
        use_container_width=True
    )

with col_b:
    st.markdown('<div class="section-title">By Platform</div>', unsafe_allow_html=True)
    if "PLATFORM" in merged.columns:
        plat = merged.groupby("PLATFORM").agg(
            TC=("tc_handled","sum"), MP=("mp_replied","sum"), Unanswered=("unanswered","sum")
        ).reset_index().melt(id_vars="PLATFORM", var_name="type", value_name="count")
        st.altair_chart(
            alt.Chart(plat).mark_bar()
            .encode(x="PLATFORM:N", y="count:Q",
                    color=alt.Color("type:N", scale=alt.Scale(
                        domain=["TC","MP","Unanswered"], range=["#a855f7","#3b82f6","#ef4444"])),
                    tooltip=["PLATFORM:N","type:N","count:Q"])
            .properties(height=270),
            use_container_width=True
        )

with col_c:
    st.markdown('<div class="section-title">TC AI vs Seller</div>', unsafe_allow_html=True)
    tc_type = pd.DataFrame({
        "type":  ["AI Only","Seller Only","Both"],
        "count": [k["tc_ai_replies"], k["tc_seller_replies"],
                  k["tc_conversations"] - k["tc_ai_replies"] - k["tc_seller_replies"]]
    }).query("count > 0")
    st.altair_chart(
        alt.Chart(tc_type).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(x="type:N", y="count:Q",
                color=alt.Color("type:N", scale=alt.Scale(
                    domain=["AI Only","Seller Only","Both"],
                    range=["#a855f7","#f59e0b","#22c55e"])),
                tooltip=["type:N","count:Q"])
        .properties(height=270),
        use_container_width=True
    )

# ─────────────────────────────────────────────────────────────────────────────
# ROW 2 — Daily trend (filtered date range)
# ─────────────────────────────────────────────────────────────────────────────
if "MSG_DATE" in merged.columns and merged["MSG_DATE"].notna().any():
    st.markdown('<div class="section-title">📈 Daily Conversation Trend</div>', unsafe_allow_html=True)
    daily = merged.groupby("MSG_DATE").agg(
        TC=("tc_handled","sum"), MP=("mp_replied","sum"), Unanswered=("unanswered","sum")
    ).reset_index()
    daily["MSG_DATE"] = pd.to_datetime(daily["MSG_DATE"])
    daily_long = daily.melt(id_vars="MSG_DATE", var_name="type", value_name="count")
    st.altair_chart(
        alt.Chart(daily_long).mark_line(point=True)
        .encode(x=alt.X("MSG_DATE:T", title="Date", axis=alt.Axis(labelAngle=-35)),
                y=alt.Y("count:Q", title="Conversations"),
                color=alt.Color("type:N", scale=alt.Scale(
                    domain=["TC","MP","Unanswered"], range=["#a855f7","#3b82f6","#ef4444"])),
                tooltip=["MSG_DATE:T","type:N","count:Q"])
        .properties(height=280),
        use_container_width=True
    )

# ─────────────────────────────────────────────────────────────────────────────
# ROW 3 — Store performance
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
store_perf["tc_pct"]         = (store_perf["tc_conversations"]/store_perf["total_conversations"]*100).round(1)
store_perf["unanswered_pct"] = (store_perf["unanswered"]/store_perf["total_conversations"]*100).round(1)
store_perf = store_perf.sort_values("total_conversations", ascending=False)

col_l, col_r = st.columns([3,2])
with col_l:
    top12 = store_perf.head(12).melt(
        id_vars=["STORE_CODE","PLATFORM"],
        value_vars=["tc_conversations","mp_conversations","unanswered"],
        var_name="type", value_name="count"
    )
    top12["type"] = top12["type"].map({"tc_conversations":"TC","mp_conversations":"MP","unanswered":"Unanswered"})
    st.altair_chart(
        alt.Chart(top12).mark_bar()
        .encode(x=alt.X("count:Q", title="Conversations"),
                y=alt.Y("STORE_CODE:N", sort="-x"),
                color=alt.Color("type:N", scale=alt.Scale(
                    domain=["TC","MP","Unanswered"], range=["#a855f7","#3b82f6","#ef4444"])),
                tooltip=["STORE_CODE:N","PLATFORM:N","type:N","count:Q"])
        .properties(height=380),
        use_container_width=True
    )
with col_r:
    st.altair_chart(
        alt.Chart(store_perf.head(20)).mark_circle()
        .encode(x=alt.X("tc_pct:Q", title="TC Handled %", scale=alt.Scale(domain=[0,105])),
                y=alt.Y("unanswered_pct:Q", title="Unanswered %"),
                size=alt.Size("total_conversations:Q", scale=alt.Scale(range=[50,900])),
                color="PLATFORM:N",
                tooltip=["STORE_CODE:N","PLATFORM:N","total_conversations:Q","tc_pct:Q","unanswered_pct:Q"])
        .properties(title="TC% vs Unanswered% (bubble = volume)", height=380),
        use_container_width=True
    )

# ─────────────────────────────────────────────────────────────────────────────
# MONTHLY SUMMARY TABLE
# ─────────────────────────────────────────────────────────────────────────────
if "MSG_DATE" in merged.columns and merged["MSG_DATE"].notna().any():
    st.markdown('<div class="section-title">📅 Monthly Summary</div>', unsafe_allow_html=True)
    merged["month"] = pd.to_datetime(merged["MSG_DATE"], errors="coerce").dt.to_period("M").astype(str)
    monthly = merged.groupby("month").agg(
        Total=("CONVERSATION_ID","count"),
        TC=("tc_handled","sum"),
        MP=("mp_replied","sum"),
        Unanswered=("unanswered","sum"),
        TC_AI=("tc_ai_only","sum"),
        TC_Seller=("tc_human","sum"),
    ).reset_index()
    monthly["TC%"] = (monthly["TC"]/monthly["Total"]*100).round(1)
    monthly["Unanswered%"] = (monthly["Unanswered"]/monthly["Total"]*100).round(1)
    st.dataframe(monthly, use_container_width=True, hide_index=True)

# ─────────────────────────────────────────────────────────────────────────────
# STORE DETAIL TABLE
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">📋 Store Detail Table</div>', unsafe_allow_html=True)
disp = store_perf.copy()
disp.columns = [c.replace("_"," ").title() for c in disp.columns]
st.dataframe(disp, use_container_width=True, height=300, hide_index=True)

# ─────────────────────────────────────────────────────────────────────────────
# DOWNLOADS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
d1, d2 = st.columns(2)
with d1:
    st.download_button("⬇️ Store Performance CSV",
                       store_perf.to_csv(index=False).encode(), "store_performance.csv", "text/csv")
with d2:
    detail_cols = ["CONVERSATION_ID","STORE_CODE","PLATFORM","platform_replied",
                   "tc_handled","mp_replied","unanswered","tc_ai_only","tc_human"]
    detail_cols = [c for c in detail_cols if c in merged.columns]
    st.download_button("⬇️ Conversation Detail CSV",
                       merged[detail_cols].to_csv(index=False).encode(), "conversation_detail.csv", "text/csv")

# ─────────────────────────────────────────────────────────────────────────────
# MANUAL SLACK SEND
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("### 📤 Send Report to Slack")
sc1, sc2 = st.columns([3,1])
with sc1:
    st.caption(f"Posts to `{slack_channel}` (#automation-jira-test) · filtered period: {date_from or 'all'} → {date_to or 'all'}")
with sc2:
    if st.button("Send Now 🚀", type="primary", use_container_width=True):
        if not slack_token:
            st.error("Add Slack Bot Token in sidebar.")
        else:
            with st.spinner("Sending…"):
                ok, msg = send_slack_report(
                    summary, store_perf.head(8), slack_token, slack_channel,
                    date_from or "all", date_to or "all"
                )
            st.success("✅ Sent to #automation-jira-test!") if ok else st.error(f"Failed: {msg}")
