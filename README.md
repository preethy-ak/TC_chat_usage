# Graas · TC Chat Dashboard

> TC Replies vs MP Replies · 22 Merchants · Streamlit + Plotly

---

## 🚀 Deploy to Streamlit Cloud

### Step 1 — Push to GitHub
```
graas_tc_dashboard/
├── app.py
├── requirements.txt
├── .streamlit/
│   └── config.toml
└── README.md
```

1. Create a new GitHub repo (e.g. `graas-tc-dashboard`)
2. Push these 4 files to the repo

### Step 2 — Deploy on Streamlit Cloud
1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Click **New app**
3. Select your GitHub repo
4. Set **Main file path** → `app.py`
5. Click **Deploy**

Done — your app is live in ~2 minutes.

---

## 💻 Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## 📂 How to use
1. Run the 90-day query in Superset
2. Export as CSV
3. Upload in the sidebar
4. Filter by merchant, date range, granularity

---

## 📊 Dashboard tabs
| Tab | Content |
|-----|---------|
| 📈 Trends | TC vs MP vs Buyer over time · Coverage % · Monthly |
| 🏪 By Merchant | Stacked bar · TC% bar · Bubble chart |
| 📊 Breakdown | Reply donut · Card types · TC ramp-up per merchant |
| 📋 Data Table | Merchant summary with progress bar · Raw daily data |

---

## 🔑 Expected CSV columns
```
MERCHANT_ID, DATE, BUYER_MESSAGE_COUNT, MP_REPLY_COUNT,
TC_REPLY_COUNT, AUTO_REPLY_COUNT, ORDER_CARD_COUNT,
LOGISTICS_CARD_COUNT, RETURN_CARD_COUNT
```
