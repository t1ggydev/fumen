import unittest
from rank_curves import np, basis, distortion_terms, quadratic
from curve_preview import curve


class RankingTests(unittest.TestCase):
    def test_coefficients_match_every_map_including_zero_and_extrapolated_values(self):
        ref={'points':[{'raw':2.,'targetIndex':0},{'raw':3.,'targetIndex':1},{'raw':4.,'targetIndex':2}]}
        x=np.array([0,.5,2,2.5,3,4,8,100.])
        for target in [[1,1.1,1.2],[15,22,30],[1,50,100]]:
            anchors=[(0,0)]+[(p['raw'],target[p['targetIndex']]) for p in ref['points']]
            np.testing.assert_allclose(basis(x,ref)@target,[curve(v,anchors) for v in x])
        matrix,linear,constant=distortion_terms(x,ref)
        t=np.array([[1.,1.5,2.]])
        self.assertAlmostEqual(float(quadratic(t,matrix)[0]-2*(t@linear)[0]+constant),0.)

    def test_quadratic_reduction_matches_direct_every_map_error(self):
        ref={'points':[{'raw':2.,'targetIndex':0},{'raw':3.,'targetIndex':1},{'raw':4.,'targetIndex':2}]}
        x=np.array([0,.1,1,2,3,4,5,20.])
        matrix,linear,constant=distortion_terms(x,ref)
        targets=np.array([[1.,1.01,1.1],[1.,2.,3.],[1.,10.,100.]])
        for t in targets:
            direct=np.zeros(len(x));mask=x>0
            direct[mask]=(basis(x,ref)@t)[mask]/(x[mask]/2)-1
            reduced=float(quadratic(t[None,:],matrix)[0]-2*t@linear+constant)
            self.assertAlmostEqual(reduced,float(np.mean(direct**2)))


if __name__=='__main__':unittest.main()
