from types import SimpleNamespace

from rich.progress import Progress
from rich.text import Text

from sc_crawler.logger import VendorProgressTracker, VoidProgressTracker


def _panel():
    return SimpleNamespace(vendors=Progress(), tasks=Progress(), metadata=Text())


def _tracker(panel, name="Vendor"):
    return VendorProgressTracker(
        vendor=SimpleNamespace(name=name), progress_panel=panel
    )


def test_task_ids_are_not_shared_between_trackers():
    panel = _panel()
    first = _tracker(panel, "First")
    first.start_task("left running", total=None)
    second = _tracker(panel, "Second")
    assert second.task_ids == []
    assert len(first.task_ids) == 1


def test_hide_task_stops_and_unregisters_the_task():
    panel = _panel()
    tracker = _tracker(panel)
    task_id = tracker.start_task("step", total=None)
    tracker.hide_task()
    task = panel.tasks._tasks[task_id]
    assert not task.visible
    assert task.stop_time is not None
    assert tracker.task_ids == []


def test_fail_vendor_hides_tasks_and_stops_the_vendor_timer():
    panel = _panel()
    tracker = _tracker(panel)
    vendor_task_id = tracker.start_vendor(total=14)
    tracker.advance_vendor()
    outer = tracker.start_task("outer", total=None)
    inner = tracker.start_task("inner", total=3)

    tracker.fail_vendor()

    assert tracker.task_ids == []
    for task_id in (outer, inner):
        task = panel.tasks._tasks[task_id]
        assert not task.visible
        assert task.stop_time is not None
    vendor_task = panel.vendors._tasks[vendor_task_id]
    assert vendor_task.fields["step"] == "✘"
    assert vendor_task.stop_time is not None
    assert not vendor_task.finished
    # elapsed time is frozen after the failure
    assert vendor_task.elapsed == vendor_task.stop_time - vendor_task.start_time


def test_fail_vendor_keeps_other_vendors_running():
    panel = _panel()
    failed = _tracker(panel, "Failed")
    failed_id = failed.start_vendor(total=14)
    failed.fail_vendor()
    other = _tracker(panel, "Other")
    other_id = other.start_vendor(total=14)
    other.update_vendor(step="running")
    assert panel.vendors._tasks[other_id].stop_time is None
    assert panel.vendors._tasks[other_id].fields["step"] == "running"
    assert panel.vendors._tasks[failed_id].fields["step"] == "✘"


def test_fail_vendor_before_start_vendor_is_a_noop():
    panel = _panel()
    tracker = _tracker(panel)
    tracker.fail_vendor()
    assert panel.vendors.task_ids == []
    VoidProgressTracker().fail_vendor()
