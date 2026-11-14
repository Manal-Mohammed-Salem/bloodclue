# BloodClue: prototype

A second reader for a clinic's blood tests. CBC and iron results are colour-coded (low, normal, high), and a short summary shows the possible patterns, what supports them, what doesn't fit, and what is missing. Each pattern names the clinical rule that produced it.

**Prototype with synthetic patients. Not for clinical use.** The rules are drafts awaiting clinical sign-off. BloodClue does not diagnose; the doctor decides.

## Run it locally
```
pip install -r requirements.txt
streamlit run app.py
```

## Files
- `app.py`: the Streamlit screen
- `rules.py`: the explainable rules engine (run `python rules.py` for its self-check)
- `sample_patients.csv`: five synthetic patients; upload your own CSV with the same columns
