# ATS Resume Parser Demo

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Then open http://127.0.0.1:8000

The parser is intentionally heuristic and local. It is a demo of ATS-like extraction, not a reproduction of any proprietary ATS.
