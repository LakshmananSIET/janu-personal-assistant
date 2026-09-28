# Janu application

Run locally:

```bash
python -m uvicorn app.main:app --reload
```

Then open:

http://127.0.0.1:8000

This version provides a browser voice loop:
1. Browser listens to Lakshman's speech.
2. Transcript is sent to FastAPI.
3. Janu generates a temporary response.
4. Browser speaks the response.

The response layer is intentionally local for now. AI credentials will be added later as environment variables, never committed to GitHub.
