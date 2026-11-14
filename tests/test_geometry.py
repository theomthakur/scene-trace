from video_investigator.events.geometry import (bottom_center, box_area, point_in_polygon, polygon_area, polygon_box_intersection_area, validate_polygon)

SQ = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
L_SHAPE = [(0.0, 0.0), (1.0, 0.0), (1.0, 0.4), (0.4, 0.4), (0.4, 1.0), (0.0, 1.0)]     # concave


def test_inside_outside_and_boundary_counts_as_inside():
    assert point_in_polygon((0.5, 0.5), SQ)
    assert not point_in_polygon((0.1, 0.5), SQ)
    assert point_in_polygon((0.2, 0.5), SQ)          # edge
    assert point_in_polygon((0.2, 0.2), SQ)          # vertex


def test_concave_polygon_notch_is_outside():
    assert point_in_polygon((0.2, 0.7), L_SHAPE)
    assert not point_in_polygon((0.7, 0.7), L_SHAPE)


def test_validation_rejects_degenerate_and_self_intersecting():
    assert validate_polygon(SQ) is None
    assert "3 points" in validate_polygon([(0, 0), (1, 1)])
    assert "no area" in validate_polygon([(0.1, 0.1), (0.5, 0.5), (0.9, 0.9)])
    assert "crosses" in validate_polygon([(0.1, 0.1), (0.9, 0.9), (0.9, 0.1), (0.1, 0.9)])      # bow tie
    assert "normalized" in validate_polygon([(0.1, 0.1), (1.5, 0.1), (0.9, 0.9)])


def test_overlap_area_cases():
    assert abs(polygon_area(SQ) - 0.36) < 1e-12
    assert abs(polygon_box_intersection_area(SQ, (0.3, 0.3, 0.5, 0.5)) - 0.04) < 1e-12          # fully inside
    assert abs(polygon_box_intersection_area(SQ, (0.1, 0.1, 0.3, 0.3)) - 0.01) < 1e-12          # partial corner
    assert polygon_box_intersection_area(SQ, (0.85, 0.85, 0.95, 0.95)) == 0.0                    # disjoint
    assert abs(polygon_box_intersection_area(SQ, (0.0, 0.0, 1.0, 1.0)) - 0.36) < 1e-12          # box covers polygon


def test_box_helpers():
    assert bottom_center((0.2, 0.1, 0.4, 0.5)) == (0.30000000000000004, 0.5) or abs(bottom_center((0.2, 0.1, 0.4, 0.5))[0] - 0.3) < 1e-12
    assert box_area((0.0, 0.0, 0.5, 0.5)) == 0.25 and box_area((0.5, 0.5, 0.4, 0.4)) == 0.0
