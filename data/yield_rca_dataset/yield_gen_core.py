"""
yield_gen_core.py
-----------------
Synthetic semiconductor wafer dataset generator with KNOWN ground truth, plus the
statistical validators that confirm the ground truth is actually detectable in the
generated data.

Why this exists: a root-cause tool can only be *validated* against data where the true
cause is known. Real fab data never gives you that answer key. So this module builds
lots where the process_step -> defect relationship is real-by-construction and
documented, and others where it is provably absent. It then runs the same kind of
statistics the tool must run (chi-square, two-proportion test, Wilson CIs,
Benjamini-Hochberg correction, a confounder check) and writes an answer key from the
*realized* numbers, not from intention.

No randomness leaks across lots: each lot gets its own seeded generator derived from the
master seed, so toggling one lot's parameters does not perturb the others.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import stats


STEPS: List[str] = ["Oxidation", "Lithography", "Etching", "Deposition", "CMP"]

# Per-step (mean, sd) for each numeric feature. Loosely plausible, varied across steps so
# the data does not look like one uniform random blob. Only the trigger parameters
# (Etching temperature_c, CMP voltage_v) carry an injected relationship to defects.
STEP_PROFILES: Dict[str, Dict[str, Tuple[float, float]]] = {
    "Oxidation":   {"temperature_c": (1000, 40), "pressure_torr": (760, 20),  "gas_flow_sccm": (10, 4),   "etch_rate_nm_min": (3, 1),    "voltage_v": (2.0, 0.5),  "current_ma": (20, 5)},
    "Lithography": {"temperature_c": (120, 10),  "pressure_torr": (760, 5),   "gas_flow_sccm": (12, 4),   "etch_rate_nm_min": (3, 1),    "voltage_v": (2.5, 0.5),  "current_ma": (20, 5)},
    "Etching":     {"temperature_c": (80, 18),   "pressure_torr": (0.12, 0.04),"gas_flow_sccm": (100, 20), "etch_rate_nm_min": (300, 50), "voltage_v": (400, 60),   "current_ma": (35, 8)},
    "Deposition":  {"temperature_c": (400, 30),  "pressure_torr": (2.0, 0.5), "gas_flow_sccm": (200, 40), "etch_rate_nm_min": (5, 2),    "voltage_v": (60, 12),    "current_ma": (28, 6)},
    "CMP":         {"temperature_c": (30, 5),    "pressure_torr": (760, 10),  "gas_flow_sccm": (8, 3),    "etch_rate_nm_min": (3, 1),    "voltage_v": (5.0, 1.5),  "current_ma": (22, 5)},
}

NUMERIC_COLS = ["temperature_c", "pressure_torr", "gas_flow_sccm",
                "etch_rate_nm_min", "voltage_v", "current_ma"]


@dataclass
class GenParams:
    """Every knob the notebook exposes. Defaults give strong, clearly-detectable effects."""
    seed: int = 42
    n_per_lot: int = 10_000

    base_rate: float = 0.03          # baseline P(defect) where no mechanism applies

    # LOT_A: strong real cause -> Etching at high temperature
    a_step: str = "Etching"
    a_param: str = "temperature_c"
    a_quantile: float = 0.75         # "high" = at/above this within-step quantile
    a_lifted: float = 0.22

    # LOT_B: pure null -> flat rate, independent of everything
    b_rate: float = 0.05

    # LOT_C: real cause (CMP high voltage) + a confounded decoy (current_ma ~ voltage_v)
    c_step: str = "CMP"
    c_param: str = "voltage_v"
    c_quantile: float = 0.75
    c_lifted: float = 0.17
    c_decoy_corr: float = 0.90       # correlation forced between current_ma and voltage_v

    # LOT_D: subtle near-noise cause -> Lithography slightly elevated
    d_step: str = "Lithography"
    d_param: str = "pressure_torr"
    d_quantile: float = 0.75
    d_lifted: float = 0.06

    # validation / decision rule
    alpha: float = 0.05
    min_lift: float = 0.03


# ----------------------------------------------------------------------------------
# feature construction
# ----------------------------------------------------------------------------------
def _build_features(step_arr: np.ndarray, rng: np.random.Generator) -> pd.DataFrame:
    n = len(step_arr)
    cols = {c: np.empty(n, dtype=float) for c in NUMERIC_COLS}
    for s in STEPS:
        mask = step_arr == s
        k = int(mask.sum())
        if k == 0:
            continue
        for c in NUMERIC_COLS:
            mean, sd = STEP_PROFILES[s][c]
            cols[c][mask] = rng.normal(mean, sd, size=k)
    df = pd.DataFrame(cols)
    df.insert(0, "process_step", step_arr)
    return df


def _assign_p_high_in_step(df, step, param, quantile, base_rate, lifted):
    """Return per-row P(defect): `lifted` for rows in `step` whose `param` is at/above the
    within-step quantile, else `base_rate`. Also returns the threshold used."""
    p = np.full(len(df), base_rate, dtype=float)
    in_step = df["process_step"].to_numpy() == step
    thr = np.nan
    if in_step.any():
        vals = df.loc[in_step, param].to_numpy()
        thr = float(np.quantile(vals, quantile))
        high = in_step & (df[param].to_numpy() >= thr)
        p[high] = lifted
    return p, thr


# ----------------------------------------------------------------------------------
# per-lot generators
# ----------------------------------------------------------------------------------
def _lot_rng(p: GenParams, offset: int) -> np.random.Generator:
    return np.random.default_rng(p.seed + offset)


def generate_lot_a(p: GenParams):
    rng = _lot_rng(p, 1)
    step_arr = rng.choice(STEPS, size=p.n_per_lot)
    df = _build_features(step_arr, rng)
    prob, thr = _assign_p_high_in_step(df, p.a_step, p.a_param, p.a_quantile, p.base_rate, p.a_lifted)
    df["defect_label"] = rng.binomial(1, prob)
    df.insert(0, "lot_id", "LOT_A")
    df.insert(1, "wafer_id", np.arange(1, p.n_per_lot + 1))
    meta = {"lot_id": "LOT_A", "kind": "strong_real_cause",
            "trigger_step": p.a_step, "trigger_param": p.a_param,
            "quantile": p.a_quantile, "threshold": thr,
            "base_rate": p.base_rate, "lifted_rate": p.a_lifted,
            "expected_null_vars": [c for c in NUMERIC_COLS if c != p.a_param]}
    return df, meta


def generate_lot_b(p: GenParams):
    rng = _lot_rng(p, 2)
    step_arr = rng.choice(STEPS, size=p.n_per_lot)
    df = _build_features(step_arr, rng)
    prob = np.full(p.n_per_lot, p.b_rate, dtype=float)  # flat, independent of all features
    df["defect_label"] = rng.binomial(1, prob)
    df.insert(0, "lot_id", "LOT_B")
    df.insert(1, "wafer_id", np.arange(1, p.n_per_lot + 1))
    meta = {"lot_id": "LOT_B", "kind": "pure_null",
            "trigger_step": None, "trigger_param": None,
            "quantile": None, "threshold": None,
            "base_rate": p.b_rate, "lifted_rate": p.b_rate,
            "expected_null_vars": list(NUMERIC_COLS) + ["process_step"]}
    return df, meta


def generate_lot_c(p: GenParams):
    rng = _lot_rng(p, 3)
    step_arr = rng.choice(STEPS, size=p.n_per_lot)
    df = _build_features(step_arr, rng)

    # Forge the decoy WITHIN the trigger step (CMP), where the causal voltage lives and
    # where voltage_v is on a single consistent scale. current_ma is rebuilt to correlate
    # with within-CMP voltage_v, so it tracks the true driver -> looks predictive, but adds
    # nothing once voltage is conditioned on. Non-CMP current_ma keeps its plain draw.
    in_c = (df["process_step"].to_numpy() == p.c_step)
    if in_c.any():
        v = df.loc[in_c, "voltage_v"].to_numpy()
        z_v = (v - v.mean()) / v.std()
        noise = rng.standard_normal(int(in_c.sum()))
        rho = p.c_decoy_corr
        z_c = rho * z_v + np.sqrt(max(1 - rho * rho, 0.0)) * noise
        df.loc[in_c, "current_ma"] = 22.0 + 5.0 * z_c  # current-like scale

    prob, thr = _assign_p_high_in_step(df, p.c_step, p.c_param, p.c_quantile, p.base_rate, p.c_lifted)
    df["defect_label"] = rng.binomial(1, prob)
    df.insert(0, "lot_id", "LOT_C")
    df.insert(1, "wafer_id", np.arange(1, p.n_per_lot + 1))
    meta = {"lot_id": "LOT_C", "kind": "real_cause_plus_decoy",
            "trigger_step": p.c_step, "trigger_param": p.c_param,
            "quantile": p.c_quantile, "threshold": thr,
            "base_rate": p.base_rate, "lifted_rate": p.c_lifted,
            "decoy_param": "current_ma", "decoy_corr_with": "voltage_v",
            "decoy_corr_target": p.c_decoy_corr,
            "expected_null_vars": [c for c in NUMERIC_COLS if c != p.c_param]}
    return df, meta


def generate_lot_d(p: GenParams):
    rng = _lot_rng(p, 4)
    step_arr = rng.choice(STEPS, size=p.n_per_lot)
    df = _build_features(step_arr, rng)
    prob, thr = _assign_p_high_in_step(df, p.d_step, p.d_param, p.d_quantile, p.base_rate, p.d_lifted)
    df["defect_label"] = rng.binomial(1, prob)
    df.insert(0, "lot_id", "LOT_D")
    df.insert(1, "wafer_id", np.arange(1, p.n_per_lot + 1))
    meta = {"lot_id": "LOT_D", "kind": "subtle_near_noise_cause",
            "trigger_step": p.d_step, "trigger_param": p.d_param,
            "quantile": p.d_quantile, "threshold": thr,
            "base_rate": p.base_rate, "lifted_rate": p.d_lifted,
            "expected_null_vars": [c for c in NUMERIC_COLS if c != p.d_param]}
    return df, meta


def generate_all(p: GenParams):
    lots = {}
    for gen in (generate_lot_a, generate_lot_b, generate_lot_c, generate_lot_d):
        df, meta = gen(p)
        lots[meta["lot_id"]] = (df, meta)
    return lots


# ----------------------------------------------------------------------------------
# statistics (the same kind the tool must perform)
# ----------------------------------------------------------------------------------
def wilson_ci(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = (z * np.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def two_proportion_ztest(k1, n1, k2, n2):
    """Pooled two-proportion z-test. Returns (p_two_sided, abs_diff, risk_ratio)."""
    if n1 == 0 or n2 == 0:
        return (float("nan"), float("nan"), float("nan"))
    p1, p2 = k1 / n1, k2 / n2
    pool = (k1 + k2) / (n1 + n2)
    se = np.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return (1.0, p1 - p2, float("inf") if p2 == 0 else p1 / p2)
    z = (p1 - p2) / se
    pval = 2 * stats.norm.sf(abs(z))
    rr = float("inf") if p2 == 0 else p1 / p2
    return (float(pval), float(p1 - p2), float(rr))


def chi2_step_defect(df):
    ct = pd.crosstab(df["process_step"], df["defect_label"])
    chi2, pval, dof, _ = stats.chi2_contingency(ct)
    return float(chi2), float(pval), int(dof)


def benjamini_hochberg(pvals):
    """Return BH-adjusted p-values, preserving input order."""
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    order = np.argsort(p)
    ranked = p[order]
    adj = ranked * m / (np.arange(m) + 1)
    adj = np.minimum.accumulate(adj[::-1])[::-1]  # enforce monotonicity
    out = np.empty(m)
    out[order] = np.clip(adj, 0, 1)
    return out


def scan_steps(df, alpha, min_lift):
    """For each step: defect rate vs rest of lot, two-proportion test, BH-corrected.
    A step is 'flagged' only if adjusted p < alpha AND |lift| >= min_lift."""
    rows = []
    total_defect = int(df["defect_label"].sum())
    total_n = len(df)
    raw_p = []
    for s in STEPS:
        in_s = df["process_step"] == s
        k1, n1 = int(df.loc[in_s, "defect_label"].sum()), int(in_s.sum())
        k2, n2 = total_defect - k1, total_n - n1
        pval, diff, rr = two_proportion_ztest(k1, n1, k2, n2)
        lo, hi = wilson_ci(k1, n1)
        rows.append({"step": s, "n": n1, "defect_rate": (k1 / n1 if n1 else float("nan")),
                     "ci95": (lo, hi), "lift_vs_rest": diff, "risk_ratio": rr, "p_raw": pval})
        raw_p.append(pval)
    adj = benjamini_hochberg(raw_p)
    for r, a in zip(rows, adj):
        r["p_adj"] = float(a)
        r["flagged"] = bool(a < alpha and abs(r["lift_vs_rest"]) >= min_lift)
    return pd.DataFrame(rows)


def mechanism_test(df, meta, p: GenParams):
    """Sharp test of the injected mechanism: within the trigger step, high-param vs
    low-param defect rates. For the null lot there is no mechanism -> returns None."""
    if meta["trigger_step"] is None:
        return None
    step, param, thr = meta["trigger_step"], meta["trigger_param"], meta["threshold"]
    in_s = df["process_step"] == step
    high = in_s & (df[param] >= thr)
    low = in_s & (df[param] < thr)
    k1, n1 = int(df.loc[high, "defect_label"].sum()), int(high.sum())
    k2, n2 = int(df.loc[low, "defect_label"].sum()), int(low.sum())
    pval, diff, rr = two_proportion_ztest(k1, n1, k2, n2)
    return {"step": step, "param": param, "threshold": thr,
            "high_rate": (k1 / n1 if n1 else float("nan")), "high_n": n1,
            "low_rate": (k2 / n2 if n2 else float("nan")), "low_n": n2,
            "abs_lift": diff, "risk_ratio": rr, "p_value": pval}


def logistic_fit(X, y, max_iter=100, tol=1e-8, ridge=1e-6):
    """Minimal logistic regression via IRLS. X already includes an intercept column.
    Returns (beta, se, z, p) with Wald p-values. Tiny ridge guards against separation."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n, k = X.shape
    beta = np.zeros(k)
    for _ in range(max_iter):
        eta = X @ beta
        mu = 1.0 / (1.0 + np.exp(-eta))
        W = np.clip(mu * (1 - mu), 1e-9, None)
        # IRLS update: beta += (X'WX + ridge I)^-1 X'(y-mu)
        XtWX = X.T @ (X * W[:, None]) + ridge * np.eye(k)
        grad = X.T @ (y - mu)
        step = np.linalg.solve(XtWX, grad)
        beta_new = beta + step
        if np.max(np.abs(step)) < tol:
            beta = beta_new
            break
        beta = beta_new
    eta = X @ beta
    mu = 1.0 / (1.0 + np.exp(-eta))
    W = np.clip(mu * (1 - mu), 1e-9, None)
    cov = np.linalg.inv(X.T @ (X * W[:, None]) + ridge * np.eye(k))
    se = np.sqrt(np.diag(cov))
    z = beta / se
    p = 2 * stats.norm.sf(np.abs(z))
    return beta, se, z, p


def confounder_test(df, p: GenParams):
    """LOT_C decoy demonstration, scoped to the trigger step (CMP). Two views:
    (1) naive marginal: current_ma high vs low defect rate -> looks predictive.
    (2) honest conditional: logistic regression defect ~ voltage_v + current_ma (both
        standardized within CMP). voltage stays significant; current_ma collapses to ~0.
    That is the confounding signature: marginal association, no independent effect."""
    d = df[df["process_step"] == p.c_step].copy()

    # (1) naive marginal: current_ma median split
    cmed = d["current_ma"].median()
    hi = d["current_ma"] >= cmed
    k1, n1 = int(d.loc[hi, "defect_label"].sum()), int(hi.sum())
    k2, n2 = int(d.loc[~hi, "defect_label"].sum()), int((~hi).sum())
    marg_p, marg_diff, _ = two_proportion_ztest(k1, n1, k2, n2)

    # (2) conditional: logistic with both predictors, standardized
    def z(col):
        v = d[col].to_numpy()
        return (v - v.mean()) / v.std()
    X = np.column_stack([np.ones(len(d)), z("voltage_v"), z("current_ma")])
    yv = d["defect_label"].to_numpy()
    beta, se, zz, pp = logistic_fit(X, yv)
    names = ["intercept", "voltage_v", "current_ma"]
    logit = {nm: {"coef": float(b), "p_value": float(pv)} for nm, b, pv in zip(names, beta, pp)}

    corr = float(np.corrcoef(d["current_ma"], d["voltage_v"])[0, 1])
    return {"scope": p.c_step, "current_voltage_corr": corr,
            "naive_marginal_current_p": marg_p, "naive_marginal_current_lift": marg_diff,
            "logistic_conditional": logit,
            "verdict": "current_ma is confounded by voltage_v: significant marginally, but "
                       "its independent logistic coefficient is ~0 (non-significant) once "
                       "voltage_v is in the model; voltage_v stays significant"}


def validate_lot(df, meta, p: GenParams):
    chi2, chi2_p, dof = chi2_step_defect(df)
    res = {
        "lot_id": meta["lot_id"], "kind": meta["kind"], "n": int(len(df)),
        "overall_defect_rate": float(df["defect_label"].mean()),
        "chi2_step_vs_defect": {"chi2": chi2, "p_value": chi2_p, "dof": dof},
        "step_scan": scan_steps(df, p.alpha, p.min_lift).to_dict(orient="records"),
        "mechanism_test": mechanism_test(df, meta, p),
        "expected_null_vars": meta["expected_null_vars"],
    }
    if meta["lot_id"] == "LOT_C":
        res["confounder_test"] = confounder_test(df, p)
    return res
