"""Assertions for the implemented FLH-034 wire contract; no fixture generation."""


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def check_search(data, ids, tokens=None, tiers=None, limit=20, total=None):
    require(data["schema_version"] == "knowledge_library_search_v1", "search schema")
    require([r["concept"]["id"] for r in data["results"]] == ids, "search IDs/order")
    require(data["limit"] == limit, "search limit")
    total = len(ids) if total is None else total
    require(data["total_matches"] == total, "total matches")
    require(data["truncated"] == (total > limit), "truncation")
    if tokens is not None:
        require(data["tokens"] == tokens, "normalized tokens")
    if tiers is not None:
        require([r["match_tier"] for r in data["results"]] == tiers, "match tiers")
    for result in data["results"]:
        fields = result["matched_fields"]
        require(fields == sorted(set(fields)), "matched fields sorted/unique")
        require(result["supporting_unit_count"] <= result["current_member_count"], "support/member counts")


def check_detail(data, supporting, members=(), relations=(), historical=(), preferred=None):
    require(data["schema_version"] == "knowledge_library_concept_v1", "detail schema")
    groups = [data["supporting_units"], data["non_supporting_members"],
              [r["unit"] for r in data["current_relations"]],
              [h["unit"] for h in data["historical_units"]]]
    for group, expected in zip(groups, (supporting, members, relations, historical)):
        require(sorted(u["unit_id"] for u in group) == sorted(expected), "detail section membership")
    flat = [u["unit_id"] for group in groups for u in group]
    require(len(flat) == len(set(flat)), "each Unit appears in exactly one section")
    actual_preferred = data["preferred_unit"]["unit_id"] if data["preferred_unit"] else None
    require(actual_preferred == preferred, "preferred representation")
    require(data["concept"]["preferred_unit_id"] == preferred, "preferred ID parity")
    for unit in data["supporting_units"]:
        require(unit["in_current_extraction"] and unit["admission"] == "active", "support qualification")
    for unit in data["non_supporting_members"]:
        require(not unit["in_current_extraction"] or unit["admission"] != "active", "non-support reason")
