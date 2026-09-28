# Janu Personal Assistant

Janu is Lakshman's personal browser-based voice assistant.

## Current trial

- Continuous browser voice conversation: listen → think → speak → listen.
- Session conversation memory so follow-up messages can refer to earlier messages.
- Natural task extraction with dates and deadlines.
- Pending-task listing and task completion.
- Local Excel storage for trial tasks.
- FastAPI backend.
- GitHub Actions syntax/tests on every push and pull request.

## Run locally

1. Create a Python 3.11 virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and add your API key locally if using AI.
4. Start: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
5. Open the site from a browser.

For the no-API-key trial, Janu can still use the local fallback parser.

## Data and secrets

Trial task data is written to `data/janu_trial_tasks.xlsx` and is ignored by Git.
Never commit API keys, passwords, phone numbers, tokens, or live personal data.

## Roadmap

1. Calendar and reminder scheduling
2. Email integration
3. Files and database tools
4. Better browser/mobile voice with a dedicated speech service
5. Optional outbound phone-call integration
