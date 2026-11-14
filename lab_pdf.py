"""Read lab results from a text-based lab-report PDF (e.g. SEHA / hospital LIS printouts).

Only results, the result date, age and sex are taken. Names, ID numbers and other identifiers are never read out.
shortcut: text PDFs only; photographed or scanned reports need OCR, add it when a pilot clinic sends scans.
"""
import io
import re
from datetime import date

NUM = r"([<>]?\d+(?:\.\d+)?)"
# test key -> line-start pattern (first match per test wins)
ALIASES = {
    "hb": r"(?:Hgb|HGB|Ha?emoglobin)",
    "rbc": r"(?:RBC(?: count)?|Red blood cells?)",
    "mcv": r"MCV",
    "rdw": r"RDW(?:-CV)?",
    "wbc": r"(?:WBC|White blood cells?)",
    "neut": r"(?:Neutro #|Neutrophils? #|ANC)",
    "eos": r"(?:Eos #|Eosinophils? #)",
    "plt": r"(?:Platelets?|PLT)",
    "ferritin": r"(?:Ferritin(?: Lvl)?|Serum ferritin)",
    "iron": r"(?:Iron Lvl|Serum iron|Iron)",
    "tibc": r"TIBC",
    "tsat": r"(?:Transferrin Sat(?:uration)?|TSAT|Iron saturation)",
    "crp": r"(?:C Reactive Prot(?:ein)?|CRP)",
    "b12": r"(?:Vitamin B12|B12)",
    "vitd": r"(?:Vitamin D(?: \(25 ?OH\))?|25[- ]?OH(?: Vitamin D)?)",
    "tsh": r"TSH",
    "mg": r"Magnesium",
}
LINE = {k: re.compile(rf"^\s*\*?\s*{a}\s+{NUM}\s*(\S+)?", re.I) for k, a in ALIASES.items()}
DATE = re.compile(r"(?:Lab Order Date|Collected(?: Time)?|Sample Collected On|Reported Time|Report Date)\s*:?\s*"
                  r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", re.I)
DOB = re.compile(r"DOB\s*:?\s*(\d{1,2})[-/](\d{1,2})[-/](\d{4})", re.I)
SEX = re.compile(r"(?:Gender|Sex)\s*:?\s*(Male|Female|M|F)\b", re.I)


def _convert(key, value, unit):
    u = (unit or "").lower()
    if key == "hb" and ("g/l" == u or value > 25):
        return round(value / 10, 2)                 # g/L -> g/dL
    if key in ("iron", "tibc") and "mol" in u:
        return round(value * 5.585, 1)              # µmol/L -> µg/dL
    if key == "crp" and u == "mg/dl":
        return round(value * 10, 1)                 # mg/dL -> mg/L
    if key == "b12" and "pmol" in u:
        return round(value * 1.355, 1)              # pmol/L -> pg/mL
    if key == "vitd" and "nmol" in u:
        return round(value / 2.496, 1)              # nmol/L -> ng/mL
    if key == "mg" and "mmol" in u:
        return round(value * 2.43, 2)               # mmol/L -> mg/dL
    return value


def parse_text(text):
    """Returns a result dict with test keys plus 'date', 'age', 'sex' when found."""
    out = {}
    for line in text.splitlines():
        for key, rx in LINE.items():
            if key in out:
                continue
            m = rx.match(line)
            if m:
                value = float(m.group(1).lstrip("<>"))
                out[key] = _convert(key, value, m.group(2))
                break
    d = DATE.search(text)
    if d:
        dd, mm, yy = (int(x) for x in d.groups())
        out["date"] = f"{yy:04d}-{mm:02d}-{dd:02d}"
    b = DOB.search(text)
    if b and "date" in out:
        bd, bm, by = (int(x) for x in b.groups())
        ty, tm, td = (int(x) for x in out["date"].split("-"))
        out["age"] = ty - by - ((tm, td) < (bm, bd))
    s = SEX.search(text)
    if s:
        out["sex"] = "M" if s.group(1).upper().startswith("M") else "F"
    return out


def parse_pdf(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return parse_text("\n".join(page.extract_text() or "" for page in reader.pages))


if __name__ == "__main__":  # self-check with synthetic report text: python lab_pdf.py
    sample = """Patient Name: TEST PERSON
Lab Order Date: 08-08-2026  DOB: 30/06/2005
Order Name: Iron Profile TRF
Iron Lvl 14.0 micromol/L 9.00-30.40 08-08-2026 20:08:42
TIBC 49.3 micromol/L 45.00-72.00 08-08-2026 20:08:42
Transferrin 2.1 g/L 1.80-3.90
Transferrin Sat 28.4 % 27.00-44.00
Ferritin Lvl 235.0 ug/L 10.00-204.00
Hgb 124.0 g/L 117.00-155.00
RDW-CV 12.0 % 11.60-14.80
RDW-SD 40.2 fL 37.90-48.30
Neutro % 21.7 % -
Neutro # 1.54 x10^9/L 1.80-7.70
Eos # 0.93 x10^9/L 0.00-0.70
C Reactive Prot 29.90 mg/L <=5.00
Gender : Female"""
    r = parse_text(sample)
    assert r["iron"] == 78.2 and r["tibc"] == 275.3 and r["tsat"] == 28.4 and r["ferritin"] == 235.0, r
    assert r["hb"] == 12.4 and r["rdw"] == 12.0 and r["neut"] == 1.54 and r["eos"] == 0.93 and r["crp"] == 29.9, r
    assert r["date"] == "2026-08-08" and r["age"] == 21 and r["sex"] == "F", r
    assert "Patient" not in str(r) and "TEST" not in str(r)
    print("lab_pdf self-check passed")
