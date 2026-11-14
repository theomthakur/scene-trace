from video_investigator.search.engine import apply, parse_query

ZONES = [{"id": "z1", "name": "Loading dock"}, {"id": "z2", "name": "Pavement strip"}]


def test_recognises_type_class_zone_status_and_time():
    c = parse_query("confirmed person entering the loading dock between 2 and 6 seconds", ZONES)
    assert c.types == {"zone_entry"} and c.classes == {"person"} and c.zone_ids == {"z1"} and c.review_status == {"confirmed"} and (c.after_ms, c.before_ms) == (2000, 6000)
    assert c.notices == [] and not c.is_empty()


def test_blocked_intents_return_notices_not_guesses():
    for q, word in [("unattended bag", "Unattended"), ("who stole the bike", "identify"), ("why did the car stop", "Causal"), ("suspicious person", "intent")]:
        assert any(word.lower() in n.lower() for n in parse_query(q, ZONES).notices), q


def test_unrecognised_text_is_reported_and_yields_nothing():
    c = parse_query("purple elephants dancing", ZONES)
    assert c.is_empty() and "elephants" in c.ignored


def test_apply_filters_orders_by_time_and_limits():
    evs = [{"id": f"e{i}", "type": "zone_entry", "class_name": "person", "zone_id": "z1", "review_status": "unreviewed", "start_ms": s, "end_ms": s + 1000} for i, s in enumerate([5000, 1000, 3000])]
    c = parse_query("person entry", ZONES)
    assert [e["id"] for e in apply(evs, c, 10)] == ["e1", "e2", "e0"] and len(apply(evs, c, 2)) == 2
    assert apply(evs, parse_query("entry before 0.5 s", ZONES), 10) == []
