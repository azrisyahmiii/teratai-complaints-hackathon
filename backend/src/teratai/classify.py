"""Understand stage (SPEC §4.2): Tier 0 safety rules, Tier 1 TF-IDF + logistic regression, category decision.

Tiers
- Tier 0 (code): scam cues and prompt-injection cues in EN + MS. They never decide alone, except scam
  precedence (decision step 4).
- Tier 1 (code, trained on labels_train.csv): char + word TF-IDF -> LogisticRegression. Confidence threshold
  `tau` is chosen from 5-fold out-of-fold (OOF) probabilities.
- Tier 2 (LLM, C11): `_llm_extract` is the hook. Without it the classifier label stands (decision step 2).

Training-set honesty: for a labelled training complaint, `understand` uses that complaint's OOF probabilities,
never the in-sample model, so train scores are not inflated (env CLASSIFY_USE_OOF=0 turns this off).

CLI: `python -m teratai.classify --cv` retrains, prints OOF accuracy, per-class report, tau, accepted accuracy,
share below tau and train time, and writes `VAR_DIR/classifier.joblib`.
"""

import contextlib
import hashlib
import importlib
import re
import sys
import time
from dataclasses import dataclass
from functools import cache
from typing import Any

import joblib
import numpy as np
from numpy.typing import NDArray
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import FeatureUnion, Pipeline

from teratai import config, data, extract, lang
from teratai.models import Category, ComplaintRow, Emit, Mode, StageEvent, Understanding

TARGET_ACCEPTED_ACCURACY = 0.99  # accepted (conf >= tau) OOF items must be at least this accurate
MAX_BELOW_TAU_SHARE = 0.10  # at most this share of items may fall below tau (goes to the LLM)
SCAM_PRECEDENCE_CONF = 0.95  # step 4: scam cue beats FAILED/UNAUTH labels below this confidence
FOLDS = 5
MODEL_VERSION = 2  # bump when features or hyper-parameters change, so a stale joblib is retrained

NDF = NDArray[np.float64]

# --- Tier 0: safety rules --------------------------------------------------------------------------------
SCAM_CUES = re.compile(
    r"\bpolis\b|\bpolice\b|\bPDRM\b|\bLHDN\b|\bmahkamah\b|\bcourt\b|\bparcel\b|\bbungkusan\b|safe account|"
    r"akaun selamat|\binvest(?:ment|ments|ing|ed|or)?\b|\bpelaburan\b|\bmelabur\b|part[- ]time|kerja sambilan|"
    r"love\s+scam|romance\s+scam|online\s+(?:love|romance|lover|boyfriend|girlfriend)|"
    r"(?:boyfriend|girlfriend|lover)\s+online|\bkekasih\b|teman\s+(?:lelaki|wanita)\s+online|"
    r"fell\s+in\s+love|dating\s+(?:app|site)|met\s+(?:\w+\s+){1,4}?(?:on|via|through)\s+(?:facebook|instagram|tinder|"
    r"telegram|whatsapp|wechat|bumble)|jumpa\s+(?:\w+\s+){1,4}?(?:di|melalui)\s+(?:facebook|instagram|tinder|"
    r"telegram|whatsapp)|online friend|kawan online|\bkenalan\b|\btertipu\b|\bscam\w*|\btipu\b|\bmenipu\b|\bcheated\b|"
    r"\bcrypto\b|\bemergency\b|\bkecemasan\b|money laundering|\bharam\b",
    re.IGNORECASE,
)
INJECTION_CUES = re.compile(
    r"ignore\s+(?:all|any|previous|prior|above|your|the|these)\b|disregard\s+(?:all|any|previous|prior|your|the)\b|"
    r"system\s+prompt|you\s+are\s+now|developer\s+mode|jailbreak|"
    r"abaikan\s+(?:semua\s+)?(?:arahan|peraturan)|refund\s+me\s+RM\s?\d[\d,.]*\s+immediately|"
    r"override\s+(?:the\s+)?(?:policy|rules|instructions)",
    re.IGNORECASE,
)
# Compliment-only text: praise with none of the complaint markers below.
_PRAISE = re.compile(
    r"thank you for (?:the )?(?:great|excellent|good|wonderful)|great service|excellent service|well done|"
    r"terima kasih atas|syabas|perkhidmatan (?:yang )?(?:cemerlang|baik|bagus)|keep it up",
    re.IGNORECASE,
)
_COMPLAINT_MARKER = re.compile(
    r"\bnot\b|\bno\b|\bbut\b|\bhowever\b|\bwrong\b|\bproblem\b|\bcharged\b|\brefund\b|\bfail\w*|\bcomplain\w*|"
    r"\btidak\b|\btak\b|\btetapi\b|\bcaj\w*|\bgagal\b|\bmasalah\b|\bsalah\b|\bRM\s?\d",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Tier0:
    scam_cue: bool
    injection_suspected: bool
    is_complaint: bool


def tier0(row: ComplaintRow) -> Tier0:
    text = f"{row.subject} {row.text}"
    return Tier0(
        scam_cue=SCAM_CUES.search(text) is not None,
        injection_suspected=INJECTION_CUES.search(text) is not None,
        is_complaint=_is_complaint(text),
    )


def _is_complaint(text: str) -> bool:
    """Keep simple: gibberish (no words in either language, short, no amount) or pure praise is not a complaint."""
    toks = lang._tokens(text)
    if len(toks) < 2:
        return False
    en, ms, _ = lang.counts(text)
    if en + ms == 0 and len(toks) <= 8 and not re.search(r"\bRM\s?\d|\bMYR\b", text, re.IGNORECASE):
        return False
    return not (_PRAISE.search(text) and not _COMPLAINT_MARKER.search(text))


# --- Tier 1: TF-IDF + logistic regression ----------------------------------------------------------------


def _text(row: ComplaintRow) -> str:
    return f"{row.subject} {row.text}".strip()


def _build_pipeline() -> Pipeline:
    features = FeatureUnion(
        [
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True)),
            ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True)),
        ]
    )
    return Pipeline(
        [("features", features), ("lr", LogisticRegression(C=10, class_weight="balanced", max_iter=2000))]
    )


@dataclass
class Artifact:
    """What `classifier.joblib` holds."""

    version: int
    fingerprint: str
    pipeline: Pipeline
    classes: list[str]
    tau: float
    oof: dict[str, list[float]]  # oof_key(complaint_id, text) -> probabilities in `classes` order (5-fold, held out)
    stats: dict[str, Any]


def oof_key(complaint_id: str | None, text: str) -> str:
    """Held-out probabilities belong to one training row: its id AND its text. A live row that reuses a training
    ID with different words is a new complaint and gets the live model."""
    return f"{complaint_id}:{hashlib.sha1(text.encode()).hexdigest()[:16]}"


def _training_set() -> tuple[list[str], list[str], list[str]]:
    ids = sorted(data.labels())
    texts = [_text(data.complaint(i)) for i in ids]
    y = [data.labels()[i].category for i in ids]
    return ids, texts, y


def _fingerprint(ids: list[str], texts: list[str], y: list[str]) -> str:
    h = hashlib.sha1(f"v{MODEL_VERSION}".encode())
    for parts in zip(ids, texts, y, strict=True):
        h.update("\x1f".join(parts).encode())
    return h.hexdigest()


def choose_tau(conf: NDF, correct: NDArray[np.bool_]) -> tuple[float, dict[str, float]]:
    """Smallest tau whose accepted items (conf >= tau) are >= 99% accurate with <= 10% of items below tau.

    If no tau meets both, take the smallest tau that meets the accuracy target and report the trade-off.
    """
    n = len(conf)
    best_acc_only: float | None = None
    for tau in np.unique(conf):
        accepted = conf >= tau
        acc = float(correct[accepted].mean())
        below = float((~accepted).sum() / n)
        if acc >= TARGET_ACCEPTED_ACCURACY:
            if below <= MAX_BELOW_TAU_SHARE:
                return float(tau), {"accepted_accuracy": acc, "below_share": below, "both_targets_met": 1.0}
            if best_acc_only is None:
                best_acc_only = float(tau)
    tau = best_acc_only if best_acc_only is not None else float(conf.max())
    accepted = conf >= tau
    return tau, {
        "accepted_accuracy": float(correct[accepted].mean()),
        "below_share": float((~accepted).sum() / n),
        "both_targets_met": 0.0,
    }


def train() -> Artifact:
    """Fit on all labelled complaints, compute 5-fold OOF probabilities and tau, persist to VAR_DIR."""
    t0 = time.perf_counter()
    ids, texts, y = _training_set()
    y_arr = np.array(y)
    pipe = _build_pipeline()
    cv = StratifiedKFold(n_splits=FOLDS, shuffle=True, random_state=0)
    oof: NDF = cross_val_predict(pipe, texts, y_arr, cv=cv, method="predict_proba")
    pipe.fit(texts, y_arr)
    classes = [str(c) for c in pipe.classes_]
    pred = np.array(classes)[oof.argmax(axis=1)]
    conf = oof.max(axis=1)
    correct = pred == y_arr
    tau, tau_stats = choose_tau(conf, correct)
    art = Artifact(
        version=MODEL_VERSION,
        fingerprint=_fingerprint(ids, texts, y),
        pipeline=pipe,
        classes=classes,
        tau=tau,
        oof={oof_key(i, texts[k]): oof[k].tolist() for k, i in enumerate(ids)},
        stats={
            "oof_accuracy": float(correct.mean()),
            "n": len(ids),
            "train_seconds": time.perf_counter() - t0,
            **tau_stats,
        },
    )
    config.VAR_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(art, config.VAR_DIR / "classifier.joblib")
    _artifact.cache_clear()
    return art


@cache
def _artifact() -> Artifact:
    """Load the persisted model; train on first use (or when the data or MODEL_VERSION changed)."""
    ids, texts, y = _training_set()
    path = config.VAR_DIR / "classifier.joblib"
    if path.exists():
        with contextlib.suppress(Exception):  # a corrupt or incompatible file just means: retrain
            art = joblib.load(path)
            if isinstance(art, Artifact) and art.fingerprint == _fingerprint(ids, texts, y):
                return art
    return train()


def tau() -> float:
    return float(config.CLASSIFY_TAU) if config.CLASSIFY_TAU else _artifact().tau


def probabilities(row: ComplaintRow) -> tuple[NDF, bool]:
    """Class probabilities (in `_artifact().classes` order) and whether they are held-out OOF values."""
    art = _artifact()
    if config.CLASSIFY_USE_OOF and oof_key(row.complaint_id, _text(row)) in art.oof:
        return np.array(art.oof[oof_key(row.complaint_id, _text(row))]), True
    return art.pipeline.predict_proba([_text(row)])[0], False


def _top3(probs: NDF, classes: list[str], first: str | None = None) -> list[tuple[Category, float]]:
    order = sorted(range(len(classes)), key=lambda k: -probs[k])
    if first is not None:  # the decided category leads, with its own classifier probability
        order.sort(key=lambda k: classes[k] != first)
    return [(classes[k], round(float(probs[k]), 4)) for k in order[:3]]  # type: ignore[misc]


# --- category decision (SPEC §4.2 steps 1, 2, 4) ---------------------------------------------------------


def decide_category(
    probs: NDF, classes: list[str], scam_cue: bool, threshold: float
) -> tuple[Category, str, str]:
    """(category, source, reason) from classifier probabilities and the Tier 0 scam cue. No LLM here.

    1. conf >= tau and no Tier 0 conflict -> the classifier label.
    2. otherwise the LLM decides (hook, C11); without it the classifier label stands.
    4. scam precedence: a scam cue and a FAILED_TRANSFER / UNAUTHORISED_CARD label below 0.95 -> SCAM_TRANSFER.
    Step 3 (evidence consistency after matching) lives in the pipeline, not here.
    """
    k = int(probs.argmax())
    label, conf = classes[k], float(probs[k])
    if scam_cue and label in ("FAILED_TRANSFER", "UNAUTHORISED_CARD") and conf < SCAM_PRECEDENCE_CONF:
        return "SCAM_TRANSFER", "rules", f"scam cue overrides {label} (conf {conf:.2f} < {SCAM_PRECEDENCE_CONF})"
    conflict = scam_cue and label != "SCAM_TRANSFER"
    if conf >= threshold and not conflict:
        return label, "classifier", f"classifier conf {conf:.2f} >= tau {threshold:.2f}"  # type: ignore[return-value]
    why = "scam cue vs " + label if conflict else f"conf {conf:.2f} < tau {threshold:.2f}"
    return label, "classifier", f"{why}; LLM tier not available, classifier label kept"  # type: ignore[return-value]


def _needs_llm(mode: Mode, probs: NDF, scam_cue: bool, classes: list[str], threshold: float) -> str | None:
    """Why the LLM tier should run (SPEC §4.2 Tier 2), or None. Live: always; batch: low conf or tier conflict."""
    if mode == "live":
        return "live"
    label = classes[int(probs.argmax())]
    if float(probs.max()) < threshold:
        return "low_confidence"
    if scam_cue and label != "SCAM_TRANSFER":
        return "tier_conflict"
    return None


def _llm_extract(row: ComplaintRow, base: Understanding, reason: str) -> Understanding | None:
    """Hook for the LLM extraction tier (C11). Returns None until it is wired in; then `base` is used as is."""
    return None


def understand(row: ComplaintRow, mode: Mode, emit: Emit) -> Understanding:
    t0 = time.perf_counter()
    art = _artifact()
    threshold = tau()
    t0r = tier0(row)
    probs, held_out = probabilities(row)
    category, source, reason = decide_category(probs, art.classes, t0r.scam_cue, threshold)
    language, language_reason = lang.reply_language(row)
    base = Understanding(
        issues=[extract.regex_issue(row, category)],
        top3=_top3(probs, art.classes, first=category),
        source="rules" if source == "rules" else "classifier",
        language=language,
        language_reason=language_reason,
        is_complaint=t0r.is_complaint,
        injection_suspected=t0r.injection_suspected,
        scam_cue=t0r.scam_cue,
    )
    llm_reason = _needs_llm(mode, probs, t0r.scam_cue, art.classes, threshold)
    result = base
    if llm_reason is not None:
        result = _llm_extract(row, base, llm_reason) or base
    emit(
        StageEvent(
            stage="understand",
            ok=True,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            payload={
                "tier": result.source,
                "decision": reason,
                "classifier_top3": _top3(probs, art.classes),
                "tau": round(threshold, 4),
                "oof_probabilities": held_out,
                "llm_reason": llm_reason,
                "llm_used": result.source == "llm",
                "clues": result.issues[0].model_dump(mode="json"),
                "language": result.language,
                "language_reason": result.language_reason,
                "scam_cue": result.scam_cue,
                "injection_suspected": result.injection_suspected,
                "is_complaint": result.is_complaint,
            },
        )
    )
    return result


# --- CLI -------------------------------------------------------------------------------------------------


def _cv_report() -> None:
    art = train()
    ids, texts, y = _training_set()
    classes = art.classes
    probs = np.array([art.oof[oof_key(i, texts[k])] for k, i in enumerate(ids)])
    pred = np.array(classes)[probs.argmax(axis=1)]
    conf = probs.max(axis=1)
    y_arr = np.array(y)
    print(f"OOF accuracy (5-fold, n={len(ids)}): {art.stats['oof_accuracy']:.4f}")
    print(classification_report(y_arr, pred, digits=3))
    print(f"tau = {art.tau:.4f}  (both targets met: {bool(art.stats['both_targets_met'])})")
    print(f"accepted accuracy (conf >= tau): {art.stats['accepted_accuracy']:.4f}  (target >= {TARGET_ACCEPTED_ACCURACY})")
    print(f"share below tau: {art.stats['below_share']:.4f}  (target <= {MAX_BELOW_TAU_SHARE})")
    below = conf < art.tau
    print(f"accuracy of the items below tau: {float((pred == y_arr)[below].mean()) if below.any() else float('nan'):.4f}")
    # Full category decision (tier 0 scam precedence included) on OOF probabilities.
    decided = []
    for k, i in enumerate(ids):
        cat, _, _ = decide_category(probs[k], classes, tier0(data.complaint(i)).scam_cue, art.tau)
        decided.append(cat)
    d_acc = float((np.array(decided) == y_arr).mean())
    print(f"category decision accuracy incl. scam precedence (OOF): {d_acc:.4f}")
    errors = [(i, y[k], decided[k]) for k, i in enumerate(ids) if decided[k] != y[k]]
    print(f"decision errors: {len(errors)}  e.g. {errors[:8]}")
    fp = sum(not tier0(data.complaint(i)).is_complaint for i in ids)
    print(f"labelled complaints flagged is_complaint=False: {fp}/{len(ids)}")
    print(f"train time (CV + final fit): {art.stats['train_seconds']:.1f}s")


if __name__ == "__main__":
    if "--cv" in sys.argv:
        # Import under the package name: classes pickled from `__main__` could not be loaded elsewhere.
        importlib.import_module("teratai.classify")._cv_report()
    else:
        print("usage: python -m teratai.classify --cv")
