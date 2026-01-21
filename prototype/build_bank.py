import json, re, unicodedata
from pathlib import Path
import pandas as pd

# rutas
RUNS_DIR = Path(__file__).parent
PLUS_CSV = RUNS_DIR / "corpus_ext_plus.csv"
OUT_JSONL = RUNS_DIR / "bank.jsonl"
OUT_PREVIEW = RUNS_DIR / "bank_preview.csv"

# normalización
_final_punct_re = re.compile(r"[.,]+$")

def nfc(s):
    return unicodedata.normalize("NFC", str(s or "")).strip()

def std_norm_min(s: str) -> str:
    s = nfc(s)
    s = re.sub(r"\s+", " ", s)
    s = _final_punct_re.sub("", s)
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s

def triad_key(src, chg, tgt) -> str:
    return "|||".join([std_norm_min(src), std_norm_min(chg), std_norm_min(tgt)])

# cargar runs (modelo ganador: mistrall)
runs_all_path = max(RUNS_DIR.glob("runs_all_*.csv"), key=lambda p: p.stat().st_mtime)
runs = pd.read_csv(runs_all_path)

mask_mistral = runs["model_id"].astype(str).str.contains("mistral", case=False, na=False)
runs = runs[mask_mistral & (runs.get("error_flag", 0) == 0)].copy()

runs["pred_std"] = runs["pred_quz"].fillna("").map(std_norm_min)
runs["gold_std"] = runs["gold_quz"].fillna("").map(std_norm_min)
runs_ok = runs[runs["pred_std"] == runs["gold_std"]].copy()

# deduplicar por tríada (Source, Change, gold)
runs_ok["triad"] = runs_ok.apply(lambda r: triad_key(r["Source"], r["Change"], r["gold_quz"]), axis=1)
runs_ok = runs_ok.drop_duplicates(subset=["triad"], keep="first").copy()

# cargar task PLUS y preparar clave de enlace
plus = pd.read_csv(PLUS_CSV)
plus["key_plus"] = plus.apply(
    lambda r: "|||".join([nfc(r["source_quz"]), nfc(r["target_quz"]), nfc(r["change_obj"])]),
    axis=1
)

# preparar clave en runs
def key_runs(row):
    return "|||".join([nfc(row["Source"]), nfc(row["gold_quz"]), nfc(row["Change"])])
runs_ok["key_runs"] = runs_ok.apply(key_runs, axis=1)

# join runs plus por claves
cols_keep_plus = [
    "source_quz","target_quz","change_obj","change_delta",
    "source_es","target_es","tags_source","tags_target","level","hints"
]
merged = runs_ok.merge(
    plus[["key_plus"] + cols_keep_plus],
    left_on="key_runs", right_on="key_plus", how="inner"
)

# exportar bank.jsonl
records = []
for _, r in merged.iterrows():
    rec = {
        "id": int(r["id"]) if "id" in r else None,
        "level": int(r["level"]) if pd.notna(r["level"]) else None,
        "source_quz": nfc(r["source_quz"]),
        "target_quz": nfc(r["target_quz"]),
        "change_obj": nfc(r["change_obj"]),
        "change_delta": nfc(r.get("change_delta","")),
        "source_es": nfc(r.get("source_es","")) or None,
        "target_es": nfc(r.get("target_es","")) or None,
        "hints": json.loads(r["hints"]) if pd.notna(r.get("hints","")) else [],
        "tags_source": r.get("tags_source"),
        "tags_target": r.get("tags_target"),
        # extras útiles
        "triad": r["triad"],
        "model_id": r.get("model_id"),
        "K": int(r["K"]) if "K" in r and pd.notna(r["K"]) else None,
        "with_hints": int(r["with_hints"]) if "with_hints" in r and pd.notna(r["with_hints"]) else None,
    }
    records.append(rec)

with OUT_JSONL.open("w", encoding="utf-8") as f:
    for rec in records:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

# preview
pd.DataFrame(records, columns=[
    "id","level","source_quz","change_obj","target_quz","source_es","target_es"
]).to_csv(OUT_PREVIEW, index=False, encoding="utf-8")

print(f"[OK] Banco listo: {OUT_JSONL}  ({len(records)} ítems)")
print(f"[OK] Vista previa: {OUT_PREVIEW}")