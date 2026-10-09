"""Independent, fixture-scoped assertions against existing HTTP read contracts."""


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def read_view(get, fixture):
    """get is an ownership-checked GET callback, never an arbitrary target URL."""
    return {
        "catalog": get("/concepts")["concepts"],
        "concepts": {cid: get(f"/concepts/{cid}") for cid in fixture["concepts"]},
        "entries": {eid: get(f"/entries/{eid}") for eid in fixture["entries"]},
        "selections": {eid: get(f"/entries/{eid}/current-extraction")
                       for eid in fixture["entries"]},
        "extractions": {xid: get(f"/extractions/{xid}")
                        for xid in fixture["extractions"]},
        "memberships": {uid: get(f"/knowledge-units/{uid}/concept-membership")
                        for uid in fixture["memberships"]},
        "invalid": {uid: get(f"/knowledge-units/{uid}/invalid")
                    for uid in fixture["memberships"]},
    }


def verify_view(view, expected):
    """History is checked for preservation, never used as CURRENT SAME authority."""
    catalog = view["catalog"]
    ids = [c["id"] for c in catalog]
    require(ids == sorted(set(ids), reverse=True), "catalog order/dedup: expected ID DESC")
    catalog_by_id = {c["id"]: c for c in catalog}
    units = {}
    for xid, source in expected["extractions"].items():
        extraction = view["extractions"][xid]
        require(extraction["id"] == xid, "extraction ID attribution")
        for key, value in source.items():
            if key != "units":
                require(extraction[key] == value, f"extraction {xid}: {key}")
        actual_units = {u["id"]: u for u in extraction["units"]}
        require(set(actual_units) == set(source["units"]), "immutable unit inventory")
        for uid, evidence in source["units"].items():
            for key, value in evidence.items():
                require(actual_units[uid][key] == value, f"unit {uid}: immutable {key}")
            require(uid not in units, "unit belongs to multiple extractions")
            units[uid] = (extraction, actual_units[uid])
    for eid, record in expected["entries"].items():
        actual = view["entries"][eid]
        require(actual["id"] == eid, "source entry ID")
        for key, value in record.items():
            require(actual[key] == value, f"source entry {eid}: {key}")
        require(view["selections"][eid] == expected["selections"][eid], "current selection")
    for uid, target in expected["memberships"].items():
        envelope = view["memberships"][uid]
        require(envelope["unit_id"] == uid, "membership unit attribution")
        membership = envelope["current_membership"]
        actual = membership["concept_id"] if membership else None
        require(actual == target, f"unit {uid}: CURRENT SAME")
        require(view["invalid"][uid]["unit_id"] == uid, "invalid unit attribution")
        require(view["invalid"][uid]["invalid"] == expected["invalid"][uid], "INVALID state")
        require(not (actual is not None and view["invalid"][uid]["invalid"]), "INVALID plus SAME")
    all_links = {}
    for cid, expectation in expected["concepts"].items():
        detail = view["concepts"][cid]
        concept = detail["concept"]
        require(concept["id"] == cid, "concept ID attribution")
        require(catalog_by_id.get(cid) == concept, "catalog/detail disagree")
        require(concept["lifecycle_state"] == "normal", "fixture lifecycle")
        require(concept["preferred_unit_id"] == expectation["preferred_unit_id"], "preferred unit")
        support = []
        for uid, (extraction, unit) in units.items():
            membership = view["memberships"][uid]["current_membership"]
            current = view["selections"][extraction["entry_id"]]["current_extraction_id"]
            if (membership and membership["concept_id"] == cid
                    and current == extraction["id"]
                    and unit["admission"]["effective_state"] == "active"):
                support.append(uid)
        require(sorted(support) == sorted(expectation["supporting_unit_ids"]),
                f"concept {cid}: current supporting fixture units")
        supported = bool(expectation["supporting_unit_ids"])
        require(concept["support_state"] == ("supported" if supported else "orphaned"), "support state")
        require(concept["state"] == ("active" if supported else "orphaned"), "effective state")
        preferred = concept["preferred_unit_id"]
        if preferred is not None:
            require(expected["memberships"].get(preferred) == cid, "preferred is not a current SAME member")
        for link in detail["links"]:
            require(link["concept_id"] == cid, "history concept attribution")
            all_links[link["id"]] = link
    for lid, original in expected["history"].items():
        require(all_links.get(lid) == original, f"immutable history event {lid}")
