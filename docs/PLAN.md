# Fix: Pacing Section NaN JSON Bug

<!-- PHASE:1 -->
## Phase 1: Fix NaN serialization in Pacing API

### Branch
`fix/pacing-nan-json`

### Scope
The pacing endpoint returns invalid JSON because rolling average values are `NaN` for the first rows (not enough data for `min_periods`). These `NaN` literals break JSON parsing in the browser. Additionally, the `_SafeJSONProvider` in `app.py` must be made robust against numpy float types.

Two problems to fix:
1. **Root cause** – in `api_pacing()` (`app.py`), `df["rolling"]` from `.rolling(20, min_periods=5).mean()` still produces `NaN` for the first 4 rows. The `.tolist()` call emits Python `float('nan')` which becomes the invalid JSON literal `NaN`.
2. **Safety net** – `_SafeJSONProvider._sanitize()` must also catch `numpy.float64` NaN (which may not pass the plain `isinstance(obj, float)` check on all platforms) and any other non-finite numeric type.

### Files to Create/Modify
- `app.py` – fix `api_pacing()` splits/consistency rolling lists, harden `_sanitize()`

### Acceptance Criteria
- [ ] `splits_out["rolling"]` list contains no `NaN` or `null` values for the first few rows — rows where rolling has fewer than `min_periods` data points are excluded from the output instead of emitting NaN
- [ ] `consistency_out["rolling"]` has the same guarantee
- [ ] `_sanitize()` explicitly handles `numpy.floating` (via `np.isnan`) so numpy NaN values are also caught
- [ ] `/api/pacing` response is valid JSON parseable by `json.loads()` with no exceptions
- [ ] All other fields in the pacing response (`split_diff`, `pace_std`, `dates`, `distance_km`) are also free of NaN

### Tests Required
- Manual verification: call `json.loads(json.dumps(_sanitize({...})))` with a dict containing `float('nan')` and `np.float64('nan')` — both must become `null`
- Verify `splits_out` and `consistency_out` have no NaN by checking that `df.dropna(subset=["rolling"])` is applied before building the response dicts
<!-- /PHASE:1 -->
