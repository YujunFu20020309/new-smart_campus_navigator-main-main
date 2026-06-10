from streamlit.testing.v1 import AppTest


def test_streamlit_only_displays_fixed_walking_profile():
    app = AppTest.from_file("app.py").run(timeout=30)

    assert len(app.exception) == 0
    captions = [item.value for item in app.caption]
    assert "OSRM 模式：walking（固定）" in captions
    assert all(item.label != "OSRM profile" for item in app.selectbox)
    route_mode = next(item for item in app.selectbox if item.label == "路線模式")
    assert route_mode.options == ["OSRM 路線", "校園路線", "雨天路線", "路線比較"]
