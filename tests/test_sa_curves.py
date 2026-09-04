import numpy as np
import pytest

from resiflow.sa.curves import mix_damage_curves, scale_depth_axis, speed_depth


BASE_CURVE = [(0.0, 0.0), (1.0, 0.5), (2.0, 1.0)]


def test_scale_depth_axis_scales_x_only():
    x, y = scale_depth_axis(BASE_CURVE, 2.0)
    assert np.allclose(x, [0.0, 2.0, 4.0])
    assert np.allclose(y, [0.0, 0.5, 1.0])


def test_mix_damage_curves_interpolates_and_weights():
    curve_b = [(0.0, 0.0), (2.0, 0.0)]
    x, y = mix_damage_curves(BASE_CURVE, curve_b, weight_a=0.5)
    assert np.allclose(x, [0.0, 1.0, 2.0])
    assert np.allclose(y, [0.0, 0.25, 0.5])


def test_speed_depth_clips_bounds():
    assert speed_depth(-1.0) == pytest.approx(1.0)
    assert speed_depth(0.0) == pytest.approx(1.0)
    assert speed_depth(0.5) == pytest.approx(0.5)
    assert speed_depth(1.0) == pytest.approx(0.0)
    assert speed_depth(2.0) == pytest.approx(0.0)


def test_speed_depth_array_input():
    values = speed_depth(np.array([0.0, 0.5, 1.0]), free_flow_speed=60.0, max_depth=1.0)
    assert np.allclose(values, [60.0, 30.0, 0.0])
