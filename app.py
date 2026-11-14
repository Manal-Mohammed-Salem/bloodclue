"""BloodClue prototype: colour-coded CBC + iron results with an explainable summary.
Run locally: streamlit run app.py
"""
from pathlib import Path

import pandas as pd
import streamlit as st

from rules import CBC, IRON, TESTS, analyse, has, ref_range

HERE = Path(__file__).parent
COLOURS = {"Low": ("#C77700", "#FFF4E0"), "High": ("#D7263D", "#FDECEE"),
           "Normal": ("#1FA5A0", "#E6F6F5"), "Missing": ("#8A93A6", "#F1F3F7")}

st.set_page_config(page_title="BloodClue", page_icon="🩸", layout="wide")
st.logo(str(HERE / "assets" / "logo.png"), size="large")


def clean(row):
    return {k: (None if pd.isna(v) else v) for k, v in row.items()}


@st.cache_data
def load_samples():
    return pd.read_csv(HERE / "sample_patients.csv", dtype={"patient_id": str})


# ---------- sidebar: choose or upload results ----------
with st.sidebar:
    st.header("Lab results")
    uploaded = st.file_uploader("Upload results (CSV)", type="csv",
                                help="Same columns as the sample file. In the pilot, results arrive from the lab automatically.")
    df = pd.read_csv(uploaded, dtype={"patient_id": str}) if uploaded else load_samples()
    pid = st.selectbox("Patient", df["patient_id"])
    st.download_button("Download sample CSV", (HERE / "sample_patients.csv").read_bytes(),
                       "bloodclue_sample.csv", "text/csv")
    st.caption("Prototype with synthetic patients. Not for clinical use.")

p = clean(df[df["patient_id"] == pid].iloc[0].to_dict())
sex = "M" if str(p.get("sex", "F")).upper().startswith("M") else "F"
p["sex"] = sex
statuses, patterns, missing = analyse(p)

st.title("BloodClue")
st.caption("Every value coloured, every clue connected. The doctor decides.")

left, right = st.columns([1, 1.15], gap="large")

# ---------- left: patient + colour-coded results ----------
with left:
    with st.container(border=True):
        st.subheader(f"Patient {pid}")
        a, b, c = st.columns(3)
        a.metric("Sex", sex)
        b.metric("Age", p.get("age") or "–")
        c.metric("Pregnant", p.get("pregnant") or "–")
        st.write(f"**Symptoms:** {p.get('symptoms') or '–'}")
        st.success("Imported from the lab. Nothing typed.", icon="✅")

        def paint(row):
            fg, bg = COLOURS[row["Status"]]
            return ["", f"color:{fg};font-weight:700", "", f"color:{fg};background-color:{bg};font-weight:700"]

        for group, keys in (("Complete blood count", CBC), ("Iron studies", IRON)):
            rows = []
            for k in keys:
                label, unit, _ = TESTS[k]
                lo, hi = ref_range(k, sex)
                val = p.get(k)
                rows.append({"Test": label, "Result": f"{val:g} {unit}" if has(val) else "–",
                             "Reference": f"{lo:g} – {hi:g}", "Status": statuses[k]})
            st.markdown(f"**{group}**")
            st.dataframe(pd.DataFrame(rows).style.apply(paint, axis=1), hide_index=True, width="stretch",
                         height=35 * len(rows) + 38)

# ---------- right: the summary ----------
with right:
    outside = sum(1 for k in CBC + IRON if statuses[k] in ("Low", "High"))
    measured = sum(1 for k in CBC + IRON if statuses[k] != "Missing")
    st.subheader(f"Summary · {outside} of {measured} values outside range")

    if not patterns:
        st.info("No pattern from the current rules. Review the values above.")
    for i, pat in enumerate(patterns, 1):
        with st.container(border=True):
            st.markdown(f"#### {i}. {pat['title']}")
            st.markdown("**Supports:** " + " · ".join(pat["supports"]))
            if pat["against"]:
                st.markdown("**Does not fit:** " + " · ".join(pat["against"]))
            st.markdown("**Ask the patient:** " + " · ".join(pat["ask"]))
            st.caption(f"Rule {pat['rule']}: {pat['rule_text']} Status: draft, awaiting clinical sign-off.")

    if missing:
        st.warning("**Missing before a confident reading:** " + " · ".join(missing))

    st.markdown("**BloodClue does not diagnose. The doctor reviews and decides.**")

    with st.expander("Pilot feedback"):
        st.write("Was this summary useful for this patient?")
        if st.feedback("thumbs", key=f"fb-{pid}") is not None:
            st.caption("Thank you. (Prototype: feedback is not stored yet.)")

st.divider()
st.caption("BloodClue prototype v0.1 · synthetic data · reference ranges vary by laboratory · not for clinical use.")
