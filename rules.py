"""BloodClue rules engine: explainable checks on CBC + iron results.

Every pattern names the rule that produced it. All rules are DRAFTS until a licensed
clinician signs them off. This is a prototype, not for clinical use.
"""
import math

# test key -> label, unit, reference range (low, high). Sex-specific ranges are dicts.
TESTS = {
    "hb":       ("Haemoglobin", "g/dL", {"F": (12.0, 15.5), "M": (13.5, 17.5)}),
    "rbc":      ("Red blood cells", "×10¹²/L", {"F": (3.8, 5.2), "M": (4.5, 5.9)}),
    "mcv":      ("MCV", "fL", (80, 100)),
    "rdw":      ("RDW", "%", (11.5, 14.5)),
    "wbc":      ("White cells", "×10⁹/L", (4.0, 11.0)),
    "neut":     ("Neutrophils", "×10⁹/L", (1.8, 7.7)),
    "eos":      ("Eosinophils", "×10⁹/L", (0.0, 0.5)),
    "plt":      ("Platelets", "×10⁹/L", (150, 400)),
    "ferritin": ("Ferritin", "ng/mL", {"F": (15, 150), "M": (30, 400)}),
    "iron":     ("Serum iron", "µg/dL", (60, 170)),
    "tibc":     ("TIBC", "µg/dL", (250, 400)),
    "tsat":     ("Transferrin saturation", "%", (20, 50)),
    "crp":      ("CRP", "mg/L", (0, 5)),
}
CBC = ["hb", "rbc", "mcv", "rdw", "wbc", "neut", "eos", "plt"]
OPTIONAL = {"crp", "neut", "eos"}  # not flagged as missing when absent
SYMPTOMS = ("tired", "fatigue", "dizz", "hair loss", "poor focus", "headache", "weak", "cold")
IRON = ["ferritin", "iron", "tibc", "tsat", "crp"]


def has(v):
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def ref_range(key, sex):
    rng = TESTS[key][2]
    return rng[sex] if isinstance(rng, dict) else rng


def status(key, value, sex):
    if not has(value):
        return "Missing"
    lo, hi = ref_range(key, sex)
    return "Low" if value < lo else "High" if value > hi else "Normal"


def analyse(p, history=()):
    """p: dict with sex ('F'/'M') and test keys; history: earlier results of the same patient, oldest first.
    Returns (statuses, patterns, missing)."""
    sex = p.get("sex", "F")
    st = {k: status(k, p.get(k), sex) for k in TESTS}
    v = {k: p.get(k) for k in TESTS}
    patterns, missing = [], []
    symptoms = str(p.get("symptoms") or "").lower()
    has_symptoms = any(s in symptoms for s in SYMPTOMS)
    treatment = (str(p.get("medicines") or "") + " " + str(p.get("notes") or "")).lower()

    # IRON-01: depleted iron stores
    if has(v["ferritin"]) and v["ferritin"] < 15:
        anaemic = st["hb"] == "Low"
        patterns.append({
            "title": "Iron-deficiency anaemia (possible)" if anaemic else "Iron deficiency without anaemia (possible)",
            "rule": "IRON-01", "rule_text": "Ferritin below 15 ng/mL indicates depleted iron stores, even when haemoglobin is normal.",
            "supports": [f"Ferritin {v['ferritin']} (low)"]
                        + [f"{TESTS[k][0]} {st[k].lower()}" for k in ("tsat", "iron", "tibc", "rdw") if st[k] in ("Low", "High")],
            "against": [] if anaemic else ["Haemoglobin normal, so a printout alone looks reassuring"],
            "ask": ["Heavy periods or other blood loss?", "Diet?", "Gut symptoms?", "Previous iron treatment and response?"],
        })
    # IRON-02: low-normal ferritin with low saturation
    elif has(v["ferritin"]) and v["ferritin"] < 30 and st["tsat"] == "Low":
        patterns.append({
            "title": "Early iron deficiency (possible)", "rule": "IRON-02",
            "rule_text": "Ferritin under 30 ng/mL with transferrin saturation under 20% may indicate early iron deficiency.",
            "supports": [f"Ferritin {v['ferritin']}", f"Transferrin saturation {v['tsat']}% (low)"],
            "against": [], "ask": ["Symptoms of tiredness or hair loss?", "Previous ferritin values?"],
        })
    # IRON-04: low-normal ferritin with symptoms, which a wide lab range can call "normal"
    elif has(v["ferritin"]) and v["ferritin"] < 30 and has_symptoms:
        patterns.append({
            "title": "Low-normal ferritin with symptoms: possible iron deficiency", "rule": "IRON-04",
            "rule_text": "Ferritin under 30 ng/mL is a common threshold for iron deficiency; a lab range starting near 10 "
                         "can still print it as normal.",
            "supports": [f"Ferritin {v['ferritin']} (inside the lab range, under 30)", f"Symptoms: {p.get('symptoms')}"],
            "against": ([] if st["hb"] != "Normal" else ["Haemoglobin normal"]),
            "ask": ["Diet and appetite?", "Blood loss?", "Gut symptoms or poor absorption?", "Previous ferritin values?"],
        })
    # IRON-05: high ferritin right after IV iron or with inflammation is not iron overload by itself
    if st["ferritin"] == "High" and ("iv iron" in treatment or st["crp"] == "High"
                                     or any(h.get("crp") and status("crp", h["crp"], sex) == "High" for h in history[-1:])):
        patterns.append({
            "title": "High ferritin: check recent IV iron and inflammation first", "rule": "IRON-05",
            "rule_text": "Ferritin rises for weeks after IV iron and during inflammation; it does not mean iron overload "
                         "on its own. Read it with transferrin saturation and CRP, and recheck later.",
            "supports": [f"Ferritin {v['ferritin']} (high)"]
                        + (["Recent IV iron"] if "iv iron" in treatment else [])
                        + ([f"Transferrin saturation {v['tsat']}% (not high)"] if st["tsat"] in ("Normal", "Low") else []),
            "against": [] , "ask": ["Date of the last IV iron dose?", "Recent infection or fever?"],
        })
    # WBC-01: raised eosinophils, more important when they stay raised over time
    if st["eos"] == "High":
        earlier = [h for h in history if has(h.get("eos")) and status("eos", h["eos"], sex) == "High"]
        patterns.append({
            "title": ("Eosinophils raised in repeated tests" if earlier else "Raised eosinophils"), "rule": "WBC-01",
            "rule_text": "Raised eosinophils have several causes, including allergy, asthma, eczema, some medicines and "
                         "parasites; parasites can also cause iron deficiency and poor absorption.",
            "supports": [f"Eosinophils {v['eos']} (high)"] + [f"Also high on {h.get('date', 'an earlier test')}: {h['eos']}"
                                                            for h in earlier],
            "against": [], "ask": ["Allergy, asthma or eczema?", "Travel, or a stool test for parasites?",
                                   "New medicines?"],
        })
    # IRON-03: low saturation with normal/high ferritin -> inflammation may mask iron deficiency
    if has(v["ferritin"]) and v["ferritin"] >= 30 and st["tsat"] == "Low":
        patterns.append({
            "title": "Iron-restricted pattern: consider inflammation", "rule": "IRON-03",
            "rule_text": "Low transferrin saturation with normal or high ferritin can mean inflammation is raising ferritin.",
            "supports": [f"Transferrin saturation {v['tsat']}% (low)", f"Ferritin {v['ferritin']}"]
                        + ([f"CRP {v['crp']} (high)"] if st["crp"] == "High" else []),
            "against": [] if st["crp"] == "High" else ["CRP not raised or not measured"],
            "ask": ["Recent infection or chronic inflammatory condition?"],
        })
    # CBC-01: microcytosis with normal ferritin -> consider thalassaemia trait (Mentzer index)
    if st["mcv"] == "Low" and has(v["ferritin"]) and st["ferritin"] != "Low" and has(v["rbc"]):
        mentzer = round(v["mcv"] / v["rbc"], 1)
        patterns.append({
            "title": "Small red cells with normal iron: consider thalassaemia trait", "rule": "CBC-01",
            "rule_text": "Low MCV with normal ferritin; a Mentzer index (MCV ÷ RBC) under 13 favours thalassaemia trait.",
            "supports": [f"MCV {v['mcv']} (low)", f"Ferritin {v['ferritin']} (normal)", f"Mentzer index {mentzer}"],
            "against": [] if mentzer < 13 else ["Mentzer index 13 or above"],
            "ask": ["Family history of thalassaemia?", "Previous haemoglobin electrophoresis?"],
        })
    # CBC-02: high haemoglobin -> check context before concluding
    if st["hb"] == "High":
        patterns.append({
            "title": "High haemoglobin: check context", "rule": "CBC-02",
            "rule_text": "Dehydration, smoking, some medicines and altitude can raise haemoglobin; compare with previous results.",
            "supports": [f"Haemoglobin {v['hb']} (high)"], "against": [],
            "ask": ["Water intake?", "Smoking?", "Testosterone or other medicines?", "Previous results?"],
        })

    if has(v["ferritin"]) and not has(v["crp"]):
        missing.append("CRP (inflammation can hide low iron)")
    if not history and not p.get("previous"):
        missing.append("Previous results, for the trend")
    if not p.get("medicines"):
        missing.append("Current medicines and supplements")
    missing += [f"{TESTS[k][0]} result" for k in CBC + IRON if k not in OPTIONAL and not has(v[k])]
    return st, patterns, missing


if __name__ == "__main__":  # self-check: python rules.py
    st, pats, miss = analyse({"sex": "F", "hb": 12.6, "rbc": 4.4, "mcv": 81, "rdw": 15.4, "wbc": 6.8, "plt": 310,
                              "ferritin": 10, "iron": 45, "tibc": 430, "tsat": 10})
    assert st["ferritin"] == "Low" and st["hb"] == "Normal" and st["tibc"] == "High"
    assert pats[0]["rule"] == "IRON-01" and "without anaemia" in pats[0]["title"]
    assert any("CRP" in m for m in miss)
    _, pats, _ = analyse({"sex": "M", "hb": 13.0, "rbc": 6.1, "mcv": 66, "ferritin": 90, "tsat": 30})
    assert [x["rule"] for x in pats] == ["CBC-01"] and "10.8" in pats[0]["supports"][2]
    _, pats, _ = analyse({"sex": "M", "hb": 18.2, "ferritin": 120, "tsat": 30})
    assert [x["rule"] for x in pats] == ["CBC-02"]
    _, pats, _ = analyse({"sex": "F", "hb": 11.5, "ferritin": 85, "tsat": 12, "crp": 24})
    assert [x["rule"] for x in pats] == ["IRON-03"]
    # low-normal ferritin + symptoms -> IRON-04; without symptoms -> nothing
    _, pats, _ = analyse({"sex": "F", "hb": 13.1, "ferritin": 23.4, "symptoms": "dizziness, tiredness"})
    assert [x["rule"] for x in pats] == ["IRON-04"]
    _, pats, _ = analyse({"sex": "F", "hb": 13.1, "ferritin": 23.4, "symptoms": "routine check"})
    assert pats == []
    # high ferritin after inflammation on the previous test + eosinophils high again -> IRON-05 and persistent WBC-01
    hist = [{"date": "2026-04-28", "eos": 0.96}, {"date": "2026-08-03", "crp": 29.9, "eos": 0.23}]
    _, pats, miss = analyse({"sex": "F", "ferritin": 235, "tsat": 28.4, "eos": 0.93}, history=hist)
    assert [x["rule"] for x in pats] == ["IRON-05", "WBC-01"], pats
    assert "repeated" in pats[1]["title"] and "2026-04-28" in pats[1]["supports"][1]
    assert not any("Previous results" in m for m in miss)
    print("rules self-check passed")
