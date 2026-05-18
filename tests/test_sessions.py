from klippyai_agent.sessions import InMemorySessionStore


def test_session_roundtrip() -> None:
    store = InMemorySessionStore(ttl_seconds=60)
    session = store.create()
    assert store.exists(session.session_id)
    loaded = store.get(session.session_id)
    assert loaded is not None
    assert loaded.session_id == session.session_id
