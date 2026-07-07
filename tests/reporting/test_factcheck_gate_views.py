"""Gate extension: policing agent-curated views on bundle sections.

The curation agent emits only a declarative view-spec (template + column/row
selection + prose captions, NO numeric values). Before any view is rendered, the
deterministic gate must HARD-fail a view that (1) is structurally invalid against
the real ``result.tables`` (bad template / nonexistent column / aggregation /
missing supports_claim / digits in captions), (2) cannot be value-matched — the
numbers the engine would display must come from the source table, never from
agent text, (3) cites a ``supports_claim`` that is not a real claim in the bundle,
or (4) blows the per-domain anti-dump cap (≤2 tables + ≤1 chart).

Each rule gets one FAILING case here; a valid view passes; and the whole gate
never raises on garbage. The pre-existing gate rules stay green (see
``tests/test_reporting_factcheck_gate.py``).
"""
from xhs_ceramics_analytics.reporting.factcheck_gate import run_gate


# ---- fixtures -------------------------------------------------------------

def _facts(**overrides):
    base = {
        "facts_hash": "h",
        "facts": {
            "m.gmv": {"rendered": "¥20.8万", "metric_key": "gmv", "direction": "down",
                      "pool_id": None, "entity_type": None, "evidence_strength": "strong",
                      "descriptive_reliability": "high", "assumption": None},
        },
        "entity_registry": [],
        "absent_link_registry": [],
    }
    base.update(overrides)
    return base


def _tables(**overrides):
    # Numbers live only here; the engine must surface them verbatim, never invent.
    t = {
        "growth_bridge": [
            {"component": "转化", "delta_gmv": 12000, "note": "a"},
            {"component": "流量", "delta_gmv": 8000, "note": "b"},
            {"component": "客单价", "delta_gmv": -3000, "note": "c"},
        ],
    }
    t.update(overrides)
    return t


def _view(**overrides):
    v = {
        "view_id": "core.gmv_bridge_table",
        "section_id": "core_business",
        "supports_claim": "core.gmv_bridge",
        "template": "ranking_table",
        "source": {"task_id": "core_business_diagnosis", "table": "growth_bridge"},
        "columns": ["component", "delta_gmv"],
        "column_labels": {"component": "增长来源", "delta_gmv": "对GMV的拉动"},
        "rows": {},
        "title": "GMV 增长拆解:谁在拉动、谁在抵消",
        "how_to_read": "越靠上影响越大",
        "why_it_matters": "锁定被转化抵消的那一块",
    }
    v.update(overrides)
    return v


def _claim(**kw):
    c = {"claim_id": "core.gmv_bridge", "section_id": "core_business",
         "claim_kind": "measurement", "sentence": "GMV {t0}。",
         "number_tokens": [{"token_id": "t0", "fact_id": "m.gmv",
                            "expected_metric_key": "gmv", "direction": "down"}],
         "entity_refs": [], "confidence": "强", "causal_link": None}
    c.update(kw)
    return c


def _bundle(views, claims=None, **kw):
    claims = [_claim()] if claims is None else claims
    b = {"facts_hash": "h", "headline": "标题。",
         "first_screen": {"spine": [], "panel": [], "actions": []},
         "spine_final": {"backbone": [{"link_id": "L1", "from": "traffic", "to": "gmv",
                                       "anchor_fact_ids": ["m.gmv"],
                                       "relation": "accounting_identity"}]},
         "sections": [{"section_id": "core_business", "title": "大盘", "claims": claims,
                       "curated_views": views, "spine_callbacks": ["L1"]}],
         "cannot_say": []}
    b.update(kw)
    return b


def _codes(report):
    return {f["code"] for f in report.hard_failures}


# ---- passing case ---------------------------------------------------------

def test_valid_curated_view_passes():
    r = run_gate(_bundle([_view()]), _facts(), _tables())
    assert r.status == "PASS"
    assert r.hard_failures == []


def test_two_tables_and_one_chart_is_at_the_cap_and_passes():
    views = [
        _view(view_id="v1", template="ranking_table"),
        _view(view_id="v2", template="comparison_table"),
        _view(view_id="v3", template="share_bar", chart={"x": "component", "y": "delta_gmv"}),
    ]
    r = run_gate(_bundle(views), _facts(), _tables())
    assert r.status == "PASS", r.hard_failures


# ---- rule 1: structural view-spec validation ------------------------------

def test_aggregation_attempt_hard_fails_view_spec():
    # rows may only select/sort/TopN/highlight — an aggregate key is forbidden.
    r = run_gate(_bundle([_view(rows={"aggregate": "sum"})]), _facts(), _tables())
    assert r.status == "FAIL"
    assert "VIEW_SPEC_INVALID" in _codes(r)


def test_nonexistent_column_hard_fails_view_spec():
    r = run_gate(_bundle([_view(columns=["component", "ghost_col"])]), _facts(), _tables())
    assert "VIEW_SPEC_INVALID" in _codes(r)


def test_digit_in_caption_hard_fails_view_spec():
    r = run_gate(_bundle([_view(why_it_matters="被抵消了 9999 元")]), _facts(), _tables())
    assert "VIEW_SPEC_INVALID" in _codes(r)


def test_digit_in_source_task_id_hard_fails_view_spec():
    # source.task_id is free-form agent text rendered verbatim into the provenance
    # footer (来源:… · 证据:…). A fabricated number there must HARD-fail exactly like
    # a digit in a caption — the numeric-trust boundary covers every agent-authored
    # string that reaches the merchant, not just the visible captions.
    r = run_gate(
        _bundle([_view(source={"task_id": "转化拉低GMV约99万", "table": "growth_bridge"})]),
        _facts(), _tables(),
    )
    assert r.status == "FAIL"
    assert "VIEW_SPEC_INVALID" in _codes(r)


def test_real_table_name_with_digit_is_not_false_rejected():
    # A real result.tables key may legitimately contain a digit (e.g.
    # sku_category_l2_mix). source.table is existence-checked, never fabricated, so its
    # digit is a traceable system identifier — it must NOT trip the task_id digit scan.
    tables = {"sku_category_l2_mix": [
        {"component": "转化", "delta_gmv": 12000},
        {"component": "流量", "delta_gmv": 8000},
    ]}
    v = _view(source={"task_id": "sku_structure_diagnosis", "table": "sku_category_l2_mix"},
              columns=["component", "delta_gmv"])
    r = run_gate(_bundle([v]), _facts(), tables)
    assert r.status == "PASS", r.hard_failures


# ---- rule 2: value-match against the source table -------------------------

def test_value_mismatch_hard_fails_when_source_has_no_rows_to_surface():
    # The spec is structurally valid (source table exists, columns are a subset of
    # its union of keys), so VIEW_SPEC_INVALID does NOT fire — but the source table
    # is empty, so the engine surfaces zero source-derived numbers. A view that
    # value-matches nothing cannot back its claim: distinct VIEW_VALUE_MISMATCH.
    r = run_gate(_bundle([_view()]), _facts(), {"growth_bridge": []})
    codes = _codes(r)
    assert r.status == "FAIL"
    assert "VIEW_VALUE_MISMATCH" in codes
    assert "VIEW_SPEC_INVALID" not in codes  # independent of rule 1


# ---- rule 3: supports_claim must reference a real claim --------------------

def test_supports_claim_not_in_bundle_hard_fails():
    r = run_gate(_bundle([_view(supports_claim="core.ghost_claim")]), _facts(), _tables())
    assert r.status == "FAIL"
    assert "VIEW_SUPPORTS_UNKNOWN_CLAIM" in _codes(r)


# ---- rule 4: per-domain anti-dump cap (≤2 tables + ≤1 chart) ---------------

def test_over_cap_three_tables_hard_fails():
    views = [
        _view(view_id="v1", template="ranking_table"),
        _view(view_id="v2", template="comparison_table"),
        _view(view_id="v3", template="ranking_table"),
    ]
    r = run_gate(_bundle(views), _facts(), _tables())
    assert r.status == "FAIL"
    assert "VIEW_OVERCAP" in _codes(r)


def test_over_cap_two_charts_hard_fails():
    views = [
        _view(view_id="c1", template="share_bar", chart={"x": "component", "y": "delta_gmv"}),
        _view(view_id="c2", template="trend_line", chart={"x": "component", "y": "delta_gmv"}),
    ]
    r = run_gate(_bundle(views), _facts(), _tables())
    assert r.status == "FAIL"
    assert "VIEW_OVERCAP" in _codes(r)


# ---- never-raise + backward compatibility ---------------------------------

def test_garbage_curated_views_never_raise():
    for views in (None, "garbage", 42, [None, "x", 7, {}], [{"template": "pie_3d"}]):
        b = _bundle([])
        b["sections"][0]["curated_views"] = views
        r = run_gate(b, _facts(), _tables())  # must not raise
        assert r.status in ("PASS", "FAIL")


def test_backward_compatible_two_arg_call_without_result_tables():
    # Existing callers pass (bundle, facts) with no result_tables; a bundle with no
    # curated_views must behave exactly as before (no new failures).
    b = _bundle([])
    del b["sections"][0]["curated_views"]
    r = run_gate(b, _facts())
    assert r.status == "PASS"
    assert not any(c.startswith("VIEW_") for c in _codes(r))


def test_curated_view_failures_do_not_suppress_existing_rules():
    # A curated-view failure and a pre-existing claim failure coexist in one report.
    bad_claim = _claim(claim_id="core.gmv_bridge",
                       number_tokens=[{"token_id": "t0", "fact_id": "m.ghost",
                                       "expected_metric_key": "gmv", "direction": "down"}])
    r = run_gate(_bundle([_view(rows={"aggregate": "sum"})], claims=[bad_claim]),
                 _facts(), _tables())
    codes = _codes(r)
    assert "VIEW_SPEC_INVALID" in codes
    assert "MISSING_FACT" in codes
