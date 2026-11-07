# Chronoops — Incident Intelligence

Chronoops is a Flask incident response workspace with persistent SQLite memory, evidence-grounded investigation, TF-IDF similarity retrieval, runbooks, replay timelines and post-mortems.

## Run locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
flask --app app run --debug
```

Open http://127.0.0.1:5000. A Groq key is optional; the app clearly labels deterministic local fallback analyses. `python -m pytest` runs the offline workflow tests.

## Demo workflow

Load the labelled demo data, analyze a database pool incident, resolve it with a verified recovery and post-mortem, then analyze the second connectivity sample. Its resolved predecessor is retrieved from SQLite and the actual cosine similarity and previous verified recovery are shown. Demo reset removes only incidents explicitly marked as demo data.

Logs are untrusted evidence. AI suggestions are hypotheses for engineer review; Chronoops never executes commands or changes production systems.
