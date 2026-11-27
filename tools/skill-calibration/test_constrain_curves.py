import unittest
from constrain_curves import preserve_ratios
from curve_preview import curve

class RatioTests(unittest.TestCase):
    def test_reference_is_fixed_and_weak_demands_do_not_catch_up(self):
        original = [[0.,0.],[1.,15.],[2.,20.],[4.,22.]]
        fixed = preserve_ratios(original)
        self.assertEqual(fixed[-1],original[-1])
        self.assertEqual(original[1][1],15.)
        for a,b in zip(fixed[1:],fixed[2:]):
            self.assertLessEqual(a[1]/a[0],b[1]/b[0])
        for x in [.01,.2,.8,1.1,2.,3.9]:
            for multiplier in [1.01,1.5,2.]:
                if x*multiplier <= fixed[-1][0]:
                    self.assertGreaterEqual(curve(x*multiplier,fixed)+1e-10,multiplier*curve(x,fixed))

    def test_already_expanding_curve_is_unchanged(self):
        pts=[[0.,0.],[1.,4.],[2.,9.],[4.,20.]]
        self.assertEqual(preserve_ratios(pts),pts)

if __name__=='__main__': unittest.main()
