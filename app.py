import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px


# ── Page config ────────────────────────────────────────────────────
st.set_page_config(
    page_title="Graas · TC Chat Dashboard",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Graas Blue Theme ───────────────────────────────────────────────
BLUE_PRIMARY   = "#1D4ED8"
BLUE_LIGHT     = "#3B82F6"
BLUE_BRIGHT    = "#60A5FA"
BLUE_PALE      = "#DBEAFE"
BG_DARK        = "#0F172A"
BG_CARD        = "#1E293B"
BG_CARD2       = "#162032"
TEXT_PRIMARY   = "#F1F5F9"
TEXT_SECONDARY = "#94A3B8"
TEXT_DIM       = "#475569"
TEAL           = "#0EA5E9"
GREEN          = "#22C55E"
AMBER          = "#F59E0B"
RED            = "#EF4444"

st.markdown(f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

  html, body, [class*="css"] {{
      font-family: 'Inter', sans-serif;
      background-color: {BG_DARK};
      color: {TEXT_PRIMARY};
  }}
  .block-container {{ padding: 1.5rem 2rem 2rem; max-width: 100%; }}
  .stApp {{ background-color: {BG_DARK}; }}

  /* Sidebar */
  section[data-testid="stSidebar"] {{
      background-color: {BG_CARD} !important;
      border-right: 1px solid #1e3a5f;
  }}
  section[data-testid="stSidebar"] * {{ color: {TEXT_PRIMARY} !important; }}

  /* Metric cards */
  div[data-testid="metric-container"] {{
      background: {BG_CARD};
      border: 1px solid #1e3a5f;
      border-radius: 10px;
      padding: 16px 18px;
      border-left: 3px solid {BLUE_PRIMARY};
  }}
  div[data-testid="metric-container"] label {{
      color: {TEXT_SECONDARY} !important;
      font-size: 11px !important;
      text-transform: uppercase;
      letter-spacing: 0.06em;
  }}
  div[data-testid="metric-container"] [data-testid="stMetricValue"] {{
      color: {BLUE_BRIGHT} !important;
      font-size: 26px !important;
      font-weight: 700 !important;
  }}
  div[data-testid="metric-container"] [data-testid="stMetricDelta"] {{
      font-size: 11px !important;
  }}

  /* Headers */
  h1 {{ color: {TEXT_PRIMARY} !important; font-size: 22px !important; font-weight: 700 !important; }}
  h2 {{ color: {TEXT_PRIMARY} !important; font-size: 17px !important; font-weight: 600 !important; }}
  h3 {{ color: {TEXT_SECONDARY} !important; font-size: 13px !important; font-weight: 600 !important;
        text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 0 !important; }}

  /* Upload widget */
  div[data-testid="stFileUploader"] {{
      background: {BG_CARD};
      border: 2px dashed {BLUE_PRIMARY};
      border-radius: 10px;
      padding: 16px;
  }}
  div[data-testid="stFileUploader"] label {{ color: {TEXT_PRIMARY} !important; font-weight: 600; }}

  /* Selectbox / slider */
  div[data-baseweb="select"] div {{
      background: {BG_CARD2} !important;
      border-color: #1e3a5f !important;
      color: {TEXT_PRIMARY} !important;
  }}
  div[data-testid="stSlider"] {{ color: {TEXT_PRIMARY}; }}

  /* Dataframe */
  div[data-testid="stDataFrame"] {{ border-radius: 8px; overflow: hidden; }}
  iframe {{ border-radius: 8px; }}

  /* Divider */
  hr {{ border-color: #1e3a5f; margin: 1rem 0; }}

  /* Tabs */
  div[data-testid="stTabs"] button {{
      color: {TEXT_SECONDARY} !important;
      border-bottom-color: transparent !important;
      font-weight: 500;
  }}
  div[data-testid="stTabs"] button[aria-selected="true"] {{
      color: {BLUE_BRIGHT} !important;
      border-bottom-color: {BLUE_PRIMARY} !important;
  }}

  /* Scrollbar */
  ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
  ::-webkit-scrollbar-track {{ background: {BG_DARK}; }}
  ::-webkit-scrollbar-thumb {{ background: #1e3a5f; border-radius: 3px; }}
  ::-webkit-scrollbar-thumb:hover {{ background: {BLUE_PRIMARY}; }}
</style>
""", unsafe_allow_html=True)

# ── Chart defaults ─────────────────────────────────────────────────
CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor=BG_CARD2,
    font=dict(family="Inter", color=TEXT_SECONDARY, size=11),
    margin=dict(l=10, r=10, t=30, b=10),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
    xaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", tickfont=dict(size=10)),
    yaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", tickfont=dict(size=10)),
)

def apply_layout(fig, title="", height=300):
    fig.update_layout(**CHART_LAYOUT, title=dict(text=title, font=dict(size=12, color=TEXT_SECONDARY)), height=height)
    return fig

# ── Helpers ────────────────────────────────────────────────────────
def pct_color(p):
    if p >= 5:   return GREEN
    if p >= 1:   return AMBER
    if p > 0:    return RED
    return TEXT_DIM

def status_badge(p):
    if p >= 5:   return "🟢 On track"
    if p >= 1:   return "🟡 Early stage"
    if p > 0:    return "🔴 Just started"
    return "⚫ Not started"

# ── Sidebar ────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://cdn.prod.website-files.com/686deb6985e5956707d1d644/687494049c704d26a946e7e2_image-6.png",
             width=130)
    st.markdown("### TC Chat Dashboard")
    st.markdown(f"<p style='color:{TEXT_DIM};font-size:11px'>TC vs MP Seller Replies Analytics</p>", unsafe_allow_html=True)
    st.divider()

    uploaded = st.file_uploader(
        "Upload Snowflake CSV",
        type=["csv"],
        help="Export from Superset using the 90-day TC query"
    )
    st.divider()

    st.markdown(f"<p style='color:{TEXT_SECONDARY};font-size:11px;font-weight:600'>FILTERS</p>", unsafe_allow_html=True)
    period    = st.selectbox("Period", ["Last 90 days", "Last 30 days", "Last 7 days"], index=0)
    gran      = st.selectbox("Granularity", ["Daily", "Weekly", "Monthly"], index=0)
    st.divider()
    st.markdown(f"<p style='color:{TEXT_DIM};font-size:10px'>Columns expected:<br>MERCHANT_ID, DATE,<br>BUYER_MESSAGE_COUNT,<br>MP_REPLY_COUNT,<br>TC_REPLY_COUNT,<br>AUTO_REPLY_COUNT,<br>ORDER_CARD_COUNT,<br>LOGISTICS_CARD_COUNT,<br>RETURN_CARD_COUNT</p>", unsafe_allow_html=True)

# ── Load data ──────────────────────────────────────────────────────
@st.cache_data
def load(file):
    df = pd.read_csv(file)
    df.columns = [c.upper().strip() for c in df.columns]
    df["DATE"] = pd.to_datetime(df["DATE"])
    num_cols = ["BUYER_MESSAGE_COUNT","MP_REPLY_COUNT","TC_REPLY_COUNT",
                "AUTO_REPLY_COUNT","ORDER_CARD_COUNT","LOGISTICS_CARD_COUNT","RETURN_CARD_COUNT"]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    return df

# ── Main ───────────────────────────────────────────────────────────
st.markdown("## 💬 TC Chat · Seller Reply Dashboard")
st.markdown(f"<p style='color:{TEXT_DIM};font-size:12px;margin-top:-8px'>TC Replies vs MP Replies vs Buyer Messages · All 22 Merchants</p>", unsafe_allow_html=True)

if uploaded is None:
    st.markdown(f"""
    <div style='background:{BG_CARD};border:1px solid #1e3a5f;border-radius:10px;padding:40px;text-align:center;margin-top:20px'>
        <div style='font-size:40px;margin-bottom:12px'>📂</div>
        <div style='font-size:16px;font-weight:600;color:{TEXT_PRIMARY};margin-bottom:8px'>Upload your Snowflake CSV</div>
        <div style='font-size:12px;color:{TEXT_DIM}'>Run the 90-day TC query in Superset → Export → Upload here</div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

df = load(uploaded)

# ── Date filter ────────────────────────────────────────────────────
days_map = {"Last 90 days": 90, "Last 30 days": 30, "Last 7 days": 7}
cutoff = pd.Timestamp.now() - pd.Timedelta(days=days_map[period])
df_f = df[df["DATE"] >= cutoff].copy()

# ── Merchant filter ────────────────────────────────────────────────
merchants = sorted(df["MERCHANT_ID"].unique())
sel_merchant = st.sidebar.multiselect("Merchants", merchants, default=merchants)
df_f = df_f[df_f["MERCHANT_ID"].isin(sel_merchant)]

# ── Granularity ────────────────────────────────────────────────────
if gran == "Weekly":
    df_f["PERIOD"] = df_f["DATE"].dt.to_period("W").dt.to_timestamp()
elif gran == "Monthly":
    df_f["PERIOD"] = df_f["DATE"].dt.to_period("M").dt.to_timestamp()
else:
    df_f["PERIOD"] = df_f["DATE"]

grouped = df_f.groupby("PERIOD").agg(
    buyer=("BUYER_MESSAGE_COUNT","sum"),
    mp=("MP_REPLY_COUNT","sum"),
    tc=("TC_REPLY_COUNT","sum"),
    auto=("AUTO_REPLY_COUNT","sum"),
    order=("ORDER_CARD_COUNT","sum"),
    logistics=("LOGISTICS_CARD_COUNT","sum"),
    ret=("RETURN_CARD_COUNT","sum"),
).reset_index().sort_values("PERIOD")

total_buyer  = int(df_f["BUYER_MESSAGE_COUNT"].sum())
total_mp     = int(df_f["MP_REPLY_COUNT"].sum())
total_tc     = int(df_f["TC_REPLY_COUNT"].sum())
total_auto   = int(df_f["AUTO_REPLY_COUNT"].sum())
total_seller = total_mp + total_tc
tc_pct       = round(total_tc / total_seller * 100, 1) if total_seller else 0
mp_pct       = round(total_mp / total_seller * 100, 1) if total_seller else 0

# ── KPI Cards ──────────────────────────────────────────────────────
st.divider()
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Buyer Messages",     f"{total_buyer:,}")
c2.metric("Total Seller Replies", f"{total_seller:,}", "MP + TC")
c3.metric("MP Replies",         f"{total_mp:,}",    f"{mp_pct}% of replies")
c4.metric("TC Replies",         f"{total_tc:,}",    f"{tc_pct}% of replies")
c5.metric("Auto Replies",       f"{total_auto:,}",  "platform-generated")
c6.metric("TC Coverage",        f"{tc_pct}%",       "TC ÷ (TC+MP)")
st.divider()

# ── Tabs ───────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["📈 Trends", "🏪 By Merchant", "📊 Breakdown", "📋 Data Table"])

# ── TAB 1: Trends ──────────────────────────────────────────────────
with tab1:
    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("### TC Replies vs MP Replies vs Buyer Messages")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=grouped["PERIOD"], y=grouped["buyer"], name="Buyer Messages",
            line=dict(color="#64748B", width=1.5), fill="tozeroy", fillcolor="rgba(100,116,139,0.08)"))
        fig.add_trace(go.Scatter(x=grouped["PERIOD"], y=grouped["mp"], name="MP Replies",
            line=dict(color=BLUE_LIGHT, width=2), fill="tozeroy", fillcolor=f"rgba(59,130,246,0.1)"))
        fig.add_trace(go.Scatter(x=grouped["PERIOD"], y=grouped["tc"], name="TC Replies",
            line=dict(color=TEAL, width=2.5), fill="tozeroy", fillcolor="rgba(14,165,233,0.15)"))
        apply_layout(fig, height=320)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("### TC Coverage % Trend")
        grouped["tc_pct"] = (grouped["tc"] / (grouped["mp"] + grouped["tc"]).replace(0, 1) * 100).round(1)
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=grouped["PERIOD"], y=grouped["tc_pct"], name="TC %",
            line=dict(color=BLUE_BRIGHT, width=2.5), fill="tozeroy",
            fillcolor=f"rgba(96,165,250,0.15)", mode="lines"))
        fig2.add_hline(y=5, line_dash="dot", line_color=GREEN, annotation_text="5% target",
                       annotation_font_size=10, annotation_font_color=GREEN)
        apply_layout(fig2, height=320)
        fig2.update_yaxes(ticksuffix="%")
        st.plotly_chart(fig2, use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("### Auto-Reply vs TC Reply")
        fig3 = go.Figure()
        fig3.add_trace(go.Bar(x=grouped["PERIOD"], y=grouped["auto"], name="Auto Replies",
            marker_color="#334155"))
        fig3.add_trace(go.Bar(x=grouped["PERIOD"], y=grouped["tc"], name="TC Replies",
            marker_color=BLUE_LIGHT))
        apply_layout(fig3, height=280)
        fig3.update_layout(barmode="group")
        st.plotly_chart(fig3, use_container_width=True)

    with col4:
        st.markdown("### Monthly MP vs TC (all time)")
        df_mo = df[df["MERCHANT_ID"].isin(sel_merchant)].copy()
        df_mo["MONTH"] = df_mo["DATE"].dt.to_period("M").astype(str)
        mo_grp = df_mo.groupby("MONTH").agg(mp=("MP_REPLY_COUNT","sum"), tc=("TC_REPLY_COUNT","sum")).reset_index()
        fig4 = go.Figure()
        fig4.add_trace(go.Bar(x=mo_grp["MONTH"], y=mo_grp["mp"], name="MP", marker_color=BLUE_PRIMARY))
        fig4.add_trace(go.Bar(x=mo_grp["MONTH"], y=mo_grp["tc"], name="TC", marker_color=TEAL))
        apply_layout(fig4, height=280)
        fig4.update_layout(barmode="group")
        st.plotly_chart(fig4, use_container_width=True)

# ── TAB 2: By Merchant ────────────────────────────────────────────
with tab2:
    m_grp = df_f.groupby("MERCHANT_ID").agg(
        buyer=("BUYER_MESSAGE_COUNT","sum"),
        mp=("MP_REPLY_COUNT","sum"),
        tc=("TC_REPLY_COUNT","sum"),
        auto=("AUTO_REPLY_COUNT","sum"),
    ).reset_index()
    m_grp["total"] = m_grp["mp"] + m_grp["tc"]
    m_grp["tc_pct"] = (m_grp["tc"] / m_grp["total"].replace(0,1) * 100).round(1)
    m_grp = m_grp.sort_values("tc_pct", ascending=False)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### TC vs MP Replies by Merchant")
        fig5 = go.Figure()
        fig5.add_trace(go.Bar(y=m_grp["MERCHANT_ID"], x=m_grp["mp"], name="MP Replies",
            orientation="h", marker_color=BLUE_PRIMARY))
        fig5.add_trace(go.Bar(y=m_grp["MERCHANT_ID"], x=m_grp["tc"], name="TC Replies",
            orientation="h", marker_color=TEAL))
        apply_layout(fig5, height=500)
        fig5.update_layout(barmode="stack",
            yaxis=dict(gridcolor="#1e3a5f", tickfont=dict(size=10)),
            xaxis=dict(gridcolor="#1e3a5f"))
        st.plotly_chart(fig5, use_container_width=True)

    with col2:
        st.markdown("### TC Coverage % by Merchant")
        colors = [GREEN if p>=5 else AMBER if p>=1 else RED if p>0 else TEXT_DIM
                  for p in m_grp["tc_pct"]]
        fig6 = go.Figure()
        fig6.add_trace(go.Bar(y=m_grp["MERCHANT_ID"], x=m_grp["tc_pct"], orientation="h",
            marker_color=colors, text=m_grp["tc_pct"].astype(str)+"%",
            textposition="outside", textfont=dict(size=10, color=TEXT_SECONDARY)))
        fig6.add_vline(x=5, line_dash="dot", line_color=GREEN,
                       annotation_text="5% target", annotation_font_color=GREEN, annotation_font_size=10)
        apply_layout(fig6, height=500)
        fig6.update_xaxes(ticksuffix="%")
        fig6.update_yaxes(gridcolor="#1e3a5f")
        st.plotly_chart(fig6, use_container_width=True)

    # Buyer volume bubble
    st.markdown("### Buyer Volume vs TC Coverage (bubble = total seller replies)")
    fig7 = px.scatter(m_grp, x="buyer", y="tc_pct", size="total", color="tc_pct",
        text="MERCHANT_ID", color_continuous_scale=[[0,"#EF4444"],[0.3,"#F59E0B"],[1,"#22C55E"]],
        size_max=60)
    fig7.update_traces(textposition="top center", textfont=dict(size=10, color=TEXT_SECONDARY))
    apply_layout(fig7, height=360)
    fig7.update_yaxes(ticksuffix="%", title="TC Coverage %")
    fig7.update_xaxes(title="Buyer Messages")
    fig7.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig7, use_container_width=True)

# ── TAB 3: Breakdown ─────────────────────────────────────────────
with tab3:
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Reply type distribution")
        labels = ["MP Replies", "TC Replies", "Auto Replies"]
        values = [total_mp, total_tc, total_auto]
        colors_pie = [BLUE_PRIMARY, TEAL, "#334155"]
        fig8 = go.Figure(go.Pie(labels=labels, values=values, hole=0.55,
            marker=dict(colors=colors_pie, line=dict(color=BG_DARK, width=2)),
            textfont=dict(size=11)))
        fig8.update_layout(**CHART_LAYOUT, height=300,
            annotations=[dict(text=f"Total<br>{total_seller:,}", x=0.5, y=0.5,
                             font=dict(size=13, color=TEXT_PRIMARY), showarrow=False)])
        st.plotly_chart(fig8, use_container_width=True)

    with col2:
        st.markdown("### Buyer message card types (period total)")
        card_vals = [
            df_f["ORDER_CARD_COUNT"].sum(),
            df_f["LOGISTICS_CARD_COUNT"].sum(),
            df_f["RETURN_CARD_COUNT"].sum(),
            total_buyer - df_f["ORDER_CARD_COUNT"].sum() - df_f["LOGISTICS_CARD_COUNT"].sum() - df_f["RETURN_CARD_COUNT"].sum(),
        ]
        card_lbls = ["Order cards", "Logistics cards", "Return cards", "Text/Media"]
        card_cols = [BLUE_LIGHT, BLUE_BRIGHT, "#818CF8", "#334155"]
        fig9 = go.Figure(go.Bar(x=card_lbls, y=card_vals, marker_color=card_cols,
            text=[f"{v:,}" for v in card_vals], textposition="outside",
            textfont=dict(size=10, color=TEXT_SECONDARY)))
        apply_layout(fig9, height=300)
        st.plotly_chart(fig9, use_container_width=True)

    # TC ramp per merchant (line per merchant, Jun only)
    st.markdown("### TC ramp-up — daily TC replies per merchant (Jun 2026)")
    df_jun = df[df["MERCHANT_ID"].isin(sel_merchant) & (df["DATE"] >= "2026-06-01")].copy()
    fig10 = go.Figure()
    blues = [BLUE_BRIGHT, TEAL, BLUE_LIGHT, "#818CF8", "#38BDF8", "#7DD3FC",
             "#BAE6FD", "#E0F2FE", "#1D4ED8", "#2563EB", "#3B82F6", "#60A5FA"]
    tc_merchants = df_jun.groupby("MERCHANT_ID")["TC_REPLY_COUNT"].sum()
    active = tc_merchants[tc_merchants>0].sort_values(ascending=False).index.tolist()
    for i, m in enumerate(active):
        mdf = df_jun[df_jun["MERCHANT_ID"]==m].sort_values("DATE")
        fig10.add_trace(go.Scatter(x=mdf["DATE"], y=mdf["TC_REPLY_COUNT"], name=m,
            line=dict(color=blues[i % len(blues)], width=2), mode="lines+markers",
            marker=dict(size=5)))
    apply_layout(fig10, height=320)
    st.plotly_chart(fig10, use_container_width=True)

# ── TAB 4: Data Table ────────────────────────────────────────────
with tab4:
    # Summary per merchant
    all_m = df[df["MERCHANT_ID"].isin(sel_merchant)].groupby("MERCHANT_ID").agg(
        Buyer_Msgs=("BUYER_MESSAGE_COUNT","sum"),
        MP_Replies=("MP_REPLY_COUNT","sum"),
        TC_Replies=("TC_REPLY_COUNT","sum"),
        Auto_Replies=("AUTO_REPLY_COUNT","sum"),
        Order_Cards=("ORDER_CARD_COUNT","sum"),
        Logistics=("LOGISTICS_CARD_COUNT","sum"),
        Returns=("RETURN_CARD_COUNT","sum"),
    ).reset_index()
    all_m["Total_Seller_Replies"] = all_m["MP_Replies"] + all_m["TC_Replies"]
    all_m["TC_%"] = (all_m["TC_Replies"] / all_m["Total_Seller_Replies"].replace(0,1) * 100).round(1)

    # TC start date from full data
    tc_start = df[df["TC_REPLY_COUNT"]>0].groupby("MERCHANT_ID")["DATE"].min().dt.strftime("%Y-%m-%d")
    all_m["TC_Started"] = all_m["MERCHANT_ID"].map(tc_start).fillna("Not started")
    all_m["Status"] = all_m["TC_%"].apply(status_badge)

    all_m = all_m.sort_values("TC_%", ascending=False).rename(columns={"MERCHANT_ID":"Merchant"})

    st.markdown("### Merchant Summary — Full Period")
    st.dataframe(
        all_m[["Merchant","Buyer_Msgs","MP_Replies","TC_Replies","Auto_Replies",
               "Total_Seller_Replies","TC_%","Order_Cards","Logistics","Returns","TC_Started","Status"]],
        use_container_width=True,
        height=500,
        column_config={
            "TC_%": st.column_config.ProgressColumn("TC %", min_value=0, max_value=100, format="%.1f%%"),
            "Merchant": st.column_config.TextColumn("Merchant", width="small"),
            "Status": st.column_config.TextColumn("Status", width="medium"),
        }
    )

    st.divider()
    st.markdown("### Raw daily data")
    show_df = df_f.rename(columns={
        "MERCHANT_ID":"Merchant","DATE":"Date",
        "BUYER_MESSAGE_COUNT":"Buyer","MP_REPLY_COUNT":"MP Reply",
        "TC_REPLY_COUNT":"TC Reply","AUTO_REPLY_COUNT":"Auto",
        "ORDER_CARD_COUNT":"Orders","LOGISTICS_CARD_COUNT":"Logistics","RETURN_CARD_COUNT":"Returns"
    })
    st.dataframe(show_df.drop(columns=["PERIOD"] if "PERIOD" in show_df.columns else []),
                 use_container_width=True, height=400)
