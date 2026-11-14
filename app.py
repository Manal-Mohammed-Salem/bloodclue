"""BloodClue prototype: colour-coded CBC + iron results, symptom clues, a bedside hypermobility check, the patient's
full history in one place, the clinical partner's knowledge base and a (demo) ranking of contributing doctors.
Run locally: streamlit run app.py
"""
import importlib
import json
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st

import rules

importlib.reload(rules)  # Streamlit reruns app.py on deploy but keeps imported modules; pick up rule changes too
from rules import (BEIGHTON, CBC, IRON, OTHER, SYMPTOM_LINKS, TESTS, analyse, beighton_cutoff, has,  # noqa: E402
                   preselect_symptoms, ref_range, status, summarize_history, symptom_clues)

HERE = Path(__file__).parent
COLOURS = {"Low": ("#C77700", "#FFF4E0"), "High": ("#D7263D", "#FDECEE"),
           "Normal": ("#1FA5A0", "#E6F6F5"), "Missing": ("#8A93A6", "#F3F5F9")}

st.set_page_config(page_title="BloodClue", page_icon=str(HERE / "assets" / "logo.png"), layout="wide")
st.logo(str(HERE / "assets" / "logo.png"), size="large")


def clean(row):
    return {k: (None if pd.isna(v) else int(v) if isinstance(v, float) and v.is_integer() else v)
            for k, v in row.items()}


@st.cache_data
def load_csv(name):
    return pd.read_csv(HERE / name, dtype={"patient_id": str})


# ---------- sidebar: choose or upload results ----------
with st.sidebar:
    st.header("Lab results")
    uploaded = st.file_uploader("Upload results (CSV)", type="csv",
                                help="Same columns as the sample file. In the pilot, results arrive from the lab automatically.")
    df = pd.read_csv(uploaded, dtype={"patient_id": str}) if uploaded else load_csv("sample_patients.csv")
    pid = st.selectbox("Patient", df["patient_id"].unique())
    visits = df[df["patient_id"] == pid]
    if "date" in visits:
        visits = visits.sort_values("date")
    dates = list(visits["date"]) if "date" in visits else [None]
    idx = len(dates) - 1
    if len(dates) > 1:
        idx = dates.index(st.selectbox("Result date", dates, index=idx))
    st.download_button("Download sample CSV", (HERE / "sample_patients.csv").read_bytes(),
                       "bloodclue_sample.csv", "text/csv")
    st.caption("Prototype with synthetic or de-identified patients. Not for clinical use.")

rows_ = [clean(r) for r in visits.to_dict("records")]
for r in rows_:
    r["sex"] = "M" if str(r.get("sex", "F")).upper().startswith("M") else "F"
p, history = rows_[idx], rows_[:idx]
sex = p["sex"]

# Beighton score from the bedside check below (session state holds the ticks from the last interaction)
bt_keys = [f"bt-{pid}-{i}-{side}" for i, (_, n) in enumerate(BEIGHTON) for side in (["L", "R"] if n == 2 else ["B"])]
if st.session_state.get(f"bt-done-{pid}"):
    p["beighton"] = sum(bool(st.session_state.get(k)) for k in bt_keys)
statuses, patterns, missing = analyse(p, history)

st.title("BloodClue")
st.caption("Every result in one place, every value coloured, every clue connected. The doctor decides.")

tab_doc, tab_hist, tab_kb, tab_rank = st.tabs(["Doctor view", "Patient history", "Knowledge base", "Doctor ranking"])

# ---------- tab 1: doctor view ----------
with tab_doc:
    left, right = st.columns([1, 1.15], gap="large")
    with left:
        with st.container(border=True):
            st.subheader(f"Patient {pid}" + (f", {p['date']}" if p.get("date") else ""))
            a, b, c = st.columns(3)
            a.metric("Sex", sex)
            b.metric("Age", p.get("age") or "–")
            c.metric("Pregnant", p.get("pregnant") or "–")
            st.write(f"**Symptoms:** {p.get('symptoms') or '–'}")
            st.success("Imported from the lab. Nothing typed.")

            def paint(row):
                fg, bg = COLOURS[row["Status"]]
                return ["", f"color:{fg};font-weight:600", "", f"color:{fg};background-color:{bg};font-weight:600"]

            groups = [("Complete blood count", CBC), ("Iron studies", IRON)]
            if any(has(p.get(k)) for k in OTHER):
                groups.append(("Vitamins, thyroid and minerals", OTHER))
            for group, keys in groups:
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

        # ---- bedside test: Beighton score for generalised joint hypermobility ----
        with st.expander("Joint hypermobility check (Beighton score)", expanded=bool(p.get("beighton") is not None)):
            st.caption("Nine quick bedside manoeuvres, one point each. Tick what the patient can do.")
            for i, (label, n) in enumerate(BEIGHTON):
                cols = st.columns([3, 1, 1])
                cols[0].write(label)
                for j, side in enumerate(["L", "R"] if n == 2 else ["B"]):
                    cols[1 + j].checkbox({"L": "Left", "R": "Right", "B": "Yes"}[side], key=f"bt-{pid}-{i}-{side}")
            st.toggle("Test done", key=f"bt-done-{pid}")
            if p.get("beighton") is not None:
                cut = beighton_cutoff(p.get("age"))
                verdict = "reaches" if p["beighton"] >= cut else "is below"
                st.markdown(f"**Score {p['beighton']}/9**, which {verdict} the cut-off of {cut} for age "
                            f"{p.get('age') or 'unknown'}.")
            st.markdown("Other signs to note (not part of the score)")
            st.checkbox("Thumb sign: with a closed fist, the thumb passes the edge of the palm", key=f"ts-{pid}")
            st.checkbox("Wrist sign: thumb and little finger overlap around the other wrist", key=f"ws-{pid}")

    with right:
        # ---- symptoms -> possible causes, in violet, checked against the results ----
        with st.container(border=True):
            st.subheader(":violet[Symptom clues]")
            chosen = st.multiselect("Symptoms (filled in from the patient's file; add or remove)",
                                    list(SYMPTOM_LINKS), default=preselect_symptoms(p.get("symptoms")),
                                    key=f"sym-{pid}-{idx}")
            badge = {"supported": ":violet-badge[Supported by results]",
                     "test suggested": ":orange-badge[Not tested yet]",
                     "ask": ":blue-badge[Ask the patient]",
                     "not supported": ":gray-badge[Not supported by results]"}
            clues = symptom_clues(chosen, p)
            if not chosen:
                st.caption("Pick a symptom to see what it might come from.")
            for c in clues:
                st.markdown(f":violet[**{c['cause']}**] {badge[c['evidence']]}  \n"
                            f"<small>From {', '.join(c['symptoms']).lower()}. {c['detail']}.</small>",
                            unsafe_allow_html=True)
            if clues:
                st.caption("Possible links that guide which tests and questions to consider. Not a diagnosis.")

        outside = sum(1 for k in CBC + IRON + OTHER if statuses[k] in ("Low", "High"))
        measured = sum(1 for k in CBC + IRON + OTHER if statuses[k] != "Missing")
        st.subheader(f"Summary: {outside} of {measured} values outside range")
        if not patterns:
            st.info("No pattern from the current rules. Review the values above.")
        for i, pat in enumerate(patterns, 1):
            with st.container(border=True):
                st.markdown(f"#### {i}. {pat['title']}")
                st.markdown("**Supports:** " + "; ".join(pat["supports"]))
                if pat["against"]:
                    st.markdown("**Does not fit:** " + "; ".join(pat["against"]))
                st.markdown("**Ask the patient:** " + " ".join(pat["ask"]))
                st.caption(f"Rule {pat['rule']}: {pat['rule_text']} Draft, awaiting clinical sign-off.")
        if missing:
            st.warning("**Missing before a confident reading:** " + "; ".join(missing))
        st.markdown("**BloodClue does not diagnose. The doctor reviews and decides.**")

# ---------- tab 2: the patient's whole story, so it is never retold ----------
with tab_hist:
    st.subheader(f"Everything the doctor should know about {pid}")
    st.caption("Built automatically from every visit, so the patient doesn't repeat their story. "
               "Rule-based for now; an AI-written version comes later.")
    s = summarize_history(rows_)
    c1, c2 = st.columns(2, gap="large")
    with c1:
        with st.container(border=True):
            st.markdown("#### Overview")
            for line in s["overview"]:
                st.markdown(f"- {line}")
            st.markdown("#### Found more than once")
            for line in s["repeated"] or ["Nothing out of range on more than one date."]:
                st.markdown(f"- {line}")
            st.markdown("#### Symptoms reported")
            st.markdown(", ".join(s["symptoms"]) or "–")
            st.markdown("#### Treatments recorded")
            for line in s["treatments"] or ["None recorded."]:
                st.markdown(f"- {line}")
    with c2:
        with st.container(border=True):
            st.markdown("#### Visit by visit")
            for line in s["timeline"]:
                st.markdown(f"- {line}")
    if len(rows_) > 1:
        with st.container(border=True):
            st.markdown("#### Results over time")
            keys = [k for k in CBC + IRON + OTHER if sum(has(r.get(k)) for r in rows_) >= 2]
            trend = pd.DataFrame({r["date"]: [r.get(k) if has(r.get(k)) else None for k in keys] for r in rows_},
                                 index=[TESTS[k][0] for k in keys])

            def mark(col):
                return ["color:{};font-weight:600".format(COLOURS[status(k, v, sex)][0]) if has(v) else ""
                        for k, v in zip(keys, col)]

            st.dataframe(trend.style.apply(mark, axis=0).format(lambda v: "–" if pd.isna(v) else f"{v:g}"),
                         width="stretch")

# ---------- tab 3: what the clinical partner teaches (draft) ----------
with tab_kb:
    kb = json.loads((HERE / "knowledge.json").read_text(encoding="utf-8"))
    st.subheader("What our clinical partner teaches")
    st.info(f"Drafted from {sum(e['videos'] for e in kb)} references in the educational videos of a Dubai "
            "internal-medicine specialist, translated from Arabic. Every point awaits his sign-off before it becomes "
            "a rule. Points with doses or uncertain numbers stay hidden until reviewed.")
    kinds = {"lab_rule": "Lab", "symptom": "Symptom", "cause": "Cause", "treatment": "Treatment",
             "advice": "Advice", "myth": "Myth"}
    for e in kb:
        shown = [x for x in e["points"] if not x["needs_review"]]
        hidden = len(e["points"]) - len(shown)
        with st.expander(f"**{e['topic']}**, {e['videos']} videos"):
            for x in shown:
                st.markdown(f"- **{kinds.get(x['type'], 'Note')}.** {x['statement']}")
            if hidden:
                st.caption(f"{hidden} point(s) hidden until clinical review.")
            if e["ask_patient"]:
                st.markdown("**Questions to ask:** " + " ".join(e["ask_patient"]))

# ---------- tab 4: contributing doctors (demo data) ----------
with tab_rank:
    st.subheader("Doctors who teach BloodClue")
    st.warning("**Demo data.** These are not real doctors or clinics. The real ranking will come from accepted, "
               "reviewed rules.")
    docs = load_csv("doctors.csv").sort_values(["accepted_rules", "reviews_given"], ascending=False)
    docs.insert(0, "Rank", range(1, len(docs) + 1))
    docs["Map"] = ["https://www.google.com/maps/search/" + quote_plus(f"{r.clinic} {r.area} {r.city}")
                   for r in docs.itertuples()]
    st.dataframe(
        docs[["Rank", "name", "specialty", "clinic", "area", "city", "accepted_rules", "reviews_given", "badge", "Map"]],
        hide_index=True, width="stretch",
        column_config={
            "name": "Doctor", "specialty": "Specialty", "clinic": "Clinic", "area": "Area", "city": "City",
            "accepted_rules": st.column_config.ProgressColumn("Accepted rules", min_value=0,
                                                              max_value=int(docs["accepted_rules"].max()), format="%d"),
            "reviews_given": "Reviews", "badge": "Badge",
            "Map": st.column_config.LinkColumn("Find the clinic", display_text="Open map"),
        })
    st.caption("A rule only counts after clinical review; votes alone never change the system.")

st.divider()
st.caption("BloodClue prototype v0.3. Synthetic and de-identified data. Reference ranges vary by laboratory. "
           "Not for clinical use.")
