from io import StringIO

from dependency_check import check_dependencies, progress_bar


def test_progress_bar_represents_completed_items():
    assert progress_bar(0, 4, width=8) == "[--------]"
    assert progress_bar(2, 4, width=8) == "[####----]"
    assert progress_bar(4, 4, width=8) == "[########]"


def test_dependency_check_shows_each_completed_dependency():
    output = StringIO()

    assert check_dependencies(
        (("first", "First"), ("second", "Second")),
        importer=lambda name: object(),
        output=output,
    )

    rendered = output.getvalue()
    assert "[1/2] Loading First..." in rendered
    assert "[2/2] Ready Second" in rendered
    assert "Backend dependencies ready" in rendered


def test_dependency_check_identifies_failed_dependency():
    output = StringIO()

    def failing_importer(name):
        raise ImportError("missing runtime")

    assert not check_dependencies(
        (("broken", "Broken package"),),
        importer=failing_importer,
        output=output,
    )
    assert "FAILED Broken package" in output.getvalue()
    assert "missing runtime" in output.getvalue()
