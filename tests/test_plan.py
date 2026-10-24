import copy
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).parents[1] / 'scripts' / 'resolve_places.py'
spec = importlib.util.spec_from_file_location('places', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def sample():
    def clip(i, start, end):
        return dict(id=i, name=i+'.mov', start=start, end=end, enabled=True,
                    media_id='media-'+i, path='synthetic/'+i+'.mov', location='')
    return dict(project='Synthetic', timeline='Demo', timeline_id='t1', start=0,
                fps=24.0, width=1920, height=1080,
                tracks=[dict(index=1, name='base', enabled=True, clips=[clip('a',0,100)]),
                        dict(index=2, name='cutaway', enabled=True, clips=[clip('b',25,50)])])


class PlanTests(unittest.TestCase):
    def test_topmost_intervals_and_disabled_track(self):
        s=sample()
        self.assertEqual([(r['clip_id'],r['start'],r['end']) for r in m.segments(s,[1,2])],
                         [('a',0,25),('b',25,50),('a',50,100)])
        s['tracks'][1]['enabled']=False
        self.assertEqual([(r['start'],r['end']) for r in m.segments(s,[1,2])],[(0,100)])

    def test_unresolved_skipped_and_evidence_required(self):
        s=sample();p=m.make_plan(s,[1,2])
        self.assertEqual(m.validate_plan(p,s),[])
        p['titles'][0].update(cn='示例城堡',en='EXAMPLE CASTLE',confidence='verified')
        with self.assertRaises(ValueError):m.validate_plan(p,s)
        p['titles'][0].update(evidence='Synthetic evidence',sources=['https://example.org/place'])
        self.assertEqual(len(m.validate_plan(p,s)),1)

    def test_replaced_media_same_name_rejected(self):
        s=sample();p=m.make_plan(s,[1,2]);new=copy.deepcopy(s)
        new['tracks'][0]['clips'][0]['media_id']='replacement'
        with self.assertRaises(ValueError):m.validate_plan(p,new)

    def test_outside_clip_and_overlap_rejected(self):
        s=sample();p=m.make_plan(s,[1,2]);p['titles'][0]['end']=26
        with self.assertRaises(ValueError):m.validate_plan(p,s)
        p=m.make_plan(s,[1,2]);p['titles'][0]['start']=-1
        with self.assertRaises(ValueError):m.validate_plan(p,s)

    def test_added_title_track_does_not_change_footage_identity(self):
        s=sample();p=m.make_plan(s,[1,2]);s['tracks'].append(dict(index=3,name='titles',enabled=True,clips=[]))
        self.assertEqual(m.validate_plan(p,s),[])


if __name__=='__main__':unittest.main()
