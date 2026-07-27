"""Landing page: the Sim Handicap card's three lines must not collide.

The card carries a number, a status line and a standing "not a USGA index"
caveat, in the narrower two-thirds of row 3. Every one of those can wrap, and
the layout used to place them at fixed offsets off the card's bottom edge — so
in practice the caveat wrapped onto two lines, drew straight through the status
line, and pushed its last word out of the bottom of the card. The number was
sized on width alone, which no realistic handicap ("---", "8.4", "+2.1") ever
exceeds, so it never shrank and simply overlapped whatever sat beneath it.

Nothing caught that because canvas drawing had no test at all: it isn't a
widget tree, so it can't be asserted on by finding children. These render the
real page and compare the drawn items' bounding boxes.
"""
import time

import customtkinter as ctk
import pytest

from data.analytics.handicap import SimHandicap
from data.store import HomeStats, HomeTrends, PlayerRecords
from ui import home_page

DISCLAIMER = "Not a USGA index"


@pytest.fixture
def root():
    try:
        ctk.deactivate_automatic_dpi_awareness()
    except Exception:
        pass
    ctk.set_widget_scaling(1.0)
    ctk.set_window_scaling(1.0)
    try:
        r = ctk.CTk()
    except Exception:
        pytest.skip("no display available for Tk")
    yield r
    try:
        r.destroy()
    except Exception:
        pass


def _render(root, handicap, scale=1.0, size=(1400, 900)):
    """Draw the real landing page and hand back its canvas.

    Clears any previous page first: two pages packed into one root stack, and
    the second lands at a different geometry, which quietly invalidates any
    comparison between two renders.
    """
    for child in root.winfo_children():
        child.destroy()
    # avg_shot_quality is set so the Shot Quality panel draws a number rather
    # than its own "---" placeholder, which would otherwise be a second canvas
    # item with the same text as an unset handicap — and _find would match
    # whichever was drawn first.
    stats = HomeStats(total_shots=879, session_count=15, shots_this_week=25,
                      days_since_last=4, avg_shot_quality=59)
    frame = home_page.build_home_page(
        root, stats, image_path=None, trends=HomeTrends(),
        records=PlayerRecords(handicap=handicap), scale=scale)
    frame.pack(fill="both", expand=True)
    root.geometry(f"{size[0]}x{size[1]}")

    canvas = frame.winfo_children()[0]
    # The redraw is debounced ~90ms behind <Configure>.
    deadline = time.time() + 5
    while time.time() < deadline:
        root.update()
        if _find(canvas, DISCLAIMER) is not None:
            return canvas
        time.sleep(0.05)
    pytest.fail("the landing page never drew the Sim Handicap card")


def _find(canvas, text):
    for i in canvas.find_all():
        if canvas.type(i) == "text" and canvas.itemcget(i, "text") == text:
            return i
    return None


def _box(canvas, text):
    item = _find(canvas, text)
    assert item is not None, f"nothing drawn with the text {text!r}"
    return canvas.bbox(item)


def _overlap(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


NO_VALUE = SimHandicap(eligible_rounds=0)
VERIFIED = SimHandicap(value=8.4, verified=True, eligible_rounds=12, rounds_used=4)
PLUS = SimHandicap(value=-2.1, verified=True, eligible_rounds=20, rounds_used=8)
# The longest status the data layer can produce: still building, and some
# rounds thrown out for mulligans, which appends a second clause.
WORDY = SimHandicap(eligible_rounds=2, excluded_mulligans=3)


@pytest.mark.parametrize("handicap", [NO_VALUE, VERIFIED, PLUS, WORDY],
                         ids=["no-value", "verified", "plus-handicap", "wordy-status"])
@pytest.mark.parametrize("scale", [1.0, 1.5], ids=["100%", "150%"])
def test_the_three_lines_never_overlap(root, handicap, scale):
    canvas = _render(root, handicap, scale=scale)

    value = _box(canvas, handicap.label)
    status = _box(canvas, handicap.status)
    caveat = _box(canvas, DISCLAIMER)

    title = _box(canvas, "Sim handicap")

    assert not _overlap(value, status), "the number is drawn through the status line"
    assert not _overlap(value, caveat), "the number is drawn through the caveat"
    assert not _overlap(status, caveat), "the status line and the caveat collide"
    # Clamping the number away from the captions is only half the job: with no
    # matching floor it just collides with the card's title instead.
    assert not _overlap(value, title), "the number is drawn through the card title"


@pytest.mark.parametrize("handicap", [NO_VALUE, VERIFIED, WORDY],
                         ids=["no-value", "verified", "wordy-status"])
def test_the_caveat_stays_inside_the_card(root, handicap):
    """It used to wrap and drop its last line below the card's bottom edge,
    over the background photo."""
    canvas = _render(root, handicap)

    caveat = _box(canvas, DISCLAIMER)
    # The card bottom isn't introspectable, but the Shot Quality panel beside
    # it shares row 3's height exactly — so its own bottom line is the floor.
    row_floor = _box(canvas, "Average score")[3]

    assert caveat[3] <= row_floor + 4, "the caveat hangs below the row"


def test_the_lines_are_ordered_number_then_status_then_caveat(root):
    canvas = _render(root, VERIFIED)

    assert (_box(canvas, VERIFIED.label)[3]
            <= _box(canvas, VERIFIED.status)[1]
            <= _box(canvas, DISCLAIMER)[1])


def test_the_placeholder_does_not_dominate_the_card(root):
    """"---" is an empty state, not a reading. Sized on width alone it stayed
    at the hero size — three hyphens are never too wide — and rendered as
    heavy bars that read as a rendering fault. It must come out no bigger than
    a real handicap, and well short of the hero number beside it."""
    canvas = _render(root, NO_VALUE)
    blank = _box(canvas, NO_VALUE.label)
    # The Shot Quality score beside it is the app's hero-sized number.
    hero = _box(canvas, "59")

    real = _box(_render(root, VERIFIED), VERIFIED.label)

    assert (blank[3] - blank[1]) <= (real[3] - real[1])
    assert (blank[3] - blank[1]) < (hero[3] - hero[1]), \
        "the empty state is drawn as large as the hero number"
