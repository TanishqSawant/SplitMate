# SplitMate
SplitMate is an AI-powered group expense management platform that extracts bill details using AI, simplifies expense splitting among friends, and enables seamless payments through PayPal.

## Team Responsibilities (PayPal AI Hackathon 2026)
- **Tanishq**: FastAPI backend, database models, and balance ledger.
- **Pawan**: AI receipt extraction (computer vision OCR & line items).
- **Dhruv**: React frontend development and UI/UX design.
- **Tanay**: PayPal Sandbox integration (order creation & capture).
- **Sunil**: Testing, integration, documentation, and demo.

## Project Structure
```
SplitMate/
├── frontend/          # React 19 + Vite + Tailwind CSS (Dhruv)
│   ├── src/
│   │   ├── api/       # API client service & endpoint contracts
│   │   ├── components/# Modular fintech & receipt splitting UI
│   │   ├── context/   # Auth, Expense, and Theme state
│   │   └── views/     # Dashboard, AI Scanner, Groups, PayPal, Analytics
│   └── README.md      # Frontend setup and integration guide
└── backend/           # FastAPI backend (Tanishq)
```

## Running Frontend
```bash
cd frontend
npm install
npm run dev
```
Runs at `http://localhost:3000`.
