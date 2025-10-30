# 🪙 SafiHash — Hedera-Powered Co-operative Finance Demo

## 🎯 Goal

Show how community lending groups can run safely and transparently using Hedera Hashgraph services.  
Judges can experience how the **Trust Score** tracks deposits, loans, repayments, and voting — making group finance reliable, tamper-proof, and fair.

---

## 🌍 Overview

**SafiHash** is a community-lending and cooperative-finance platform built on **Hedera Hashgraph**.  
It uses:

- 🗂 **HFS** – for storing KYC file hashes (tamper-proof)
- 💰 **HTS (BHC Token)** – for all deposits, withdrawals, and repayments
- ⚙️ **Smart Contracts** – for on-chain Trust Score logic
- 💬 **Consensus Service (HCS)** – for auditable transaction ordering
- 🤖 **AI-based Assistant** – chat interface for all group operations

It also includes an **Offline Transaction & Retry System** that safely re-processes failed transfers, guaranteeing reliability even when the Hedera network or internet temporarily fails.

🔗 **Live backend:** [https://safihash.onrender.com](https://safihash.onrender.com)

---

## 🧠 Key Features

| Feature                     | Description                                                  |
| --------------------------- | ------------------------------------------------------------ |
| 🧾 Auto & Manual KYC        | Demo mode = Auto-KYC (instant). Production = Admin-approved. |
| 💸 Tokenized Finance        | All group transactions use BHC (Hedera Token Service).       |
| 🔒 On-Chain Trust Score     | Smart contract records and updates user reliability metrics. |
| 🗳 Group Voting & Loan Logic | Fully transparent loan approvals and repayments.             |
| 📡 Offline Retry System     | Queues pending on-chain actions until network recovers.      |

---

## ⚙️ Tech Stack

**Backend:** Flask (3.1.1), Flask-JWT-Extended, Flask-SQLAlchemy, Flask-Migrate  
**Blockchain SDKs:** Hedera-SDK-Py 2.50.0, Web3 7.13.0  
**Frontend:** HTML + Bootstrap + JS (Chat UI + Dashboard)  
**Database:** SQLite (embedded demo)  
**Deployment:** Docker on Render  
**Scheduler:** APScheduler (for retries, cron jobs)

---

## 📂 Project Structure

```plaintext
safihash/
│
├── app.py                        # Flask entrypoint
├── config.py / extensions.py
├── requirements.txt / Dockerfile / Procfile
│
├── ai_engine/                    # Chatbot, KYC verifier, fraud detector, etc.
├── cooperative/                  # Group lending logic (models + routes)
├── finance/                      # Loan, voting, wallet & rewards
├── hedera_sdk/                   # HTS, HFS, HCS, Smart-Contract utilities
├── middleware/                   # Alerts, error handler, offline retry
├── notifications/, payments/, savings/, security/
├── templates/ & static/           # Frontend (chatbot.html, dashboards)
│
├── instance/safichain.db          # Demo DB (test data only)
└── frontend/                      # Optional React/JS build (if used)
```

---

⚠️ **Note:** Modules like `company`, `ngo`, and `user_dashboard` exist for future expansion and are not active in this demo version.

---

## 🔐 Environment Variables

Below are the keys required for Render or local `.env` setup
(Use dummy/test values for offline runs — no private keys should be shared):

| Key                                                                   | Purpose                                |
| --------------------------------------------------------------------- | -------------------------------------- |
| SECRET_KEY, JWT_SECRET_KEY                                            | Flask session + JWT auth               |
| HEDERA_OPERATOR_ID, HEDERA_OPERATOR_KEY, HEDERA_PUBLIC_KEY            | Operator account (Testnet)             |
| HEDERA_NETWORK                                                        | Set to testnet                         |
| BHC_TOKEN_ID, BHC_TOKEN_EVM, BHC_DECIMALS                             | Demo token details                     |
| VAULT_EVM                                                             | Co-op group vault address              |
| COOPTRUST_CONTRACT                                                    | Smart contract address for Trust Score |
| KYC_NFT_ID                                                            | NFT used for KYC proof                 |
| ENABLE_HEDERA                                                         | Toggle Hedera integration (on/off)     |
| MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET, MPESA_SHORTCODE, MPESA_ENV | M-Pesa sandbox keys                    |
| PRODUCTION                                                            | false → testnet mode                   |

🧩 **All environment variables are already configured in Render.**

---

## 🧰 Setup & Run (Locally)

```bash
# 1️⃣ Clone the repository
git clone https://github.com/amritasinhaclickify/safiHash.git
cd safihash

# 2️⃣ Create a virtual environment
python -m venv venv
venv\Scripts\activate   # Windows
# or
source venv/bin/activate   # Mac/Linux

# 3️⃣ Install dependencies
pip install -r requirements.txt

# 4️⃣ Create a .env file
# (copy from .env.example and add your Hedera/M-Pesa test keys)

# 5️⃣ Run the app
flask run
# or
python app.py

📍 Default server: http://127.0.0.1:5000
---

Ye block GitHub par bilkul aligned aur readable dikhega — tables, emojis aur code blocks sab proper Markdown me render honge 💎
```

---

## 🐳 Deployment on Render

Render automatically builds from the **Dockerfile**.
No extra commands are required.

```bash
CMD gunicorn -w 1 -b 0.0.0.0:$PORT app:app

✅ Expose port: handled automatically via $PORT
✅ Environment variables: injected in Render settings (see table above)
```

## 🧪 Judge Testing Guide

### 🧍 Pre-Verified Accounts (Auto-KYC Enabled)

Use any of these logins (already verified):

testuser01@example.com / testuser01
testuser02@example.com / testuser02
testuser03@example.com / testuser03
testuser04@example.com / testuser04
testuser05@example.com / testuser05
testuser06@example.com / testuser06
testuser07@example.com / testuser07
testuser08@example.com / testuser08
testuser09@example.com / testuser09
testuser10@example.com / testuser10

### ✅ Quick Demo Flow

Login → any test user

Check wallet:
`wallet`

Create group:
`create group Farmers Union interest 0.1 minbalance 50 profit_reserve 10`

Deposit funds:
`deposit 100 bhc farmers-union-123abc`

Request loan:
`loan farmers-union-123abc 30 seeds purchase`

Vote / Approve / Repay:
`vote 7 yes`
`repay 7 30`

View Trust Score:
`trustscore me`

💬 The chatbot interface automatically connects to the **Render backend**.

## 🧮 Trust Score Logic (On-Chain)

Smart contract rules combine:
**Deposits 📈 + Repayments ⏱ + Voting 🗳 + Consistency 🧭 + Profit Share 💰**
to calculate a transparent, auditable **Trust Score** for every member.

Admins can sync on-chain scores via:

push trustscore <user_id> <group_slug>

## 🧾 Offline Transaction & Retry System

If **Hedera** or the **internet** goes offline, every pending action
(e.g., deposit, repayment, or M-Pesa call) is **queued in an Outbox**.

A background scheduler automatically retries failed transactions until confirmed.
✅ **No payment or audit event is ever lost.**

## 🧩 Troubleshooting

| Issue                       | Solution                                        |
| --------------------------- | ----------------------------------------------- |
| HTS transfer fails          | Ensure enough HBAR for fees & token association |
| KYC hash mismatch           | Re-upload file and verify hash                  |
| 3rd-party repayment pending | Admin approves via `approve payment <id>`       |

## 🧱 For AI Judging & Repo Analysis

This repository is **public** and freshly created for the hackathon.

✅ `Hackathon@hashgraph-association.com` has been added as a collaborator.
🔒 `.env` and private keys are excluded from the repo.
🧩 `safichain.db` includes only **test/demo data**.
📁 Unused modules: `company`, `ngo`, and `user_dashboard` – safe to ignore.
🌐 Frontend automatically connects to the Render backend: [https://safihash.onrender.com](https://safihash.onrender.com).

Judges can **run locally** or **directly test the online version**.

## 🎥 Pitch Deck & Certification

- [🎞️ Pitch Deck (Google Slides)](https://drive.google.com/your-pitch-link)
- [📄 Hashgraph Developer Certification (Google Drive PDF)](https://drive.google.com/file/d/1CnBRK_EjlyB5Xkr7vW1l9C1qTq_Pqemq/view?usp=sharing)

## 🏁 Credits & License

Developed by **Amrita Sinha**
for the **Hedera × DoraHacks Hackathon 2025**

📜 Licensed under **MIT** (for educational/demo use)
© 2025 Amrita Sinha. All rights reserved.

```

```
