# app.py
import json, random, re, unicodedata
from pathlib import Path
import streamlit as st
from difflib import SequenceMatcher

st.set_page_config(page_title="Ejercicios (Quechua Collao)", layout="centered")
BANK_PATH = Path(__file__).resolve().parent / "bank.jsonl"

# rerun helper (evaluar versiones de Streamlit)
def _rerun():
    try:
        st.rerun()  # Streamlit >= 1.27
    except AttributeError:
        st.experimental_rerun()  # Streamlit < 1.27

# estilos CSS
st.markdown("""
<style>
div.stButton > button {
  padding: 0.45rem 1.0rem;
  white-space: nowrap;
  line-height: 1.2;
}
div.stButton { margin-right: .5rem; }
.small-gap { margin-top: -0.35rem; }
</style>
""", unsafe_allow_html=True)

# utilidades
def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", str(s or "")).strip()

@st.cache_data(show_spinner=False)
def load_bank():
    items = []
    with BANK_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            items.append(json.loads(line))
    # orden estable por nivel e id
    items.sort(key=lambda x: (x.get("level", 99), x.get("id", 0)))
    return items

def parse_change_to_dict(ch_str: str) -> dict:
    ch_str = (ch_str or "").strip().strip("{}")
    if not ch_str:
        return {}
    out = {}
    for part in ch_str.split(","):
        part = part.strip()
        if ":" in part:
            k, v = part.split(":", 1)
            out[nfc(k)] = nfc(v)
    return out

# naturalización etiquetas
PERSON_ES = {
    "1_SI": "Primera Persona Singular",
    "2_SI": "Segunda Persona Singular",
    "3_SI": "Tercera Persona Singular",
    "1_PL_INC": "Primera Persona Plural Inclusiva",
    "1_PL_EXC": "Primera Persona Plural Exclusiva",
    "2_PL": "Segunda Persona Plural",
    "3_PL": "Tercera Persona Plural",
}
PERSON_ES_COMPACT = {
    "1_SI": "Primera Singular",
    "2_SI": "Segunda Singular",
    "3_SI": "Tercera Singular",
    "1_PL_INC": "Primera Plural Inclusiva",
    "1_PL_EXC": "Primera Plural Exclusiva",
    "2_PL": "Segunda Plural",
    "3_PL": "Tercera Plural",
}
LABEL_ES = {
    "PERSON": "PERSONA",
    "NUMBER": "NÚMERO",
    "POSS": "POSESIÓN",
    "TENSE": "TIEMPO",
    "ASPECT": "ASPECTO",
    "MODE": "MODO",
    "TYPE": "TIPO DE FRASE",
    "SUBTYPE": "SUBTIPO",
    "PERSON_OBJ": "PRONOMBRE DE OBJETO",
    "EVID": "EVIDENCIALIDAD",
}
VALUE_ES = {
    ("NUMBER", "PL"): "Plural",
    ("TENSE", "PRE_SIM"): "Presente Simple",
    ("TENSE", "FUT_SIM"): "Futuro",
    ("TENSE", "PST_EXP"): "Pasado experimentado",
    ("TENSE", "PST_NEXP"): "Pasado no experimentado",
    ("ASPECT", "PRG"): "Progresivo",
    ("MODE", "POT"): "Potencial",
    ("MODE", "DUB"): "Dubitativo",
    ("TYPE", "IMP"): "Imperativa",
    ("TYPE", "NEG"): "Negación proposicional",
    ("TYPE", "PROH"): "Negación prohibitiva",
    ("SUBTYPE", "INT"): "Interrogativa",
    ("EVID", "ATT"): "Atestiguativa",
    ("EVID", "REP"): "Reportativa",
}

def change_lines_es(change_obj: str, source_quz: str | None = None, target_quz: str | None = None) -> list[str]:
    d = parse_change_to_dict(change_obj)
    lines = []
    if not d:
        return lines

    if len(d) > 1 and source_quz and target_quz:
        keys = infer_category_order(source_quz, target_quz, d)
    else:
        keys = sorted(d.keys())

    for k in keys:
        v = d[k]
        label = LABEL_ES.get(k, k)
        if k == "PERSON":
            val_es = PERSON_ES.get(v, v)
        elif k == "POSS":
            val_es = PERSON_ES.get(v, v)
        elif k == "PERSON_OBJ":
            try:
                src, tgt = v.split(">", 1)
                src_es = PERSON_ES_COMPACT.get(src.strip(), src.strip())
                tgt_es = PERSON_ES_COMPACT.get(tgt.strip(), tgt.strip())
                val_es = f"{src_es} → {tgt_es}"
            except Exception:
                val_es = v
        else:
            val_es = VALUE_ES.get((k, v), v)
        lines.append(f"{label}: {val_es}")
    return lines

# gaps básicos para agregar huecos en morfemas
def char_span_diff(a: str, b: str):
    s = SequenceMatcher(a=a, b=b)
    spans = []
    for tag, i1, i2, j1, j2 in s.get_opcodes():
        if tag == "equal":
            continue
        spans.append((a[i1:i2], b[j1:j2]))
    return spans

def morpheme_gaps_general(source: str, target: str):
    """
    Fallback genérico: usa diferencias de spans de caracteres para enmascarar
    hasta dos fragmentos distintos entre source y target.

    Siempre reemplaza los fragmentos ocultos con un placeholder fijo "_____",
    independiente de la longitud real del sufijo.
    """
    diffs = char_span_diff(source, target)
    t_frags = [t for _, t in diffs if t]
    t_frags = sorted(t_frags, key=len, reverse=True)[:2]
    masked = target
    for frag in t_frags:
        if frag.strip():
            masked = masked.replace(frag, "_____", 1)
    masked = re.sub(r"\s{2,}", " ", masked).strip()
    masked = re.sub(r"\s*_____+\s*", " _____ ", masked)
    masked = re.sub(r"\s{2,}", " ", masked).strip()
    return masked, [f.strip() for f in t_frags if f.strip()]

def morpheme_gaps_neg_proh(source: str, target: str, kind: str, change: dict | None = None):
    """
    NEG/PROH: patrón mana/ama … (morfemas verbales) … -chu con dos huecos.

    - Primer hueco: la partícula de negación (mana/ama) como palabra independiente.
      Si lleva evidencial pegado (manam, manami, amas, amasi), se considera todo
      ese bloque dentro del hueco.
    - Segundo hueco: el bloque verbal asociado a la negación, incluyendo siempre -chu
      y, si aplica, otros morfemas añadidos (p.ej. chka en ASPECT:PRG).
    - Ambos huecos usan un placeholder fijo "_____".
    """
    trig = "mana" if kind == "NEG" else "ama"
    masked = target

    evid_code = change.get("EVID") if change else None

    # 1. Hueco para la partícula de negación (con o sin evidencial pegado)
    found_block = False
    if evid_code in EVID:
        # intentar primero capturar formas como manam, manami, amas, amasi
        for ev in sorted(EVID[evid_code], key=len, reverse=True):
            ev = nfc(ev)
            # permitir que la palabra sea exactamente trig+evid, con o sin puntuación final
            pattern = rf"\b{trig}{ev}(?=\b|[.,;:!?\u00B7])"
            if re.search(pattern, masked):
                masked = re.sub(pattern, "_____", masked, count=1)
                found_block = True
                break

    # si no encontramos bloque mana+evid, seguir flujo normal con solo mana/ama:
    if not found_block and trig in target and trig not in source:
        masked = re.sub(rf"\b{trig}\b", "_____", masked, count=1)

    # 2. hueco para el bloque verbal que termina en -chu
    def _mask_chu_once(text: str):
        m = re.search(r"([A-Za-zñÑ'áéíóúÁÉÍÓÚ]+-?)chu\b", text)
        if m:
            start, end = m.span()
            chunk = text[start:end]          # p.ej. 'unquchkanchu'
            stem = chunk.replace("chu", "")  # p.ej. 'unquchkan'

            # si hay aspecto progresivo en el cambio, quitamos 'chka' del verbo
            # para que también quede en el hueco (ej.: unqun_____ en vez de unquchkan_____).
            if change and change.get("ASPECT") == "PRG":
                stem = stem.replace("chka", "", 1)

            return text[:start] + stem + "_____" + text[end:], True
        return text, False

    masked, _ = _mask_chu_once(masked)

    # normalización de espacios
    masked = re.sub(r"\s{2,}", " ", masked).strip()

    # En NEG/PROH no usamos frags para opciones, solo como descriptor
    frags = [f"{trig} … -chu"]
    return masked, frags

def morpheme_gaps_int(source: str, target: str):
    """
    SUBTYPE:INT → mantener ¿? y enmascarar solo -chu final del predicado.
    """
    has_open  = "¿" in target
    has_close = "?" in target
    core_target = target.replace("¿", "").replace("?", "")

    m = re.search(r"([A-Za-zñÑ'áéíóúÁÉÍÓÚ]+-?)chu\b", core_target)
    masked_core = core_target
    if m:
        start, end = m.span()
        stem = core_target[start:end].replace("chu", "")
        masked_core = core_target[:start] + stem + "_____" + core_target[end:]

    masked_core = re.sub(r"\s{2,}", " ", masked_core).strip()
    #quitar espacios alrededor del hueco para que quede pegado al verbo
    masked_core = re.sub(r"\s*_+\s*", lambda m: m.group(0).strip(), masked_core)
    masked_core = re.sub(r"\s{2,}", " ", masked_core).strip()

    if has_open:
        masked_core = "¿" + masked_core
    if has_close:
        masked_core = masked_core + "?"

    return masked_core, ["-chu"]

# tokenización básica
TOKEN_RE = re.compile(r"\S+")

def _tokenize(s: str):
    return TOKEN_RE.findall(s), list(TOKEN_RE.finditer(s))

# inventario concatenado
PERSON_PRESENT = {
    "1_SI": {"ni"}, "2_SI": {"nki"}, "3_SI": {"n"},
    "1_PL_INC": {"nchik"}, "1_PL_EXC": {"yku"},
    "2_PL": {"nkichik"}, "3_PL": {"nku"},
}
TENSE_FUT_SIM = {
    "1_SI": {"saq"}, "2_SI": {"nki"}, "3_SI": {"nqa"},
    "1_PL_INC": {"sunchik"}, "1_PL_EXC": {"saqku"},
    "2_PL": {"nkichik"}, "3_PL": {"nqaku"},
}
PST_EXP_AFFIX = {"rqa"}
PST_NEXP_AFFIX = {"sqa"}
ASPECT = {"PRG": {"chka"}}
MODE = {"POT": {"man"}, "DUB": {"manchus"}}
TYPE_POOL = {
    "IMP": {"y", "chun", "sunchik", "saqku", "ychik", "chunku"},
    "NEG": {"mana … -chu"},
    "PROH": {"ama … -chu"},
}
SUBTYPE = {"INT": {"chu"}}
EVID = {"ATT": {"mi", "m"}, "REP": {"si", "s"}}
POSS_POOL = {
    "1_SI": {"y", "niy"},
    "2_SI": {"yki", "niyki"},
    "3_SI": {"n", "nin"},
    "1_PL_INC": {"nchik", "ninchik"},
    "1_PL_EXC": {"yku", "niyku"},
    "2_PL": {"ykichik", "niykichik"},
    "3_PL": {"nku", "ninku"},
}
NUMBER = {"PL": {"kuna"}}

# mapa de posibles morfemas por categoría (para inferir orden)
CAT_SURF = {
    "POSS": set().union(*POSS_POOL.values()),
    "NUMBER": set().union(*NUMBER.values()),
    "PERSON": set().union(*PERSON_PRESENT.values()),
    "TENSE": PST_EXP_AFFIX
             | PST_NEXP_AFFIX
             | set().union(*TENSE_FUT_SIM.values()),
    "ASPECT": set().union(*ASPECT.values()),
    "MODE": set().union(*MODE.values()),
    "PERSON_OBJ": {"yki", "wanqi", "wan", "ni", "sunki", "nki"},
    "EVID": set().union(*EVID.values()),
    # SUBTYPE/TYPE son más sintácticos; si no se detectan, quedarán al final
    "SUBTYPE": set().union(*SUBTYPE.values()),
    "TYPE": set().union(*(
        TYPE_POOL.get("IMP", set())
    )),
}

def infer_category_order(source: str | None, target: str | None, change_dict: dict) -> list[str]:
    """
    Infere un orden local de categorías según la posición de sus sufijos
    en las palabras que cambian del target.
    Devuelve una lista de claves de change_dict ordenadas.

    Ajuste importante para EVID:
    - En lugar de buscar mi/m o si/s en cualquier parte del token,
      solo se consideran las alomorfas que aparezcan como sufijo
      al final de la palabra (ignorando puntuación final). Esto
      evita confundir una 'si' o 's' interna de la raíz con el
      sufijo evidencial real.
    """
    if not source or not target or not change_dict:
        return sorted(change_dict.keys())

    src_tokens, _ = _tokenize(source)
    tgt_tokens, _ = _tokenize(target)
    m = min(len(src_tokens), len(tgt_tokens))
    diff_indices = [i for i in range(m) if src_tokens[i] != tgt_tokens[i]]

    if not diff_indices:
        return sorted(change_dict.keys())

    positions: dict[str, int] = {}
    evid_code = change_dict.get("EVID")

    for i in diff_indices:
        tok = tgt_tokens[i]

        # para evidenciales queremos trabajar sobre el token sin puntuación final,
        # porque el sufijo EVID va inmediatamente antes de la puntuación.
        tok_core_for_evid = re.sub(r"[.,;:!?\u00B7]+$", "", tok)

        for cat, surfset in CAT_SURF.items():
            if cat not in change_dict:
                continue

            # para EVID, limitar las superficies a las alomorfas
            # compatibles con el tipo de evidencial del cambio (ATT/REP).
            if cat == "EVID" and evid_code and evid_code in EVID:
                surfset_eff = EVID[evid_code]
            else:
                surfset_eff = surfset

            for mor in surfset_eff:
                if not mor:
                    continue

                # regla robusta para EVID: solo si es sufijo real ---
                if cat == "EVID":
                    # analizar sobre tok_core_for_evid (sin puntuación final)
                    if not tok_core_for_evid.endswith(mor):
                        continue
                    # posición aproximada del inicio del morfema EVID dentro del token
                    pos = len(tok_core_for_evid) - len(mor)
                else:
                    # para las demás categorías seguimos usando la primera ocurrencia
                    pos = tok.find(mor)
                    if pos == -1:
                        continue

                # posición global aproximada: índice de token + offset de carácter
                p = i * 1000 + pos
                if cat not in positions or p < positions[cat]:
                    positions[cat] = p

    keys = list(change_dict.keys())
    with_pos = [k for k in keys if k in positions]
    without_pos = [k for k in keys if k not in positions]

    ordered = sorted(with_pos, key=lambda k: positions[k])
    ordered += sorted(without_pos)
    return ordered

#normalización de morfemas
DASHES = r"[\u2010\u2011\u2012\u2013\u2014\u2212-]"
PUNCT = r"[.,;:!?\u00B7]+"

def canonical_morph(m: str) -> str:
    s = nfc(m)
    # patrones especiales de neg/proh
    if "mana" in s and "chu" in s:
        return "mana … -chu"
    if "ama" in s and "chu" in s:
        return "ama … -chu"
    s = re.sub(DASHES, "", s)
    s = s.replace("¿", "").replace("?", "")
    s = re.sub(PUNCT, "", s)
    s = re.sub(r"\s+", "", s)
    return s or "∅"

def display_combo(morphs: list[str]) -> str:
    safe = [canonical_morph(x) for x in morphs if canonical_morph(x) != "∅"]
    return " - ".join(safe) if safe else "∅"

def normalize_option(opt: str, typ: str | None = None) -> str:
    """
    Normaliza una opción para fines de deduplicación.

    Para todos los tipos (incluyendo NEG/PROH) usamos simplemente
    canonical_morph, de modo que secuencias como 'mana - chka - chu'
    y 'mana - chu' se mantengan diferenciadas.
    """
    return canonical_morph(opt)

def dedupe_by_norm(options, typ: str | None = None):
    seen, unique = set(), []
    for o in options:
        k = normalize_option(o, typ)
        if k == "∅" or k in seen:
            continue
        seen.add(k)
        unique.append(o)
    return unique

# sufijos verbales conocidos para detectar la raíz
VERB_SUFFIX_SET = set()

# persona presente
for s in PERSON_PRESENT.values():
    VERB_SUFFIX_SET |= {canonical_morph(x) for x in s}
# futuro simple
for s in TENSE_FUT_SIM.values():
    VERB_SUFFIX_SET |= {canonical_morph(x) for x in s}
# pasado exp / no exp
VERB_SUFFIX_SET |= {canonical_morph("rqa"), canonical_morph("sqa")}
# aspecto
VERB_SUFFIX_SET |= {canonical_morph("chka")}
# modos
for s in MODE.values():
    VERB_SUFFIX_SET |= {canonical_morph(x) for x in s}
# imperativos (solo sufijos simples)
VERB_SUFFIX_SET |= {
    canonical_morph("y"),
    canonical_morph("chun"),
    canonical_morph("sunchik"),
    canonical_morph("saqku"),
    canonical_morph("ychik"),
    canonical_morph("chunku"),
}

# quitar patrones de neg/proh, que no son sufijos verbales simples
VERB_SUFFIX_SET = {s for s in VERB_SUFFIX_SET if "…" not in s}

KNOWN_VERB_SUFFIXES = sorted(VERB_SUFFIX_SET, key=len, reverse=True)

def find_stem_by_suffix(src_tok: str):
    """
    Intenta separar src_tok en raíz + sufijo verbal conocido.
    Devuelve (stem, sufijo) o (None, None) si no encuentra nada.
    """
    tok = nfc(src_tok)
    for suf in KNOWN_VERB_SUFFIXES:
        if tok.endswith(suf) and len(tok) > len(suf) + 1:
            stem = tok[:-len(suf)]
            return stem, suf
    return None, None

def split_verb_token(tok: str):
    """
    Segmenta un token verbal en:
        raíz + sufijo verbal conocido (+ clítico externo) (+ puntuación final)

    Devuelve (stem, verb_suf, external_clitic, trailing_punct).

    - stem: posible raíz verbal (str) o None si no se reconoció.
    - verb_suf: sufijo verbal (persona/tiempo/modo/aspecto) reconocido.
    - external_clitic: clítico que viene DESPUÉS del complejo verbal (chu, mi, m, si, s).
    - trailing_punct: puntuación final (.,;:!?) si la hay.

    Ejemplos ideales:
        hamunqakuchu. : stem=hamu, verb_suf=nqaku, external_clitic=chu, trailing_punct='.'
        hamunkichu    : stem=hamu, verb_suf=nki,   external_clitic=chu, trailing_punct=''
        wayk'un       : stem=wayk'u, verb_suf=n,   external_clitic='',  trailing_punct=''
    """
    tok = nfc(tok)

    # 1. separar puntuación final
    trailing_punct = ""
    m = re.match(r"^(.*?)([.,;:!?\u00B7]+)$", tok)
    if m:
        core = m.group(1)
        trailing_punct = m.group(2)
    else:
        core = tok

    # 2. separar posible clítico externo (chu, mi/m, si/s) al final
    external_clitic = ""
    base = core
    for encl in ("chu", "mi", "m", "si", "s"):
        if base.endswith(encl) and len(base) > len(encl) + 1:
            base = base[:-len(encl)]
            external_clitic = encl
            break  # solo quitamos un clítico externo

    # 3. buscar el sufijo verbal conocido MÁS LARGO al final de 'base'
    for suf in KNOWN_VERB_SUFFIXES:
        if base.endswith(suf) and len(base) > len(suf) + 1:
            stem = base[:-len(suf)]
            return stem, suf, external_clitic, trailing_punct

    return None, None, external_clitic, trailing_punct

# enmascarado por LCP + sufijos verbales
def _longest_common_prefix(a: str, b: str) -> str:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    if i > 0 and i < n and a[i-1] in "-’'":
        i -= 1
    return a[:i]

def morpheme_gaps_by_lcp(source: str, target: str, change: dict | None = None):
    """
    Enmascara las palabras que cambian entre source y target de forma más robusta.

    - Compara token por token y detecta TODOS los índices donde difieren.
    - Para cada par (src_tok, tgt_tok):
        1) Si hay posesión en change, intenta segmentar usando sufijos posesivos conocidos.
           Si además hay NUMBER:PL, se absorbe también 'kuna' dentro del hueco.
        1bis) Si hay NUMBER:PL + EVID y en el token target aparece 'kuna' y al final
              un evidencial (m/mi, s/si), se segmenta como raíz + 'kuna' + caso + evidencial
              y se ocultan 'kuna' y el evidencial con dos huecos (runa_____ta_____).
        2) Si no, intenta separar raíz + sufijo verbal con un inventario de sufijos
           y clíticos externos (chu, mi/m, si/s), ocultando SOLO el bloque verbal
           del token target (sin solapamientos), permitiendo que el source tenga
           un sufijo de pasado extra (rqa/sqa) en la raíz.
        2bis) Si hay EVID en change y el token target termina en un alomorfo
              evidencial conocido (m/mi, s/si), se oculta el sufijo evidencial,
              y si además hay PERSON_OBJ, se agrupa PERSON_OBJ+EVID como bloque.
        3) En caso general, usa prefijo común + sufijo común para preservar enclíticos
           como -taqa u otros morfemas externos.

    Devuelve:
        masked_sentence: oración target con uno o varios "_____".
        frags: lista con un elemento por gap creado (solo para contar huecos).
    """
    src_tokens, src_spans = _tokenize(source)
    tgt_tokens, tgt_spans = _tokenize(target)

    if not tgt_tokens:
        return target, []

    # índices donde source y target difieren (palabra por palabra)
    m = min(len(src_tokens), len(tgt_tokens))
    diff_indices = [i for i in range(m) if src_tokens[i] != tgt_tokens[i]]

    if not diff_indices:
        # fallback genérico
        return morpheme_gaps_general(source, target)

    # 1. patrones de posesión (a partir de POSS)
    poss = change.get("POSS") if change else None
    number = change.get("NUMBER") if change else None
    poss_patterns: dict[str, str] = {}
    if poss:
        poss_base = {
            "1_SI": ("y", "niy"),
            "2_SI": ("yki", "niyki"),
            "3_SI": ("n", "nin"),
            "1_PL_INC": ("nchik", "ninchik"),
            "1_PL_EXC": ("yku", "niyku"),
            "2_PL": ("ykichik", "niykichik"),
            "3_PL": ("nku", "ninku"),
        }
        if poss in poss_base:
            v_suf, c_suf = poss_base[poss]
            poss_patterns["vowel"] = v_suf
            poss_patterns["cons"] = c_suf

    def _common_suffix(a: str, b: str) -> str:
        n = min(len(a), len(b))
        i = 0
        while i < n and a[-1 - i] == b[-1 - i]:
            i += 1
        if i == 0:
            return ""
        return a[-i:]

    # calcular cuántos huecos se generan
    hidden_slots: list[str] = []

    evid_code = change.get("EVID") if change else None

    def _mask_pair(src_tok: str, tgt_tok: str):
        """
        Decide cómo enmascarar un par (source_token, target_token)
        y registra que se generó un hueco.

        Nota robusta: si este par refleja principalmente un cambio de EVID
        (ej. mi → si al final del token), evitamos aplicar posesión en
        este mismo token para no "robar" una 'y' interna de la raíz.
        """
        # 0. Detectar si este token es principalmente evidencial
        skip_possessive_for_token = False
        if evid_code in EVID:
            # probar alomorfas más largas primero (mi antes que m, si antes que s)
            for ev in sorted(EVID[evid_code], key=len, reverse=True):
                ev = nfc(ev)
                if tgt_tok.endswith(ev) and len(tgt_tok) > len(ev) + 1:
                    # si el source NO termina en esta misma alomorfa,
                    # se asume que se está realizando el cambio de evidencial
                    if not src_tok.endswith(ev):
                        skip_possessive_for_token = True
                    break

        # 1. caso posesión: buscar sufijo posesivo dentro del token target
        # solo aplicamos posesión en este token si NO lo hemos marcado como "evidencial".
        if poss and poss_patterns and not skip_possessive_for_token:
            for suf in poss_patterns.values():
                if not suf:
                    continue
                idx = tgt_tok.find(suf)
                # buscar forma del tipo waka + [y/ykuna/.] + taqa -> waka_____taqa
                if idx > 0:
                    left = tgt_tok[:idx]
                    right = tgt_tok[idx + len(suf):]

                    # si además hay NUMBER:PL y justo después viene 'kuna',
                    # la consideramos también parte del cambio (dentro del hueco)
                    if number == "PL" and right.startswith("kuna"):
                        right = right[len("kuna"):]

                    if left and (right or len(tgt_tok) > len(suf) + 1):
                        hidden_slots.append("SLOT")
                        return left + "_____" + right

        # caso nominal NUMBER:PL + EVID en la misma palabra
        # patrón típico: src: runata  |  tgt: runakunatam
        # Queremos: runa_____ta_____  (kuna y m/mi en los huecos).
        if number == "PL" and evid_code in EVID:
            base = None
            # quitar primero el evidencial al final (m/mi o s/si)
            for ev in sorted(EVID[evid_code], key=len, reverse=True):
                ev = nfc(ev)
                if tgt_tok.endswith(ev) and len(tgt_tok) > len(ev) + 1:
                    base = tgt_tok[:-len(ev)]  # ej. runakunata
                    break

            if base and "kuna" in base:
                idx_kuna = base.find("kuna")
                if idx_kuna > 0:
                    left = base[:idx_kuna]                  # ej. 'runa'
                    right = base[idx_kuna + len("kuna"):]   # ej. 'ta'
                    # verificar que source sea exactamente left+right (ej. runata)
                    if left and right and nfc(left + right) == nfc(src_tok):
                        hidden_slots.append("SLOT")
                        hidden_slots.append("SLOT")
                        return left + "_____" + right + "_____"

        # 2. caso verbal: raíz + sufijo verbal conocido (PERSON/TENSE/MODE/ASPECT)
        # usamos segmentación explícita con split_verb_token para evitar solapamientos
        src_stem, src_vsuf, src_ext, _ = split_verb_token(src_tok)
        tgt_stem, tgt_vsuf, tgt_ext, tgt_punct = split_verb_token(tgt_tok)

        if src_stem and tgt_stem:
            src_root = canonical_morph(src_stem)
            tgt_root = canonical_morph(tgt_stem)

            # si no coinciden exactamente, permitimos que la raíz del source tenga
            # un sufijo de pasado extra ('rqa' o 'sqa') y lo retiramos antes de comparar.
            if src_root != tgt_root:
                for past in ("rqa", "sqa"):
                    if src_root.endswith(past) and len(src_root) > len(past) + 1:
                        base_root = src_root[:-len(past)]
                        if base_root == tgt_root:
                            src_root = base_root
                            break

            if src_root == tgt_root:
                hidden_slots.append("SLOT")
                ext = tgt_ext or ""
                punct = tgt_punct or ""
                stem_for_output = tgt_stem

                # si el cambio es evidencial y el clítico externo es precisamente
                # un evidencial (m/mi/s/si), enmascaramos el clítico, NO el sufijo verbal.
                if evid_code in EVID and ext:
                    evid_set = {canonical_morph(x) for x in EVID[evid_code]}
                    if canonical_morph(ext) in evid_set:
                        base = stem_for_output + (tgt_vsuf or "")
                        return f"{base}_____{punct}"

                # comportamiento estándar: ocultar bloque verbal y preservar clítico externo
                if ext:
                    return f"{stem_for_output}_____{ext}{punct}"
                else:
                    return f"{stem_for_output}_____{punct}"

        # 2. caso evidencial: sufijo m/mi o s/si al final del token
        if evid_code in EVID:
            # probamos las alomorfas más largas primero (mi antes que m, si antes que s)
            for mor in sorted(EVID[evid_code], key=len, reverse=True):
                mor = nfc(mor)
                if tgt_tok.endswith(mor) and len(tgt_tok) > len(mor) + 1:
                    base = tgt_tok[:-len(mor)]

                    # si también hay PERSON_OBJ, intentamos agrupar PERSON_OBJ+EVID
                    # como bloque único a ocultar (ej.: amachawanmi → amacha_____).
                    po_code = change.get("PERSON_OBJ") if change else None
                    if po_code:
                        po_surfs = {"yki", "wanqi", "wan", "ni", "sunki", "nki"}
                        for po_suf in sorted(po_surfs, key=len, reverse=True):
                            if base.endswith(po_suf) and len(base) > len(po_suf) + 1:
                                stem = base[:-len(po_suf)]
                                hidden_slots.append("SLOT")
                                return stem + "_____"

                    # si no hay PERSON_OBJ (o no se detecta sufijo de objeto),
                    # ocultar solo el evidencial como bloque.
                    hidden_slots.append("SLOT")
                    return base + "_____"

        # 3. caso general: prefijo común + sufijo común (para enclíticos tipo -taqa)
        lcp = _longest_common_prefix(src_tok, tgt_tok)
        prefix_len = len(lcp)

        src_tail = src_tok[prefix_len:]
        tgt_tail = tgt_tok[prefix_len:]
        common_tail_suf = _common_suffix(src_tail, tgt_tail)
        suffix_len = len(common_tail_suf)

        central_len = len(tgt_tok) - prefix_len - suffix_len
        if central_len <= 0:
            hidden_slots.append("SLOT")
            if lcp:
                return lcp + "_____"
            else:
                return src_tok + "_____"

        # prefijo (posible raíz) + hueco + sufijo común (enclíticos externos, caso, etc.)
        hidden_slots.append("SLOT")
        return tgt_tok[:prefix_len] + "_____" + tgt_tok[len(tgt_tok) - suffix_len:]

    # 2. reconstruir la oración target con TODOS los tokens distintos enmascarados
    result_parts: list[str] = []
    prev_end = 0
    for idx, span_match in enumerate(tgt_spans):
        start, end = span_match.span()

        # Texto entre tokens (espacios, signos, etc.)
        if prev_end < start:
            result_parts.append(target[prev_end:start])

        tok_str = target[start:end]
        if idx in diff_indices and idx < len(src_tokens):
            masked_tok = _mask_pair(src_tokens[idx], tok_str)
            result_parts.append(masked_tok)
        else:
            result_parts.append(tok_str)

        prev_end = end

    if prev_end < len(target):
        result_parts.append(target[prev_end:])

    masked_sentence = "".join(result_parts)
    masked_sentence = re.sub(r"\s{2,}", " ", masked_sentence).strip()
    masked_sentence = re.sub(r"_+\s+", lambda m: m.group(0).rstrip() + " ", masked_sentence)

    # frags: solo nos interesa saber cuántos slots hay (len(frags) = #gaps)
    frags = hidden_slots[:]  # por ejemplo ["SLOT", "SLOT"] si hay 2 gaps
    return masked_sentence, frags

# derivación EXACTA de la correcta
def compute_correct_morphemes(change_dict: dict) -> list[str] | None:
    person = change_dict.get("PERSON")
    tense  = change_dict.get("TENSE")
    mode   = change_dict.get("MODE")
    typ    = change_dict.get("TYPE")
    aspect = change_dict.get("ASPECT")
    poss   = change_dict.get("POSS")
    number = change_dict.get("NUMBER")
    evid   = change_dict.get("EVID")
    subtype= change_dict.get("SUBTYPE")
    po     = change_dict.get("PERSON_OBJ")

    # Interrogativa
    if subtype == "INT":
        return ["chu"]

    # Negación / Prohibitiva (patrones sintáctico-morfológicos)
    if typ == "NEG":
        return ["mana … -chu"]
    if typ == "PROH":
        return ["ama … -chu"]

    # Posesión + número plural -> combinación de dos morfemas (ej.: y - kuna)
    if poss in POSS_POOL:
        v_final_pref = {
            "1_SI": "y", "2_SI": "yki", "3_SI": "n",
            "1_PL_INC": "nchik", "1_PL_EXC": "yku",
            "2_PL": "ykichik", "3_PL": "nku"
        }
        poss_m = v_final_pref.get(poss, list(POSS_POOL[poss])[0])
        if number == "PL":
            return [poss_m, "kuna"]
        return [poss_m]

    # Número nominal simple
    if number == "PL":
        return ["kuna"]

    # Aspecto
    if aspect == "PRG":
        return ["chka"]

    # Evidenciales
    if evid == "ATT":
        return ["mi"]
    if evid == "REP":
        return ["si"]

    # Imperativo
    if typ == "IMP" and person:
        imp_map = {
            "2_SI": "y", "3_SI": "chun",
            "1_PL_INC": "sunchik", "1_PL_EXC": "saqku",
            "2_PL": "ychik", "3_PL": "chunku",
        }
        if person in imp_map:
            return [imp_map[person]]

    # Modos
    if mode == "POT":
        if person and person in PERSON_PRESENT:
            return ["man", list(PERSON_PRESENT[person])[0]]
        return ["man"]

    if mode == "DUB":
        # Dubitativo: superficie 'manchus' va al final; persona va inmediatamente después de la raíz
        if person and person in PERSON_PRESENT:
            return [list(PERSON_PRESENT[person])[0], "manchus"]
        return ["manchus"]

    # Tiempos
    if tense == "FUT_SIM":
        if person and person in TENSE_FUT_SIM:
            return [list(TENSE_FUT_SIM[person])[0]]
        return ["saq"]

    if tense == "PST_EXP":
        if person and person in PERSON_PRESENT:
            return ["rqa", list(PERSON_PRESENT[person])[0]]
        return ["rqa"]

    if tense == "PST_NEXP":
        if person == "3_SI":
            return ["sqa"]
        if person and person in PERSON_PRESENT:
            return ["sqa", list(PERSON_PRESENT[person])[0]]
        return ["sqa"]

    # Solo persona (presente)
    if person and person in PERSON_PRESENT:
        return [list(PERSON_PRESENT[person])[0]]

    # Persona-objeto
    if po:
        po_map = {
            "1_SI>2_SI": "yki",
            "2_SI>1_SI": "wanqi",
            "3_SI>1_SI": "wan",
            "1_SI>3_SI": "ni",
            "3_SI>2_SI": "sunki",
            "2_SI>3_SI": "nki",
        }
        if po in po_map:
            return [po_map[po]]

    return None

# candidatos para distractores
def candidate_morphemes(change_dict: dict) -> set[str]:
    pool = set()
    person = change_dict.get("PERSON")
    tense  = change_dict.get("TENSE")
    mode   = change_dict.get("MODE")
    typ    = change_dict.get("TYPE")
    aspect = change_dict.get("ASPECT")
    poss   = change_dict.get("POSS")
    number = change_dict.get("NUMBER")
    po     = change_dict.get("PERSON_OBJ")
    evid   = change_dict.get("EVID")
    subtype= change_dict.get("SUBTYPE")

    if person:
        if typ == "IMP":
            pool |= TYPE_POOL["IMP"]
        elif mode == "POT":
            pool |= MODE["POT"] | set().union(*PERSON_PRESENT.values())
        elif mode == "DUB":
            pool |= MODE["DUB"] | set().union(*PERSON_PRESENT.values())
        elif tense == "FUT_SIM":
            pool |= set().union(*TENSE_FUT_SIM.values())
        elif tense == "PST_EXP":
            pool |= PST_EXP_AFFIX | set().union(*PERSON_PRESENT.values())
        elif tense == "PST_NEXP":
            pool |= PST_NEXP_AFFIX | set().union(*PERSON_PRESENT.values())
        else:
            pool |= set().union(*PERSON_PRESENT.values())

    if tense == "FUT_SIM":
        pool |= set().union(*TENSE_FUT_SIM.values())
    elif tense == "PST_EXP":
        pool |= PST_EXP_AFFIX | set().union(*PERSON_PRESENT.values())
    elif tense == "PST_NEXP":
        pool |= PST_NEXP_AFFIX | set().union(*PERSON_PRESENT.values())

    if aspect == "PRG":
        pool |= ASPECT["PRG"]
    if mode in MODE:
        pool |= MODE[mode]
    if typ in TYPE_POOL:
        pool |= TYPE_POOL[typ]
    if subtype == "INT":
        pool |= SUBTYPE["INT"]
    if po:
        pool |= {"yki", "wanqi", "wan", "ni", "sunki", "nki"}
    if poss in POSS_POOL:
        pool |= POSS_POOL[poss]
    if number == "PL":
        pool |= NUMBER["PL"]
    if evid in EVID:
        pool |= EVID[evid]
    return {canonical_morph(m) for m in pool if canonical_morph(m) != "∅"}

def infer_evid_morph_for_item(item, evid_code: str) -> str | None:
    """
    Inferimos la forma superficial del evidencial (m/mi, s/si) mirando
    directamente el par source/target.

    Estrategia:
      - Localizar tokens que cambian entre source_quz y target_quz.
      - Para cada token distinto, buscar qué segmento nuevo se añadió.
      - Si ese segmento coincide con alguna alomorfa registrada en EVID,
        devolvemos su forma canónica (m, mi, s o si).
    """
    src = nfc(item.get("source_quz") or "")
    tgt = nfc(item.get("target_quz") or "")
    src_tokens, _ = _tokenize(src)
    tgt_tokens, _ = _tokenize(tgt)
    m = min(len(src_tokens), len(tgt_tokens))
    if m == 0:
        return None

    if evid_code not in EVID:
        return None

    allowed_raw = EVID[evid_code]
    allowed = {canonical_morph(x) for x in allowed_raw}

    for i in range(m):
        if src_tokens[i] == tgt_tokens[i]:
            continue
        s_tok = nfc(src_tokens[i])
        t_tok = nfc(tgt_tokens[i])

        new_seg = ""

        # caso ideal: el target es source + sufijo nuevo (ej. chukunta → chukuntas)
        if t_tok.startswith(s_tok) and len(t_tok) > len(s_tok):
            new_seg = t_tok[len(s_tok):]
        else:
            # fallback: buscar si el target termina en alguna alomorfa de este evidencial
            for cand in sorted(allowed_raw, key=len, reverse=True):
                if t_tok.endswith(cand):
                    new_seg = cand
                    break

        if not new_seg:
            continue

        new_norm = canonical_morph(new_seg)
        if new_norm in allowed:
            return new_norm

    # si no se encuentra un patrón en la oración, devolvemos None y dejamos que el resto
    # de la lógica haga un fallback.
    return None

# HINTS en español
def make_hints_es(change_obj: str, source_quz: str | None = None, target_quz: str | None = None) -> list[str]:
    d = parse_change_to_dict(change_obj)
    person, tense, mode, typ = d.get("PERSON"), d.get("TENSE"), d.get("MODE"), d.get("TYPE")

    # primero construimos (cat, texto) para cada pista
    records: list[tuple[str, str]] = []

    # número
    if d.get("NUMBER") == "PL":
        records.append(("NUMBER", "Añade **kuna** al sustantivo núcleo."))

    # posesión
    poss = d.get("POSS")
    if poss:
        base = {
            "1_SI": "Si la raíz termina en vocal: **y** | Si termina en consonante: **niy**",
            "2_SI": "Si la raíz termina en vocal: **yki** | Si termina en consonante: **niyki**",
            "3_SI": "Si la raíz termina en vocal: **n** | Si termina en consonante: **nin**",
            "1_PL_INC": "Si la raíz termina en vocal: **nchik** | Si termina en consonante: **ninchik**",
            "1_PL_EXC": "Si la raíz termina en vocal: **yku** | Si termina en consonante: **niyku**",
            "2_PL": "Si la raíz termina en vocal: **ykichik** | Si termina en consonante: **niykichik**",
            "3_PL": "Si la raíz termina en vocal: **nku** | Si termina en consonante: **ninku**",
        }
        if poss in base:
            records.append(("POSS", f"Agregar el adjetivo posesivo: {base[poss]}."))

    # Aspecto
    if d.get("ASPECT") == "PRG":
        records.append(("ASPECT", "Marca progresivo con **chka** en el verbo."))

    # Tipo de frase
    if typ == "NEG":
        records.append(("TYPE", "Usa el patrón **mana … -chu** (conserva los argumentos)."))
    elif typ == "PROH":
        records.append(("TYPE", "Usa el patrón **ama … -chu** (prohibitiva)."))
    elif typ == "IMP":
        imp_map = {
            "2_SI": "**y**", "3_SI": "**chun**",
            "1_PL_INC": "**sunchik**", "1_PL_EXC": "**saqku**",
            "2_PL": "**ychik**", "3_PL": "**chunku**",
        }
        if person in imp_map:
            records.append(("TYPE", f"Imperativo: usa el sufijo {imp_map[person]}."))

        # Modo
    if mode == "POT":
        records.append(("MODE", "Añade **man** (potencial)."))
    elif mode == "DUB":
        records.append(("MODE", "Añade **manchus** (dubitativo)."))

    # Tiempo verbal
    if tense == "FUT_SIM" and person:
        fut_map = {
            "1_SI": "**saq**", "2_SI": "**nki**", "3_SI": "**nqa**",
            "1_PL_INC": "**sunchik**", "1_PL_EXC": "**saqku**",
            "2_PL": "**nkichik**", "3_PL": "**nqaku**",
        }
        if person in fut_map:
            records.append(("TENSE", f"Tiempo Futuro: usa el sufijo {fut_map[person]}."))
    if tense == "PST_EXP" and person:
        records.append(("TENSE", "Pasado experimentado: **rqa** + terminación de persona."))
    if tense == "PST_NEXP" and person:
        if person == "3_SI":
            records.append(("TENSE", "Tiempo Pasado no experimentado: **sqa** (sin **n** en 3ª singular)."))
        else:
            records.append(("TENSE", "Tiempo Pasado no experimentado: **sqa** + terminación de persona."))

    # Presente
    if person and (tense == "PRE_SIM" or (not tense and not mode and typ != "IMP")):
        pres_map = {
            "1_SI": "**ni**", "2_SI": "**nki**", "3_SI": "**n**",
            "1_PL_INC": "**nchik**", "1_PL_EXC": "**yku**",
            "2_PL": "**nkichik**", "3_PL": "**nku**",
        }
        if person in pres_map:
            persona_es = PERSON_ES.get(person, person)
            records.append(
                ("PERSON", f"Tiempo Presente: para {persona_es} usa el sufijo {pres_map[person]}."
            ))

    # Interrogativa
    if d.get("SUBTYPE") == "INT":
        records.append(
            ("SUBTYPE", "Agregar el clítico interrogativo: **chu** (mantener los signos de interrogación: ¿ ?).")
        )

    # Pronombre de Objeto
    if d.get("PERSON_OBJ"):
        po_map = {
            "1_SI>2_SI": "**yki**",
            "2_SI>1_SI": "**wanqi**",
            "3_SI>1_SI": "**wan**",
            "1_SI>3_SI": "**ni**",
            "3_SI>2_SI": "**sunki**",
            "2_SI>3_SI": "**nki**",
        }
        code = d["PERSON_OBJ"]
        mor = po_map.get(code)
        if mor:
            try:
                src, tgt = code.split(">", 1)
                src_es = PERSON_ES.get(src.strip(), src.strip())
                tgt_es = PERSON_ES.get(tgt.strip(), tgt.strip())
                records.append(
                    ("PERSON_OBJ",
                     f"Pronombre de objeto: de {src_es} a {tgt_es}, se agrega el sufijo {mor} en el verbo.")
                )
            except Exception:
                records.append(
                    ("PERSON_OBJ", f"Pronombre de objeto: se agrega el sufijo {mor} en el verbo.")
                )

    # Evidenciales
    if d.get("EVID") == "ATT":
        records.append(("EVID", "Evidencial atestiguativa: tras consonante **mi**, tras vocal **m**."))
    elif d.get("EVID") == "REP":
        records.append(("EVID", "Evidencial reportativa: tras consonante **si**, tras vocal **s**."))

    if not records:
        return []

    # Orden dinámico solo cuando hay ≥2 categorías con pista
    cats_present = [cat for cat, _ in records]
    if source_quz and target_quz and len(set(cats_present)) > 1:
        cat_order = infer_category_order(source_quz, target_quz, d)
        rank = {cat: i for i, cat in enumerate(cat_order)}
        # ordenar manteniendo orden relativo original como desempate
        indexed = list(enumerate(records))
        indexed.sort(key=lambda it: (rank.get(it[1][0], len(cat_order)), it[0]))
        records = [rec for _, rec in indexed]

    return [text for _, text in records]

# opciones (correcta + distractores)
def make_options(item, frags):
    """
    Construye la lista de opciones (correcta + distractores) a partir del cambio
    gramatical.

    - Para NEG/PROH e INT usa comportamientos especiales.
    - Para el resto:
        * compute_correct_morphemes define el/los morfemas correctos.
        * El número de "slots" (huecos) se aproxima por len(frags) cuando aplica.
        * Si hay varios huecos pero un solo morfema, se replica (ej.: yku → yku - yku),
          salvo en los casos donde reconstruimos explícitamente la secuencia
          por categoría (p.ej. EVID + ASPECT, EVID + PERSON_OBJ, EVID + NUMBER,
          EVID + POSS).
        * Si hay varios morfemas pero un solo hueco, se muestran como combo
          "m1 - m2" en una única opción.
    """
    ch = parse_change_to_dict(item.get("change_obj", "{}"))
    typ = ch.get("TYPE")
    subtype = ch.get("SUBTYPE")
    evid = ch.get("EVID")

    # Derivación "teórica" a partir de change_dict
    correct_morphs = compute_correct_morphemes(ch) or []

    # Número aproximado de huecos (slots) a partir del enmascarador
    n_slots = len(frags) if isinstance(frags, list) else 1
    if n_slots < 1:
        n_slots = 1

    # Para categoría INT asumimos siempre un único hueco (solo -chu)
    if subtype == "INT":
        n_slots = 1
    # Para NEG/PROH sabemos que hay dos huecos: mana/ama y bloque verbal (incluye -chu)
    if typ in {"NEG", "PROH"}:
        n_slots = 2

    # ajuste robusto para EVID
    # Queremos:
    #   - EVID solo: morfema correcto = s/si o m/mi según el contexto real.
    #   - EVID + ASPECT:PRG: secuencia [EVID, chka] en orden local.
    #   - EVID + PERSON_OBJ: secuencia [PERSON_OBJ, EVID] en orden local,
    #     mostrada como combo "wan - mi" en un único hueco.
    #   - EVID + NUMBER:PL (nominal): secuencia [kuna, EVID] con 2 huecos.
    #   - EVID + POSS (posesivo): secuencia [POSS, EVID] con 2 huecos (ej.: yki - mi).
    if evid in {"ATT", "REP"}:
        ev_morph = infer_evid_morph_for_item(item, evid)
        if ev_morph:
            ev_morph = canonical_morph(ev_morph)

        other_cats = {k for k in ch.keys() if k not in {"EVID"}}

        # Caso 1: solo evidencialidad (un único cambio categorial)
        if ev_morph and not other_cats:
            correct_morphs = [ev_morph]

        # Caso 2: evidencialidad + aspecto progresivo (dos cambios, típicamente 2 huecos)
        elif ev_morph and other_cats == {"ASPECT"} and ch.get("ASPECT") == "PRG":
            src_q = item.get("source_quz") or ""
            tgt_q = item.get("target_quz") or ""
            cat_order = infer_category_order(src_q, tgt_q, ch)

            seq: list[str] = []
            for cat in cat_order:
                if cat == "EVID":
                    seq.append(ev_morph)
                elif cat == "ASPECT" and ch.get("ASPECT") == "PRG":
                    seq.append("chka")

            if seq:
                correct_morphs = seq
                if n_slots < len(seq):
                    n_slots = len(seq)

        # Caso 3: evidencialidad + pronombre de objeto (PERSON_OBJ)
        elif ev_morph and other_cats == {"PERSON_OBJ"} and ch.get("PERSON_OBJ"):
            src_q = item.get("source_quz") or ""
            tgt_q = item.get("target_quz") or ""
            cat_order = infer_category_order(src_q, tgt_q, ch)

            po_code = ch.get("PERSON_OBJ")
            po_map = {
                "1_SI>2_SI": "yki",
                "2_SI>1_SI": "wanqi",
                "3_SI>1_SI": "wan",
                "1_SI>3_SI": "ni",
                "3_SI>2_SI": "sunki",
                "2_SI>3_SI": "nki",
            }
            po_morph = po_map.get(po_code)

            seq: list[str] = []
            if po_morph:
                for cat in cat_order:
                    if cat == "PERSON_OBJ":
                        seq.append(po_morph)
                    elif cat == "EVID":
                        seq.append(ev_morph)

            if seq:
                correct_morphs = seq
                if n_slots < 1:
                    n_slots = 1

        # Caso 4: evidencialidad + número plural (NUMBER:PL) en la misma palabra nominal
        elif ev_morph and ch.get("NUMBER") == "PL" and other_cats == {"NUMBER"}:
            # Para combos nominales NUMBER+EVID queremos secuencia [kuna, evid]
            # y dos huecos (ej.: runa_____ta_____ con opción "kuna - m").
            correct_morphs = ["kuna", ev_morph]
            if n_slots < 2:
                n_slots = 2

        # Caso 5: evidencialidad + posesión (POSS) → ej. yki + mi
        elif ev_morph and ch.get("POSS") and other_cats == {"POSS"}:
            poss_code = ch.get("POSS")
            # Reutilizamos la misma tabla base que compute_correct_morphemes para POSS
            poss_vowel = {
                "1_SI": "y",
                "2_SI": "yki",
                "3_SI": "n",
                "1_PL_INC": "nchik",
                "1_PL_EXC": "yku",
                "2_PL": "ykichik",
                "3_PL": "nku",
            }
            poss_morph = poss_vowel.get(poss_code)
            if poss_morph:
                src_q = item.get("source_quz") or ""
                tgt_q = item.get("target_quz") or ""
                cat_order = infer_category_order(src_q, tgt_q, ch)

                seq: list[str] = []
                for cat in cat_order:
                    if cat == "POSS":
                        seq.append(poss_morph)
                    elif cat == "EVID":
                        seq.append(ev_morph)

                if seq:
                    correct_morphs = seq
                    # Dos huecos: uno para POSS, otro para EVID.
                    if n_slots < len(seq):
                        n_slots = len(seq)

    # fallback por tipo si no hay morfemas derivados
    if not correct_morphs:
        if subtype == "INT":
            correct_morphs = ["chu"]
        elif typ == "NEG":
            correct_morphs = ["mana", "chu"] if n_slots > 1 else ["mana … -chu"]
        elif typ == "PROH":
            correct_morphs = ["ama", "chu"] if n_slots > 1 else ["ama … -chu"]

    # casos especiales: Categorpía INT
    if subtype == "INT":
        correct = "chu"
        distract = ["chus", "chi", "chuq"]
        opts = dedupe_by_norm([correct] + distract, "INT")[:4]
        random.shuffle(opts)
        answer_idx = opts.index(correct) if correct in opts else 0
        return opts, answer_idx

    # casos especiales: NEG / PROH
    if typ in {"NEG", "PROH"}:
        neg_particle = "mana" if typ == "NEG" else "ama"

        # Quitamos TYPE para derivar otros morfemas (EVID, ASPECT, etc.)
        ch_no_type = {k: v for k, v in ch.items() if k != "TYPE"}
        extra_raw = compute_correct_morphemes(ch_no_type) or []

        evid_code = ch.get("EVID")
        ev_norm = None
        if evid_code in {"ATT", "REP"}:
            ev = infer_evid_morph_for_item(item, evid_code)
            if ev:
                ev_norm = canonical_morph(ev)

        seen = set()
        extra_clean: list[str] = []

        for m in extra_raw:
            cm = canonical_morph(m)
            # si esta entrada corresponde al evidencial genérico (mi/m o si/s),
            # la omitimos y luego añadimos la forma real ev_norm.
            if evid_code == "ATT" and cm in {"mi", "m"}:
                continue
            if evid_code == "REP" and cm in {"si", "s"}:
                continue
            if cm not in seen and cm != "∅":
                seen.add(cm)
                extra_clean.append(cm)

        # añadimos el evidencial real (m/mi o s/si) si lo pudimos inferir
        if ev_norm and ev_norm not in seen:
            extra_clean.append(ev_norm)
            seen.add(ev_norm)

        correct_parts = [neg_particle] + extra_clean + ["chu"]
        correct = display_combo(correct_parts)

        L = len(correct_parts)

        def pick_alt_first(correct0: str) -> str:
            candidates = ["mana", "ama", "y"]
            for c in candidates:
                if c != correct0:
                    return c
            return correct0

        def pick_alt_last(correct_last: str) -> str:
            candidates = ["ni", "rqa", "sqa", "chu"]
            for c in candidates:
                if c != correct_last:
                    return c
            return correct_last

        d1_parts = [pick_alt_first(correct_parts[0])] + correct_parts[1:]
        d2_parts = correct_parts[:-1] + [pick_alt_last(correct_parts[-1])]
        d3_parts = [pick_alt_first(correct_parts[0])] + correct_parts[1:-1] + [pick_alt_last(correct_parts[-1])]

        raw_opts = [
            correct,
            display_combo(d1_parts),
            display_combo(d2_parts),
            display_combo(d3_parts),
        ]

        opts = dedupe_by_norm(raw_opts, typ)[:4]
        random.shuffle(opts)
        answer_idx = opts.index(correct) if correct in opts else 0
        return opts, answer_idx

    # si después de todo no se obtiene nada, devolvemos opciones de relleno seguras
    if not correct_morphs:
        SAFE_FILL = ["ni", "nki", "nchik", "nkichik", "kuna", "chka", "rqa", "sqa", "yku", "nku"]
        random.shuffle(SAFE_FILL)
        opts = SAFE_FILL[:4]
        return opts, 0

    # 1. caso multi-SLOT (varios huecos en la oración)
    if n_slots >= 2:
        canon = [canonical_morph(m) for m in correct_morphs if canonical_morph(m) != "∅"]
        if not canon:
            canon = ["∅"]
        if len(canon) >= n_slots:
            corr_seq = canon[:n_slots]
        else:
            corr_seq = [canon[0]] * n_slots

        corr_tuple = tuple(corr_seq)
        correct = display_combo(list(corr_tuple))

        pool_morphs = candidate_morphemes(ch) or set()
        base = {canonical_morph(m) for m in pool_morphs}
        base |= set(corr_seq)
        base = [m for m in sorted(base) if m != "∅"]

        combos = []
        if n_slots == 2:
            for a in base:
                for b in base:
                    combo = (a, b)
                    if combo == corr_tuple:
                        continue
                    combos.append(display_combo(list(combo)))
        else:
            for a in base:
                combo = tuple([a] * n_slots)
                if combo == corr_tuple:
                    continue
                combos.append(display_combo(list(combo)))

        distract_combos = dedupe_by_norm(combos, typ)
        random.shuffle(distract_combos)
        distract = distract_combos[:3]

        opts = [correct] + distract
        opts = dedupe_by_norm(opts, typ)[:4]
        random.shuffle(opts)
        answer_idx = opts.index(correct) if correct in opts else 0
        return opts, answer_idx

    # 2. caso un solo SLOT (un hueco en la oración)
    # Si hay varios morfemas correctos, se muestran como combo "m1 - m2".
    if len(correct_morphs) >= 2:
        corr_tuple = tuple(canonical_morph(m) for m in correct_morphs)
        correct = display_combo(list(corr_tuple))

        pool_morphs = candidate_morphemes(ch) or set()
        base = {canonical_morph(m) for m in pool_morphs}
        base |= set(corr_tuple)
        base = [m for m in sorted(base) if m != "∅"]

        combos = []
        k = len(corr_tuple)
        for a in base:
            for b in base:
                if k == 2:
                    combo = (a, b)
                else:
                    combo = tuple([a] * (k - 1) + [b])
                if combo == corr_tuple:
                    continue
                combos.append(display_combo(list(combo)))

        distract_combos = dedupe_by_norm(combos, typ)
        random.shuffle(distract_combos)
        distract = distract_combos[:3]

        opts = [correct] + distract
        opts = dedupe_by_norm(opts, typ)[:4]
        random.shuffle(opts)
        answer_idx = opts.index(correct) if correct in opts else 0
        return opts, answer_idx

    # 3. caso simple (un solo morfema y un solo hueco)
    correct = canonical_morph(correct_morphs[0])

    pool = candidate_morphemes(ch) or set()
    pool = {canonical_morph(m) for m in pool}
    pool.discard("∅")
    pool.discard(correct)

    distract = sorted(pool)
    random.shuffle(distract)
    distract = distract[:3]

    opts = [correct] + distract
    opts = dedupe_by_norm(opts, typ)

    SAFE_FILL = ["ni", "nki", "nchik", "nkichik", "kuna", "chka", "rqa", "sqa", "yku", "nku"]
    for s in SAFE_FILL:
        if len(opts) >= 4:
            break
        if canonical_morph(s) not in {canonical_morph(o) for o in opts}:
            opts.append(s)

    opts = opts[:4]
    random.shuffle(opts)
    answer_idx = opts.index(correct) if correct in opts else 0
    return opts, answer_idx

# interfaz
st.title("Ejercicios (Quechua Collao)")
bank = load_bank()

level = st.selectbox("Elige nivel", [1, 2, 3, 4])
pool = [x for x in bank if x.get("level") == level]
if not pool:
    st.warning("No hay ejercicios para este nivel.")
    st.stop()

key_idx = f"idx_level_{level}"
if key_idx not in st.session_state:
    st.session_state[key_idx] = 0

idx = st.session_state[key_idx] % len(pool)
item = pool[idx]

triad_key = item.get("triad") or (
    item["source_quz"] + "|||" +
    item["target_quz"] + "|||" +
    item.get("change_obj", "{}")
)

# Encabezado con contador
st.markdown(
    f"### Ejercicio (Nivel {item.get('level','?')}) — "
    f"#{idx+1} de {len(pool)}"
)

st.write("**Dada la siguiente oración en quechua (quz):**")
st.write(item["source_quz"])
if item.get("source_es"):
    st.caption(item["source_es"])

st.write("**Aplicar el siguiente cambio gramatical:**")
for line in change_lines_es(item.get("change_obj", "{}"), item["source_quz"], item["target_quz"]):
    st.text(line)

ch_dict = parse_change_to_dict(item.get("change_obj", "{}"))
typ = ch_dict.get("TYPE")
subtype = ch_dict.get("SUBTYPE")

# Elección de estrategia de enmascarado
if typ in {"NEG", "PROH"}:
    masked_target, frags = morpheme_gaps_neg_proh(
        item["source_quz"], item["target_quz"], typ, ch_dict
    )
elif subtype == "INT":
    masked_target, frags = morpheme_gaps_int(item["source_quz"], item["target_quz"])
else:
    masked_target, frags = morpheme_gaps_by_lcp(item["source_quz"], item["target_quz"], ch_dict)

st.write("**Oración transformada (completar):**")
st.write(masked_target)
if item.get("target_es"):
    st.caption(item["target_es"])

# Opciones persistentes por ejercicio (triada)
if "opts_store" not in st.session_state:
    st.session_state["opts_store"] = {}

if triad_key not in st.session_state["opts_store"]:
    opts, answer_idx = make_options(item, frags)
    if len(opts) < 4:
        base = ["ni", "nki", "nchik", "nkichik", "kuna", "chka", "rqa", "sqa"]
        for b in base:
            if len(opts) >= 4:
                break
            if b not in opts:
                opts.append(b)
    if answer_idx >= len(opts):
        answer_idx = 0
    st.session_state["opts_store"][triad_key] = (opts, answer_idx)

opts, answer_idx = st.session_state["opts_store"][triad_key]
labels = [f"a) {opts[0]}", f"b) {opts[1]}", f"c) {opts[2]}", f"d) {opts[3]}"]

choice = st.radio("Seleccione una alternativa:", labels, index=0, key=f"choice_{triad_key}")

if st.button("Verificar", key=f"check_{triad_key}"):
    picked = labels.index(choice)
    if picked == answer_idx:
        st.success("✅ ¡Correcto!")
    else:
        st.error("❌ Incorrecto.")
        lines = make_hints_es(item.get("change_obj", "{}"), item["source_quz"], item["target_quz"])
        if lines:
            st.info("**Pistas (HINTS)**\n\n- " + "\n- ".join(lines))
        with st.expander("Ver respuesta"):
            st.write(item["target_quz"])
            if item.get("target_es"):
                st.caption(item["target_es"])

col_a, col_b, _ = st.columns([2, 2, 6])
with col_a:
    if st.button("Anterior"):
        st.session_state[key_idx] = (st.session_state[key_idx] - 1) % len(pool)
        _rerun()
with col_b:
    if st.button("Siguiente"):
        st.session_state[key_idx] = (st.session_state[key_idx] + 1) % len(pool)
        _rerun()