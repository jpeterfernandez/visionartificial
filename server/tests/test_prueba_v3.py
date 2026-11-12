import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def detection_script(monkeypatch):
    script_path = Path(__file__).parents[1] / "models" / "prueba_v3.py"
    config_path = script_path.with_name("config.json")
    configured_classes = json.loads(config_path.read_text(encoding="utf-8"))["classes"]

    class FakeYOLO:
        def __init__(self, model_path):
            if Path(model_path).name == "yolo26m.pt":
                self.names = {0: "person", 1: "cell phone"}
            else:
                self.names = dict(enumerate(configured_classes))

    monkeypatch.setitem(
        sys.modules, "ultralytics", SimpleNamespace(YOLO=FakeYOLO)
    )
    module_name = "prueba_v3_under_test"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(module_name, None)


def test_tracker_keeps_same_machine_when_box_scale_changes(detection_script):
    script = detection_script
    tracker = script.Tracker()
    confidence = 0.79

    tracker.update(
        [script.Det((100, 100, 300, 300), "chasis_vinilado", confidence)],
        now=1.0,
        conf_start=0.70,
    )
    tracker.update(
        [script.Det((150, 150, 250, 250), "chasis_vinilado", confidence)],
        now=1.1,
        conf_start=0.70,
    )
    visible = tracker.update(
        [script.Det((148, 148, 252, 252), "chasis_vinilado", confidence)],
        now=1.2,
        conf_start=0.70,
    )

    assert len(visible) == 1
    assert visible[0].conf == pytest.approx(confidence)
    assert len(tracker.tracks) == 1
    assert tracker.tracks[0].confirmed


def test_detection_summary_counts_machines_and_vinyl_colors(detection_script):
    script = detection_script
    detections = {
        "camara-1": [
            script.DisplayDetection((0, 0, 10, 10), "vinilado_azul", "chasis_vinilado", "azul"),
            script.DisplayDetection((0, 0, 10, 10), "vinilado_naranja", "chasis_vinilado", "naranja"),
            script.DisplayDetection((0, 0, 10, 10), "base", "chasis_base", None),
        ],
        "camara-2": [
            script.DisplayDetection((0, 0, 10, 10), "puerta", "puerta_inferior", None),
        ],
    }

    summary = script.summarize_detections(detections)

    assert summary == {
        "total_detections": 4,
        "machine_count": 3,
        "color_counts": {
            "naranja": 1,
            "azul": 1,
            "rosado": 0,
            "sin identificar": 1,
        },
    }


def test_composite_rule_labels_parent_with_required_nested_classes(detection_script):
    script = detection_script
    detections = [
        script.DisplayDetection((0, 0, 100, 100), "base", "chasis_base", None, 0.9),
        script.DisplayDetection((10, 10, 40, 40), "panel", "puerta_sup_panel", None, 0.8),
        script.DisplayDetection((50, 50, 80, 80), "chapa", "puerta_sup_chapa", None, 0.85),
    ]

    labeled = script.apply_composite_rules(
        detections,
        [{
            "name": "Chasis armado",
            "parent_class": "chasis_base",
            "required_classes": ["puerta_sup_panel", "puerta_sup_chapa"],
            "exclusive": False,
            "hide_components": True,
        }],
        show_confidence=False,
    )

    assert labeled[0].label == "Chasis armado"
    assert len(labeled) == 1


def test_composite_rule_hides_parts_but_keeps_other_machines_and_external_objects(
    detection_script,
):
    script = detection_script
    detections = [
        script.DisplayDetection((0, 0, 100, 100), "base", "chasis_base", None, 0.9),
        script.DisplayDetection((10, 10, 40, 40), "panel", "puerta_sup_panel", None, 0.8),
        script.DisplayDetection((50, 50, 80, 80), "chapa", "puerta_sup_chapa", None, 0.85),
        script.DisplayDetection((20, 20, 30, 30), "otra", "chasis_vinilado", None, 0.9),
        script.DisplayDetection((120, 120, 150, 150), "puerta", "puerta_inferior", None, 0.8),
    ]

    visible = script.apply_composite_rules(
        detections,
        [{
            "name": "Chasis armado",
            "parent_class": "chasis_base",
            "required_classes": ["puerta_sup_panel", "puerta_sup_chapa"],
            "exclusive": False,
            "hide_components": True,
        }],
        show_confidence=False,
    )

    assert [item.class_name for item in visible] == [
        "chasis_base",
        "chasis_vinilado",
        "puerta_inferior",
    ]


def test_composite_rule_can_keep_nested_detections_visible(detection_script):
    script = detection_script
    detections = [
        script.DisplayDetection((0, 0, 100, 100), "base", "chasis_base", None, 0.9),
        script.DisplayDetection((10, 10, 40, 40), "panel", "puerta_sup_panel", None, 0.8),
        script.DisplayDetection((50, 50, 80, 80), "chapa", "puerta_sup_chapa", None, 0.85),
    ]

    visible = script.apply_composite_rules(
        detections,
        [{
            "name": "Chasis armado",
            "parent_class": "chasis_base",
            "required_classes": ["puerta_sup_panel", "puerta_sup_chapa"],
            "exclusive": False,
            "hide_components": False,
        }],
        show_confidence=False,
    )

    assert [item.label for item in visible] == ["Chasis armado", "panel", "chapa"]


def test_exclusive_composite_rule_rejects_extra_nested_classes(detection_script):
    script = detection_script
    rule = {
        "name": "Chasis doblado",
        "parent_class": "chasis_base",
        "required_classes": ["cavidad_hueca"],
        "exclusive": True,
    }
    detections = [
        script.DisplayDetection((0, 0, 100, 100), "base", "chasis_base", None, 0.9),
        script.DisplayDetection((10, 10, 40, 40), "hueco", "cavidad_hueca", None, 0.8),
    ]

    labeled = script.apply_composite_rules(
        detections, [rule], show_confidence=False
    )
    assert labeled[0].label == "Chasis doblado"

    outside_component = [
        detections[0],
        script.DisplayDetection((110, 110, 140, 140), "hueco", "cavidad_hueca", None, 0.8),
    ]
    labeled = script.apply_composite_rules(
        outside_component, [rule], show_confidence=False
    )
    assert labeled[0].label == "base"

    with_extra_component = detections + [
        script.DisplayDetection((50, 50, 80, 80), "panel", "puerta_sup_panel", None, 0.85),
    ]
    labeled = script.apply_composite_rules(
        with_extra_component, [rule], show_confidence=False
    )
    assert labeled[0].label == "base"


def test_people_tracker_marks_possible_phone_only_after_consecutive_frames(
    detection_script,
):
    script = detection_script
    track = script.Track((0, 0, 100, 200), "person", 0.9, now=1.0)
    phone_box = (40, 20, 50, 30)
    streaks = {}

    people, possible_users, streaks = script.build_people_detections(
        [track], [phone_box], streaks, phone_confirm_frames=3
    )
    assert len(people) == 1
    assert possible_users == 0
    assert "#" not in people[0].label
    assert "90%" in people[0].label
    assert "posible celular" not in people[0].label

    people, possible_users, streaks = script.build_people_detections(
        [track], [phone_box], streaks, phone_confirm_frames=3
    )
    assert possible_users == 0

    people, possible_users, streaks = script.build_people_detections(
        [track], [phone_box], streaks, phone_confirm_frames=3
    )
    assert possible_users == 1
    assert "posible celular" in people[0].label
    assert "#" not in people[0].label


def test_person_tracking_does_not_count_cellphones_as_people(detection_script):
    script = detection_script
    result = SimpleNamespace(boxes=[
        SimpleNamespace(
            cls=script.np.array([0]),
            conf=script.np.array([0.9]),
            xyxy=script.np.array([[0, 0, 100, 200]]),
        ),
        SimpleNamespace(
            cls=script.np.array([1]),
            conf=script.np.array([0.95]),
            xyxy=script.np.array([[40, 20, 50, 30]]),
        ),
    ])
    people, phones = script.split_people_model_result(
        result,
        person_class_id=0,
        phone_class_id=1,
        person_confidence=0.45,
        phone_confidence=0.35,
    )

    assert [person.cls for person in people] == ["person"]
    assert [phone.box for phone in phones] == [(40, 20, 50, 30)]

    people_tracker = script.Tracker()
    visible_people = []
    for frame_number in range(3):
        visible_people = people_tracker.update(
            people,
            now=1.0 + frame_number * 0.1,
            conf_start=0.45,
        )
    assert len(visible_people) == 1
    assert visible_people[0].cls == "person"
    assert script.phone_center_in_person_upper_body(
        phones[0].box, visible_people[0].box
    )
    assert not script.phone_center_in_person_upper_body(
        (110, 150, 120, 160), visible_people[0].box
    )


def test_phone_toggle_changes_yolo_classes_and_persists_config(
    detection_script, monkeypatch
):
    script = detection_script
    people_config = {
        "person_confidence": 0.45,
        "phone_confidence": 0.35,
    }

    enabled_options = script.people_model_prediction_options(
        {"detect_phone": True}, people_config
    )
    disabled_options = script.people_model_prediction_options(
        {"detect_phone": False}, people_config
    )

    assert enabled_options == {"conf": 0.35, "classes": [0, 1]}
    assert disabled_options == {"conf": 0.45, "classes": [0]}
    assert ("detect_phone", "DETECTAR CELULAR") in script.AdminMenu.TOGGLE_BUTTONS

    settings = script.LiveSettings(script.live_from_cfg(script.CFG))
    settings.set("detect_phone", False)
    written_config = {}
    monkeypatch.setattr(
        script, "write_config_file", lambda config: written_config.update(config)
    )
    script.save_config(script.CFG, settings.snapshot())

    assert written_config["people_model"]["detect_phone"] is False
    assert script.live_from_cfg(written_config)["detect_phone"] is False


def test_chassis_model_detections_inside_person_boxes_are_discarded(
    detection_script,
):
    script = detection_script
    person = script.Det((20, 10, 100, 190), "person", 0.92)
    chassis_detections = [
        script.Det((30, 30, 70, 90), "chasis_base", 0.88),
        script.Det((110, 40, 170, 100), "chasis_vinilado", 0.85),
    ]

    remaining = script.exclude_detections_inside_people(
        chassis_detections, [person]
    )

    assert [detection.cls for detection in remaining] == ["chasis_vinilado"]
