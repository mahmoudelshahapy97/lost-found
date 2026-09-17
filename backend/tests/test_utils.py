"""Geometry, colour and vector helper tests."""

import numpy as np
import pytest

from app.utils.color_utils import color_agreement, dominant_color
from app.utils.geometry_utils import (
    box_gap,
    box_in_polygon,
    centroid,
    centroid_distance,
    clamp_box,
    iou,
    point_in_polygon,
)
from app.utils.vector_utils import from_pgvector, to_pgvector


# ------------------------------------------------------------------- geometry
def test_centroid():
    assert centroid((0.0, 0.0, 10.0, 20.0)) == (5.0, 10.0)


def test_iou_identical_boxes_is_one():
    box = (0.0, 0.0, 10.0, 10.0)
    assert iou(box, box) == pytest.approx(1.0)


def test_iou_disjoint_boxes_is_zero():
    assert iou((0.0, 0.0, 10.0, 10.0), (50.0, 50.0, 60.0, 60.0)) == 0.0


def test_iou_half_overlap():
    assert iou((0.0, 0.0, 10.0, 10.0), (5.0, 0.0, 15.0, 10.0)) == pytest.approx(1 / 3)


def test_box_gap_is_zero_when_boxes_overlap():
    assert box_gap((0.0, 0.0, 10.0, 10.0), (5.0, 5.0, 15.0, 15.0)) == 0.0


def test_box_gap_measures_edge_distance():
    # A tall person next to a small bag: edges are 10 px apart even though the
    # centroids are much further, which is why owner association uses the gap.
    assert box_gap((0.0, 0.0, 10.0, 10.0), (20.0, 0.0, 30.0, 100.0)) == pytest.approx(10.0)
    assert centroid_distance((0.0, 0.0, 10.0, 10.0), (20.0, 0.0, 30.0, 100.0)) > 45.0


def test_point_in_polygon():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert point_in_polygon((5.0, 5.0), square)
    assert not point_in_polygon((15.0, 5.0), square)


def test_degenerate_polygon_accepts_everything():
    assert point_in_polygon((999.0, 999.0), [])
    assert point_in_polygon((999.0, 999.0), [(0.0, 0.0), (1.0, 1.0)])


def test_box_in_polygon_uses_the_centroid():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert box_in_polygon((4.0, 4.0, 6.0, 6.0), square)
    assert not box_in_polygon((40.0, 40.0, 60.0, 60.0), square)


def test_clamp_box_keeps_crops_inside_the_frame():
    clamped = clamp_box((-20.0, -30.0, 900.0, 900.0), 640, 480)
    x1, y1, x2, y2 = clamped
    assert (x1, y1) == (0.0, 0.0)
    assert x2 <= 640 and y2 <= 480


def test_clamp_box_never_returns_an_empty_box():
    x1, y1, x2, y2 = clamp_box((100.0, 100.0, 100.0, 100.0), 640, 480)
    assert x2 > x1 and y2 > y1


# --------------------------------------------------------------------- colour
def test_dominant_color_of_a_solid_blue_image():
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    image[:, :] = (255, 0, 0)  # BGR blue
    assert dominant_color(image) == "blue"


def test_dominant_color_of_a_black_image():
    assert dominant_color(np.zeros((32, 32, 3), dtype=np.uint8)) == "black"


def test_dominant_color_of_an_empty_image_is_none():
    assert dominant_color(np.zeros((0, 0, 3), dtype=np.uint8)) is None


def test_color_agreement():
    assert color_agreement("blue", "blue")
    assert color_agreement("black", "gray")       # neutrals are interchangeable
    assert not color_agreement("blue", "red")
    assert not color_agreement(None, "blue")


# --------------------------------------------------------------------- vectors
def test_vector_roundtrip():
    original = [0.125, -0.5, 0.75]
    assert from_pgvector(to_pgvector(original)) == pytest.approx(original)


def test_to_pgvector_formats_a_literal():
    assert to_pgvector([1.0, 2.0]) == "[1.000000,2.000000]"


def test_none_vector_stays_none():
    assert to_pgvector(None) is None
    assert from_pgvector(None) is None
