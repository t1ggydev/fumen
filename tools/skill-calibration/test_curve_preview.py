import unittest
from curve_preview import weighted_quantile, fit_curve, curve


class CurveTests(unittest.TestCase):
    def test_cell_size_cannot_dominate(self):
        self.assertEqual(weighted_quantile({'large': [1.] * 1000, 'small': [10.]}, .75), 10.)

    def test_monotone_anchors_and_open_extrapolation(self):
        anchors, _ = fit_curve({'a': list(range(1, 101))})
        for x, y in anchors:
            self.assertAlmostEqual(curve(x, anchors), y)
        values = [curve(x, anchors) for x in range(300)]
        self.assertTrue(all(b >= a for a, b in zip(values, values[1:])))
        self.assertGreater(curve(200, anchors), 30)
        self.assertEqual(curve(0, anchors), 0)

    def test_tied_reference_values_are_not_divided_by_zero(self):
        anchors, skipped = fit_curve({'a': [2.] * 100})
        self.assertEqual(skipped, [.75, .9])
        self.assertAlmostEqual(curve(2, anchors), 15)
        self.assertAlmostEqual(curve(4, anchors), 30)


if __name__ == '__main__':
    unittest.main()
