import copy
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clipper import ClipError, Window, choose, plan, srt, timestamp, validate

def fixture():
    return {"rights_confirmed": True, "duration": 24, "clip_count": 2,
            "min_seconds": 4, "max_seconds": 8, "formats": ["vertical", "square"],
            "captions": True, "sentences": [
                {"start": i*4, "end": (i+1)*4, "text": text}
                for i, text in enumerate([
                    "One complete idea makes a useful clip.",
                    "Start with the question before the answer.",
                    "The fix is a clean sentence boundary.",
                    "Because context matters, keep the whole thought.",
                    "Captions repeat the actual spoken words.",
                    "Change only the requested clip."])]}

class ValidationTests(unittest.TestCase):
    def reject(self, mutate):
        x = fixture(); mutate(x)
        with self.assertRaises(ClipError): plan(x)
    def test_valid(self): self.assertEqual(len(validate(fixture())[0]), 6)
    def test_wrong_manifest_type(self):
        with self.assertRaises(ClipError): plan([])
    def test_rights_required(self): self.reject(lambda x: x.update(rights_confirmed=False))
    def test_duration_nan(self): self.reject(lambda x: x.update(duration=math.nan))
    def test_duration_inf(self): self.reject(lambda x: x.update(duration=math.inf))
    def test_duration_bool(self): self.reject(lambda x: x.update(duration=True))
    def test_duration_long(self): self.reject(lambda x: x.update(duration=3601))
    def test_count_zero(self): self.reject(lambda x: x.update(clip_count=0))
    def test_count_bool(self): self.reject(lambda x: x.update(clip_count=True))
    def test_count_high(self): self.reject(lambda x: x.update(clip_count=13))
    def test_formats_empty(self): self.reject(lambda x: x.update(formats=[]))
    def test_formats_unknown(self): self.reject(lambda x: x.update(formats=["portrait"]))
    def test_formats_duplicate(self): self.reject(lambda x: x.update(formats=["square", "square"]))
    def test_formats_bad_type(self): self.reject(lambda x: x.update(formats=[{}]))
    def test_bounds_reversed(self): self.reject(lambda x: x.update(min_seconds=12, max_seconds=8))
    def test_captions_wrong_type(self): self.reject(lambda x: x.update(captions="yes"))
    def test_empty_sentences(self): self.reject(lambda x: x.update(sentences=[]))
    def test_missing_text(self): self.reject(lambda x: x["sentences"][0].update(text=""))
    def test_incomplete_sentence(self): self.reject(lambda x: x["sentences"][0].update(text="cut in the middle"))
    def test_negative_time(self): self.reject(lambda x: x["sentences"][0].update(start=-1))
    def test_reversed_time(self): self.reject(lambda x: x["sentences"][0].update(end=0))
    def test_overlap(self): self.reject(lambda x: x["sentences"][1].update(start=3.5))
    def test_outside_source(self): self.reject(lambda x: x["sentences"][-1].update(end=25))
    def test_empty_retention_is_content(self): self.assertIsNone(plan(fixture())["retention_source"])
    def test_retention_requires_source(self): self.reject(lambda x: x.update(retention=[{"time": 2, "value": .5}]))
    def test_retention_invalid_value(self): self.reject(lambda x: x.update(retention_source="test", retention=[{"time": 2, "value": 2}]))
    def test_retention_nan(self): self.reject(lambda x: x.update(retention_source="test", retention=[{"time": 2, "value": math.nan}]))
    def test_retention_outside(self): self.reject(lambda x: x.update(retention_source="test", retention=[{"time": 24, "value": .5}]))
    def test_retention_duplicate_time(self): self.reject(lambda x: x.update(retention_source="test", retention=[{"time": 2, "value": .5}]*2))

class PlannerTests(unittest.TestCase):
    def test_exact_count(self): self.assertEqual(len(plan(fixture())["clips"]), 2)
    def test_nonoverlap(self):
        clips = plan(fixture())["clips"]
        self.assertLessEqual(clips[0]["end"], clips[1]["start"])
    def test_sentence_boundaries(self):
        for c in plan(fixture())["clips"]:
            self.assertEqual(c["start"], c["sentences"][0]["start"])
            self.assertEqual(c["end"], c["sentences"][-1]["end"])
    def test_reasons_quote_selected_text(self):
        for c in plan(fixture())["clips"]:
            self.assertTrue(any(s["text"] in c["reason"] for s in c["sentences"]))
    def test_fallback_honest(self):
        for c in plan(fixture())["clips"]:
            self.assertIn("No retention supplied", c["reason"])
            self.assertEqual(c["selection_mode"], "transcript-content-heuristic")
    def test_retention_highest_selected(self):
        x = fixture(); x.update(clip_count=1, max_seconds=4, retention_source="synthetic QA", retention=[{"time": i*4+1, "value": 1.0 if i==5 else 0.01} for i in range(6)])
        c = plan(x)["clips"][0]
        self.assertEqual(c["start"],20); self.assertEqual(c["retention_peak"],1)
    def test_retention_is_explicit(self):
        x=fixture(); x.update(clip_count=1, retention_source="synthetic test data, not viewers", retention=[{"time":5,"value":.9}])
        out=plan(x);self.assertEqual(out["retention_source"],x["retention_source"])
    def test_impossible_request_fails(self):
        x=fixture();x.update(clip_count=12)
        with self.assertRaises(ClipError):plan(x)
    def test_dp_not_greedy(self):
        ws=[Window(0,1,0,8,100,"all","test",None), Window(0,0,0,4,3,"a","test",None),Window(1,1,4,8,3,"b","test",None)]
        self.assertEqual([(w.start,w.end) for w in choose(ws,2)],[(0,4),(4,8)])
    def test_repeatable(self):self.assertEqual(plan(fixture()),plan(fixture()))
    def test_input_not_mutated(self):
        x=fixture();old=copy.deepcopy(x);plan(x);self.assertEqual(x,old)
    def test_caption_origin_and_text(self):
        c=plan(fixture())["clips"][0];captions=srt(c)
        self.assertIn("00:00:00,000 -->",captions)
        self.assertIn(c["sentences"][0]["text"].split()[0],captions)
    def test_caption_rounding(self):self.assertEqual(timestamp(59.9996),"00:01:00,000")
    def test_caption_markup_plain(self):
        c={"start":0,"end":2,"sentences":[{"start":0,"end":2,"text":"<b>One</b> {idea}."}]}
        out=srt(c);self.assertNotIn("<",out);self.assertNotIn("{",out)
    def test_synthetic_label(self):
        x=fixture();x["synthetic"]=True;self.assertTrue(plan(x)["synthetic"])

if __name__ == "__main__": unittest.main()
