"""Shared statistical core for the RCA tools — the single place hypothesis tests live.

Every RCA tool that claims an *association* between a categorical grouping column
(e.g. process_step) and a binary 0/1 outcome (e.g. defect_label) calls into here,
so the math exists once and cannot drift between tools.

Design (deliberately conservative — the system must never assert a finding the data
does not support):

  * Association is tested PER GROUP as a 2x2 ("this group vs the rest"), NOT as one
    kxN chi-square. This gives a per-group effect size and lets Fisher's exact be a
    *valid* low-count fallback (it is a 2x2 test).
  * Each group reports: n, defect rate, absolute lift vs rest, risk ratio, a Wilson
    95% CI on its rate, a raw two-proportion z p-value (Fisher exact when any cell is
    small), and a Benjamini-Hochberg FDR-adjusted p across the scan family.
  * A group is FLAGGED a candidate cause only if  adjusted_p < alpha  AND
    |lift| >= min_lift. Nothing clearing both bars => a structured "no significant
    association" result, never a fabricated "strongest driver".
  * Degenerate input (any group below MIN_GROUP_N, or zero-variance outcome) returns
    a structured "insufficient/degenerate" result instead of a number.
  * Confounder check (statsmodels logistic) demotes a variable that loses independent
    significance once a correlated co-variate is in the model.

All results are plain dicts with a "kind" discriminator so callers can render either a
finding or an honest null without guessing.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
from scipy import stats as _sp
from statsmodels.stats.proportion import proportions_ztest, proportion_confint
from statsmodels.stats.multitest import multipletests

from core.config import cfg


# --------------------------------------------------------------------------- #
# Result kinds (string discriminators kept stable for callers / the UI)
# --------------------------------------------------------------------------- #
KIND_FINDING = "finding"                 # >=1 group cleared both bars
KIND_NULL = "no_significant_association"  # tested cleanly, nothing significant
KIND_DEGENERATE = "insufficient_data"    # too few rows / zero variance
KIND_INCOMPATIBLE = "incompatible_data"  # columns don't meet the contract


def _wilson_ci(successes: int, n: int, alpha: float) -> tuple[float, float]:
    """Wilson score 95% CI for a binomial proportion (well-behaved at 0/1 and small n)."""
    if n == 0:
        return (0.0, 0.0)
    lo, hi = proportion_confint(successes, n, alpha=alpha, method="wilson")
    return (float(lo), float(hi))


def resolve_outcome(df: pd.DataFrame, outcome_col: str | None) -> tuple[str | None, str | None]:
    """Resolve the binary 0/1 outcome column.

    If outcome_col is given, validate it is 0/1. Else infer the unique column whose
    non-null values are a subset of {0,1}. Returns (col, error) — error is a human
    string when no single valid outcome column can be resolved.
    """
    def _is_binary(s: pd.Series) -> bool:
        v = pd.to_numeric(s, errors="coerce").dropna().unique()
        return len(v) > 0 and set(v).issubset({0, 1})

    if outcome_col:
        if outcome_col not in df.columns:
            return None, f"outcome column '{outcome_col}' not found"
        if not _is_binary(df[outcome_col]):
            return None, f"outcome column '{outcome_col}' is not binary 0/1"
        return outcome_col, None

    cands = [c for c in df.columns if _is_binary(df[c])]
    if len(cands) == 1:
        return cands[0], None
    if not cands:
        return None, "no binary 0/1 outcome column found — pass outcome_col explicitly"
    return None, (f"ambiguous outcome: multiple 0/1 columns {cands} — pass outcome_col explicitly")


def resolve_group(df: pd.DataFrame, group_col: str | None,
                  outcome_col: str | None) -> tuple[str | None, str | None]:
    """Resolve the categorical grouping column.

    If given, validate it exists and is low-cardinality. Else infer a single
    low-cardinality non-numeric column (excluding the outcome). Returns (col, error).
    """
    def _is_group(c: str) -> bool:
        if c == outcome_col:
            return False
        s = df[c]
        nun = s.nunique(dropna=True)
        if nun < 2 or nun > 50:
            return False
        # categorical = non-numeric, OR numeric with very few distinct values
        is_numeric = pd.api.types.is_numeric_dtype(pd.to_numeric(s, errors="coerce"))
        return (not is_numeric) or nun <= 12

    if group_col:
        if group_col not in df.columns:
            return None, f"grouping column '{group_col}' not found"
        if df[group_col].nunique(dropna=True) < 2:
            return None, f"grouping column '{group_col}' has <2 distinct values"
        return group_col, None

    cands = [c for c in df.columns if _is_group(c)]
    # prefer genuinely non-numeric columns when inferring
    non_numeric = [c for c in cands
                   if not pd.api.types.is_numeric_dtype(pd.to_numeric(df[c], errors="coerce"))]
    pick = non_numeric or cands
    if len(pick) == 1:
        return pick[0], None
    if not pick:
        return None, "no categorical grouping column found — pass group_col explicitly"
    return None, f"ambiguous grouping: multiple categorical columns {pick} — pass group_col explicitly"


def group_vs_rest_scan(df: pd.DataFrame, group_col: str, outcome_col: str,
                       alpha: float | None = None, min_lift: float | None = None,
                       min_group_n: int | None = None) -> dict:
    """Run the per-group 2x2 association scan of `group_col` against binary `outcome_col`.

    Returns a structured dict (see KIND_* constants). This is the heart of the honest
    RCA path — it either flags groups with a passing test + effect size, or returns an
    explicit null/degenerate result.
    """
    alpha = cfg.stat_alpha if alpha is None else alpha
    min_lift = cfg.stat_min_lift if min_lift is None else min_lift
    min_group_n = cfg.stat_min_group_n if min_group_n is None else min_group_n

    y = pd.to_numeric(df[outcome_col], errors="coerce")
    work = pd.DataFrame({"g": df[group_col], "y": y}).dropna()
    n_total = len(work)

    # --- degeneracy guards ------------------------------------------------- #
    if n_total < min_group_n:
        return {"kind": KIND_DEGENERATE, "group_col": group_col, "outcome_col": outcome_col,
                "n": n_total,
                "reason": f"only {n_total} usable rows (< MIN_GROUP_N={min_group_n})"}
    if work["y"].nunique() < 2:
        return {"kind": KIND_DEGENERATE, "group_col": group_col, "outcome_col": outcome_col,
                "n": n_total, "overall_rate": float(work["y"].mean()),
                "reason": "outcome has zero variance (all one class) — no association is testable"}

    # Per-group degeneracy: a single small group must NOT force the whole scan to
    # 'insufficient'. Drop groups below MIN_GROUP_N, record them as `dropped_groups`,
    # and test the rest. Only when NOTHING testable remains is the scan degenerate.
    all_groups = list(work["g"].unique())
    dropped = [{"group": str(g), "n": int((work["g"] == g).sum())} for g in all_groups
               if int((work["g"] == g).sum()) < min_group_n]
    groups = [g for g in all_groups if int((work["g"] == g).sum()) >= min_group_n]
    if len(groups) < 2:
        return {"kind": KIND_DEGENERATE, "group_col": group_col, "outcome_col": outcome_col,
                "n": n_total, "dropped_groups": dropped,
                "reason": (f"fewer than 2 groups have >= MIN_GROUP_N={min_group_n} rows "
                           f"(dropped: {[d['group'] for d in dropped]})")}
    # Restrict the working set to the testable groups so rates/p-values are computed
    # group-vs-(other testable groups), not vs. the degenerate remainder.
    work = work[work["g"].isin(groups)]
    n_total = len(work)

    overall_rate = float(work["y"].mean())
    rows = []
    for g in groups:
        in_g = work["g"] == g
        n_g = int(in_g.sum())
        succ_g = int(work.loc[in_g, "y"].sum())
        n_rest = n_total - n_g
        succ_rest = int(work["y"].sum()) - succ_g
        rate_g = succ_g / n_g
        rate_rest = succ_rest / n_rest if n_rest else float("nan")
        lift = rate_g - rate_rest
        rr = (rate_g / rate_rest) if rate_rest > 0 else float("inf")

        # two-proportion z by default; Fisher's exact when any cell is small (<5)
        cells = [succ_g, n_g - succ_g, succ_rest, n_rest - succ_rest]
        if min(cells) < 5:
            _, p_raw = _sp.fisher_exact([[succ_g, n_g - succ_g],
                                         [succ_rest, n_rest - succ_rest]])
            test = "fisher_exact"
        else:
            _, p_raw = proportions_ztest([succ_g, succ_rest], [n_g, n_rest])
            test = "two_proportion_z"
        lo, hi = _wilson_ci(succ_g, n_g, alpha)
        rows.append({"group": str(g), "n": n_g, "defect_rate": rate_g,
                     "ci95": [lo, hi], "lift_vs_rest": lift,
                     "risk_ratio": rr, "p_raw": float(p_raw), "test": test})

    # --- Benjamini-Hochberg FDR across the scan family --------------------- #
    p_raws = [r["p_raw"] for r in rows]
    _, p_adj, _, _ = multipletests(p_raws, alpha=alpha, method="fdr_bh")
    for r, pa in zip(rows, p_adj):
        r["p_adj"] = float(pa)
        r["flagged"] = bool(pa < alpha and abs(r["lift_vs_rest"]) >= min_lift)

    rows.sort(key=lambda r: r["p_adj"])
    flagged = [r for r in rows if r["flagged"]]
    family_size = len(rows)
    base = {"group_col": group_col, "outcome_col": outcome_col, "n": n_total,
            "overall_rate": overall_rate, "family_size": family_size,
            "alpha": alpha, "min_lift": min_lift, "scan": rows,
            "dropped_groups": dropped}

    if flagged:
        return {**base, "kind": KIND_FINDING, "flagged": flagged}
    smallest = min(rows, key=lambda r: r["p_adj"])
    return {**base, "kind": KIND_NULL,
            "smallest_p_adj": smallest["p_adj"], "closest_group": smallest["group"]}


# --------------------------------------------------------------------------- #
# Row scope — a VALIDATED structured filter applied in pandas (never raw SQL).   #
# --------------------------------------------------------------------------- #
def _norm_token(v) -> str:
    """Normalise a scope value/cell for tolerant matching: lowercase, strip, and keep
    only alphanumerics (so 'LOT_A', 'lot a', 'Lot-A', 'A' all reduce comparably).
    Purely structural — no hardcoded values or formats."""
    import re
    return re.sub(r'[^a-z0-9]', '', str(v).strip().lower())


def _resolve_value(col_values, wanted_raw):
    """Map a requested scope value to an ACTUAL value present in the column, tolerantly:
    exact → case/format-insensitive (normalised) → unique suffix/substring match. Returns
    the real value, or None if it cannot be resolved unambiguously. Data-driven: the truth
    is whatever values the column actually holds, in whatever format."""
    actual = list(dict.fromkeys(col_values))           # unique, order-preserving
    # 1. exact
    if wanted_raw in actual:
        return wanted_raw
    nw = _norm_token(wanted_raw)
    if not nw:
        return None
    norm_map = {}
    for a in actual:
        norm_map.setdefault(_norm_token(a), a)
    # 2. exact normalised ('A' vs 'a', 'LOT_A' vs 'lot a')
    if nw in norm_map:
        return norm_map[nw]
    # 3. requested is a SUFFIX/substring of exactly one actual ('A' -> 'LOT_A'),
    #    or an actual is a substring of the request — but only if UNAMBIGUOUS.
    cands = [a for na, a in norm_map.items() if na.endswith(nw) or nw.endswith(na)
             or nw in na or na in nw]
    return cands[0] if len(cands) == 1 else None


def apply_scope(df: pd.DataFrame, scope) -> tuple[pd.DataFrame, list[str], str | None]:
    """Restrict `df` to rows matching a structured scope, injection-safe.

    `scope` is one filter `{"column": str, "values": [...]}` or a LIST of such filters
    (AND-combined). Column names are validated against df.columns. VALUES are matched
    TOLERANTLY against the column's real values (exact → case/format-insensitive →
    unambiguous substring), so a request for 'A', 'LOT_A', 'lot a', or 'Lot-A' all hit
    the actual value whatever its stored format. If a value cannot be resolved, the error
    LISTS the real available values so the caller can self-correct instead of guessing.
    No value or format is ever hardcoded. Returns (filtered_df, labels, error).
    """
    if not scope:
        return df, [], None
    filters = scope if isinstance(scope, list) else [scope]
    out = df
    labels = []
    for f in filters:
        if not isinstance(f, dict):
            return df, [], f"invalid scope entry (expected {{column, values}}): {f!r}"
        col = f.get("column")
        vals = f.get("values")
        if not col or col not in df.columns:
            return df, [], (f"scope column '{col}' not found; available columns: "
                            f"{', '.join(map(str, df.columns))}")
        if vals is None:
            return df, [], f"scope for '{col}' has no values"
        vals = vals if isinstance(vals, (list, tuple, set)) else [vals]
        col_values = out[col].astype(str).tolist()
        resolved, unresolved = [], []
        for v in vals:
            r = _resolve_value(col_values, str(v))
            (resolved.append(r) if r is not None else unresolved.append(str(v)))
        if unresolved:
            available = list(dict.fromkeys(col_values))
            shown = ", ".join(map(str, available[:20])) + (" …" if len(available) > 20 else "")
            return df, [], (f"scope value(s) {unresolved} not found in '{col}'. "
                            f"Real values in '{col}': {shown}. "
                            "Use one of these exact values (do not guess the format).")
        mask = out[col].astype(str).isin(set(resolved))
        out = out[mask]
        labels.append(f"{col}={'|'.join(map(str, resolved))}")
    return out, labels, None


# --------------------------------------------------------------------------- #
# Within-scope univariate parameter -> outcome driver test                      #
# (the search confounder_check is NOT: which single parameter is associated     #
#  with the outcome, over a given row subset.)                                  #
# --------------------------------------------------------------------------- #
def _is_id_like(s: pd.Series, n_rows: int, ratio: float = 0.9) -> bool:
    """Data-driven id/near-unique test (no hardcoded column names).

    An identifier (e.g. wafer_id) is near-unique AND integer-valued — it enumerates
    rows. A continuous process parameter is *also* high-cardinality (many distinct
    floats) but is NOT integer-valued, so cardinality alone would wrongly drop real
    parameters. We therefore require BOTH: near-unique (distinct/rows >= ratio, or a
    unique key) AND all-integer values. Schema-agnostic; no column names."""
    vals = s.dropna()
    if len(vals) == 0:
        return True
    nun = vals.nunique()
    near_unique = nun >= len(vals) or (nun / max(1, n_rows)) >= ratio
    if not near_unique:
        return False
    # integer-valued? (ids are ints; continuous parameters carry a fractional part)
    frac = (vals - np.floor(vals)).abs()
    all_integer = bool((frac < 1e-9).all())
    return all_integer


def _numeric_param_cols(df: pd.DataFrame, outcome_col: str, group_col: str | None,
                        candidates=None) -> list[str]:
    """Continuous parameter columns eligible as drivers: numeric, not the outcome,
    not the grouping column, not (near-)binary/constant, and not id/near-unique.
    Schema-agnostic. An explicit `candidates` list is honoured but still filtered for
    id-likeness so a passed id column can't poison the family."""
    n_rows = len(df)
    cols = candidates if candidates else list(df.columns)
    out = []
    for c in cols:
        if c not in df.columns or c == outcome_col or c == group_col:
            continue
        s = pd.to_numeric(df[c], errors="coerce")
        if not pd.api.types.is_numeric_dtype(s):
            continue
        nun = s.dropna().nunique()
        if nun < 3:                      # binary/constant -> not a continuous driver
            continue
        if _is_id_like(s, n_rows):       # wafer_id and friends -> not a parameter
            continue
        out.append(c)
    return out


def driver_scan(df: pd.DataFrame, outcome_col: str, params=None, group_col=None,
                alpha: float | None = None, min_lift: float | None = None,
                min_group_n: int | None = None) -> dict:
    """Test which CONTINUOUS parameter is associated with the binary outcome over
    the rows in `df` (already scoped by the caller). For each candidate parameter we
    split rows at the median (high vs low half) and run the same 2x2 machinery as
    group_vs_rest_scan: lift, Wilson CI, two-proportion z / Fisher, BH-FDR across the
    parameter family. Returns the same `kind` discriminator so callers render a
    finding / null / insufficient identically.

    Surviving (flagged) parameters that are mutually correlated are then handed to
    confounder_check so a flagged-but-confounded parameter is demoted honestly.
    """
    alpha = cfg.stat_alpha if alpha is None else alpha
    min_lift = cfg.stat_min_lift if min_lift is None else min_lift
    min_group_n = cfg.stat_min_group_n if min_group_n is None else min_group_n

    y = pd.to_numeric(df[outcome_col], errors="coerce")
    base_n = int(y.notna().sum())
    if base_n < min_group_n:
        return {"kind": KIND_DEGENERATE, "outcome_col": outcome_col, "n": base_n,
                "reason": f"only {base_n} usable rows (< MIN_GROUP_N={min_group_n})"}
    if y.dropna().nunique() < 2:
        return {"kind": KIND_DEGENERATE, "outcome_col": outcome_col, "n": base_n,
                "overall_rate": float(y.mean()),
                "reason": "outcome has zero variance (all one class) — no driver is testable"}

    cand = _numeric_param_cols(df, outcome_col, group_col, params)
    if not cand:
        return {"kind": KIND_INCOMPATIBLE, "outcome_col": outcome_col, "n": base_n,
                "reason": "no continuous parameter columns to test"}

    rows = []
    for p in cand:
        x = pd.to_numeric(df[p], errors="coerce")
        sub = pd.DataFrame({"x": x, "y": y}).dropna()
        if len(sub) < min_group_n or sub["x"].nunique() < 3 or sub["y"].nunique() < 2:
            continue
        med = float(sub["x"].median())
        hi = sub["x"] > med
        if hi.sum() < min_group_n or (~hi).sum() < min_group_n:
            continue
        succ_hi, n_hi = int(sub.loc[hi, "y"].sum()), int(hi.sum())
        succ_lo, n_lo = int(sub.loc[~hi, "y"].sum()), int((~hi).sum())
        rate_hi = succ_hi / n_hi
        rate_lo = succ_lo / n_lo
        lift = rate_hi - rate_lo
        cells = [succ_hi, n_hi - succ_hi, succ_lo, n_lo - succ_lo]
        if min(cells) < 5:
            _, p_raw = _sp.fisher_exact([[succ_hi, n_hi - succ_hi],
                                         [succ_lo, n_lo - succ_lo]])
            test = "fisher_exact"
        else:
            _, p_raw = proportions_ztest([succ_hi, succ_lo], [n_hi, n_lo])
            test = "two_proportion_z"
        lo_ci, hi_ci = _wilson_ci(succ_hi, n_hi, alpha)
        rows.append({"param": p, "split": "median", "threshold": med,
                     "rate_high": rate_hi, "rate_low": rate_lo,
                     "ci95_high": [lo_ci, hi_ci], "lift_high_vs_low": lift,
                     "p_raw": float(p_raw), "test": test})

    if not rows:
        return {"kind": KIND_DEGENERATE, "outcome_col": outcome_col, "n": base_n,
                "reason": "no parameter had two halves each >= MIN_GROUP_N to test"}

    p_raws = [r["p_raw"] for r in rows]
    _, p_adj, _, _ = multipletests(p_raws, alpha=alpha, method="fdr_bh")
    for r, pa in zip(rows, p_adj):
        r["p_adj"] = float(pa)
        r["flagged"] = bool(pa < alpha and abs(r["lift_high_vs_low"]) >= min_lift)
    rows.sort(key=lambda r: r["p_adj"])
    flagged = [r for r in rows if r["flagged"]]

    base = {"outcome_col": outcome_col, "n": base_n, "family_size": len(rows),
            "alpha": alpha, "min_lift": min_lift, "scan": rows, "group_col": group_col}

    if not flagged:
        smallest = min(rows, key=lambda r: r["p_adj"])
        return {**base, "kind": KIND_NULL,
                "smallest_p_adj": smallest["p_adj"], "closest_param": smallest["param"]}

    # Confounder pass: among flagged params, demote any that loses independent
    # significance against a correlated co-flagged param (reuse confounder_check).
    verdicts = {r["param"]: "independently predictive" for r in flagged}
    names = [r["param"] for r in flagged]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            cc = confounder_check(df, outcome_col, names[i], names[j])
            if cc.get("kind") == "confounder_result":
                for v, verdict in cc["verdicts"].items():
                    if verdict == "confounded — not independently predictive":
                        verdicts[v] = verdict
    for r in flagged:
        r["confounder_verdict"] = verdicts.get(r["param"], "independently predictive")
    independent = [r for r in flagged if r["confounder_verdict"] == "independently predictive"]
    return {**base, "kind": KIND_FINDING, "flagged": flagged,
            "independent": independent}


def render_driver(res: dict) -> str:
    """Render a driver_scan result as concise honest text (mirrors render_scan)."""
    k = res.get("kind")
    if k == KIND_INCOMPATIBLE:
        return f"No driver test possible: {res.get('reason')}."
    if k == KIND_DEGENERATE:
        return (f"Insufficient/degenerate data for a within-scope driver test "
                f"({res.get('reason')}). No driver reported.")
    oc = res["outcome_col"]
    scope_note = f" within {res['group_col']}" if res.get("group_col") else ""
    hdr = (f"Parameter drivers of '{oc}'{scope_note} — n={res['n']}, "
           f"family={res['family_size']} params (median split, BH-FDR, "
           f"alpha={res['alpha']}, min_lift={res['min_lift']}):")
    lines = [hdr]
    for r in res["scan"]:
        mark = "  *FLAGGED*" if r.get("flagged") else ""
        cv = f" [{r['confounder_verdict']}]" if r.get("confounder_verdict") else ""
        lines.append(
            f"  {r['param']}: rate_high={r['rate_high']:.3f} vs rate_low={r['rate_low']:.3f}, "
            f"lift={r['lift_high_vs_low']:+.3f}, p_adj={r['p_adj']:.2e}{mark}{cv}")
    if k == KIND_FINDING:
        ind = res.get("independent") or []
        if ind:
            names = ", ".join(f"{r['param']} (lift {r['lift_high_vs_low']:+.3f}, "
                              f"p_adj {r['p_adj']:.2e})" for r in ind)
            lines.append(f"\nIndependently predictive{scope_note}: {names}. "
                         "Association only — confirm mechanism before causal claims.")
        else:
            lines.append(f"\nParameters passed the test but were demoted as confounded; "
                         "none is independently predictive.")
    else:
        lines.append(
            f"\nNo parameter independently predictive: none cleared adjusted "
            f"p<{res['alpha']} AND |lift|>={res['min_lift']}. "
            f"Smallest adjusted p={res['smallest_p_adj']:.2e} ({res['closest_param']}).")
    return "\n".join(lines)


def confounder_check(df: pd.DataFrame, outcome_col: str, var_a: str, var_b: str,
                     corr_threshold: float | None = None, ridge: float | None = None) -> dict:
    """Decide whether var_a / var_b is confounded by the other.

    Only meaningful when the two are correlated (>= corr_threshold). Fits a logistic
    `outcome ~ z(var_a) + z(var_b)` and reports which retains independent significance.
    A variable significant marginally but not in the joint model is "confounded —
    not independently predictive".
    """
    corr_threshold = cfg.stat_confounder_corr if corr_threshold is None else corr_threshold
    ridge = cfg.stat_logistic_ridge if ridge is None else ridge

    sub = df[[outcome_col, var_a, var_b]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(sub) < cfg.stat_min_group_n:
        return {"kind": KIND_DEGENERATE, "reason": "too few complete rows for confounder check"}
    r = float(sub[var_a].corr(sub[var_b]))
    if not np.isfinite(r) or abs(r) < corr_threshold:
        return {"kind": "not_confounded", "pair_corr": r,
                "reason": f"|corr|={abs(r):.2f} < threshold {corr_threshold}; "
                          "no conditioning needed (independent signals)"}

    import statsmodels.api as sm
    z = (sub[[var_a, var_b]] - sub[[var_a, var_b]].mean()) / sub[[var_a, var_b]].std(ddof=0)
    X = sm.add_constant(z)
    y = sub[outcome_col].astype(float)
    try:
        import warnings
        from statsmodels.tools.sm_exceptions import PerfectSeparationError
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                res = sm.Logit(y, X).fit(disp=0)
            except (PerfectSeparationError, np.linalg.LinAlgError, Exception):
                # clean/separable signal — tiny L2 ridge keeps the fit finite
                res = sm.Logit(y, X).fit_regularized(alpha=ridge, L1_wt=0.0, disp=0)
        pvals = {v: float(res.pvalues[v]) for v in (var_a, var_b)}
        coefs = {v: float(res.params[v]) for v in (var_a, var_b)}
    except Exception as e:  # PerfectSeparationError, convergence, etc. — demote gracefully
        return {"kind": "confounder_inconclusive", "pair_corr": r, "error": str(e),
                "reason": "logistic conditioning did not converge; cannot assert independence"}

    alpha = cfg.stat_alpha
    verdicts = {}
    for v, other in ((var_a, var_b), (var_b, var_a)):
        if pvals[v] >= alpha and pvals[other] < alpha:
            verdicts[v] = "confounded — not independently predictive"
        elif pvals[v] < alpha:
            verdicts[v] = "independently predictive"
        else:
            verdicts[v] = "not significant"
    return {"kind": "confounder_result", "pair_corr": r,
            "coefficients": coefs, "p_values": pvals, "verdicts": verdicts}


# --------------------------------------------------------------------------- #
# Rendering — turn a structured result into the brief, honest text a tool returns
# --------------------------------------------------------------------------- #
def render_scan(res: dict) -> str:
    """Format a scan result as concise engineering text. Honest by construction:
    a null result renders as an explicit null, never as a softened finding."""
    k = res.get("kind")
    if k == KIND_INCOMPATIBLE:
        return f"Incompatible data: {res.get('reason', 'columns do not meet the contract')}."
    if k == KIND_DEGENERATE:
        return (f"Insufficient/degenerate data for '{res.get('outcome_col')}' by "
                f"'{res.get('group_col')}': {res.get('reason')}. No association reported.")
    gc, oc = res["group_col"], res["outcome_col"]
    hdr = (f"Association of '{gc}' with '{oc}' — n={res['n']}, overall rate "
           f"{res['overall_rate']:.3f}, family={res['family_size']} groups "
           f"(BH-FDR, alpha={res['alpha']}, min_lift={res['min_lift']}):")
    lines = [hdr]
    for r in res["scan"]:
        mark = "  *FLAGGED*" if r.get("flagged") else ""
        lines.append(
            f"  {r['group']}: rate={r['defect_rate']:.3f} "
            f"[{r['ci95'][0]:.3f},{r['ci95'][1]:.3f}], lift={r['lift_vs_rest']:+.3f}, "
            f"RR={r['risk_ratio']:.2f}, p_adj={r['p_adj']:.2e}{mark}")
    if k == KIND_FINDING:
        names = ", ".join(f"{r['group']} (lift {r['lift_vs_rest']:+.3f}, "
                          f"p_adj {r['p_adj']:.2e})" for r in res["flagged"])
        lines.append(f"\nAssociated with elevated '{oc}': {names}. "
                     "Association only — confirm mechanism/confounders before causal claims.")
    else:  # KIND_NULL
        lines.append(
            f"\nNo statistically significant association: no group cleared "
            f"adjusted p<{res['alpha']} AND |lift|>={res['min_lift']}. "
            f"Smallest adjusted p={res['smallest_p_adj']:.2e} ({res['closest_group']}). "
            "No root cause is supported by this data.")
    dropped = res.get("dropped_groups") or []
    if dropped:
        names = ", ".join(f"{d['group']} (n={d['n']})" for d in dropped)
        lines.append(f"Not tested (below MIN_GROUP_N): {names}.")
    return "\n".join(lines)
