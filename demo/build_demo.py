"""Create original synthetic speech/video and render an honestly labeled sample."""
from pathlib import Path
import json
import copy
import shutil
import subprocess
import sys
import wave
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clipper import plan, render, file_hash
ROOT = Path(__file__).resolve().parent
TEXT = [
 "A reliable clip keeps one complete idea.",
 "Start with the question before giving the answer.",
 "The fix is to cut at a sentence boundary.",
 "Captions repeat the spoken words without inventing facts.",
 "Real retention data must be labeled with its source.",
 "Change only the requested clip and keep the rest intact."
]

def run(args):
    subprocess.run(args, cwd=ROOT, check=True, capture_output=True, timeout=90)

def main():
    frames=[]; sentences=[]; rate=16000; cursor=0
    for i,text in enumerate(TEXT):
        name=f"speech-{i:02d}"
        (ROOT/(name+".txt")).write_text(text,encoding="utf-8")
        run(["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y","-f","lavfi","-i",f"flite=textfile={name}.txt:voice=slt","-ar",str(rate),"-ac","1",name+".wav"])
        with wave.open(str(ROOT/(name+".wav")),"rb") as w:
            assert w.getnchannels()==1 and w.getsampwidth()==2 and w.getframerate()==rate
            raw=w.readframes(w.getnframes())
        silence=b"\0\0"*int(.25*rate)
        size=len(raw)//2 + len(silence)//2
        sentences.append({"start":cursor/rate,"end":(cursor+size)/rate,"text":text})
        frames.append(raw+silence); cursor+=size
    with wave.open(str(ROOT/"speech.wav"),"wb") as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(b"".join(frames))
    duration=cursor/rate
    run(["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y","-f","lavfi","-i",f"testsrc2=size=640x360:rate=24:duration={duration}","-i","speech.wav","-vf","drawtext=text='SYNTHETIC QA DEMO - NOT CUSTOMER FOOTAGE':fontsize=18:fontcolor=white:box=1:boxcolor=black@0.8:x=10:y=10","-filter_threads","1","-c:v","libx264","-threads","2","-preset","veryfast","-crf","26","-c:a","aac","-shortest","-movflags","+faststart","source.mp4"])
    data={"rights_confirmed":True,"synthetic":True,"duration":duration,"clip_count":2,"min_seconds":4,"max_seconds":9,"formats":["vertical","square"],"captions":True,"sentences":sentences}
    (ROOT/"manifest-content.json").write_text(json.dumps(data,indent=2)+"\n")
    content=plan(data);(ROOT/"plan-content.json").write_text(json.dumps(content,indent=2)+"\n")
    receipt=render(content,ROOT/"source.mp4",ROOT/"clips")
    before={p.name:file_hash(p) for p in (ROOT/"clips").glob("clip-01-*.mp4")}
    shutil.copytree(ROOT/"clips", ROOT/"clips-original", dirs_exist_ok=True)
    old_changed={p.name:file_hash(p) for p in (ROOT/"clips").glob("clip-02-*.mp4")}
    revised=copy.deepcopy(content)
    replacement=sentences[2:4]
    revised["clips"][1].update(start=replacement[0]["start"],end=replacement[-1]["end"],sentences=replacement,reason="Buyer-style revision fixture: replace clip 02 with the two complete sentences about sentence boundaries and accurate captions.")
    (ROOT/"plan-revision.json").write_text(json.dumps(revised,indent=2)+"\n")
    revision=render(revised,ROOT/"source.mp4",ROOT/"clips",only=["clip-02"])
    new_changed={p.name:file_hash(p) for p in (ROOT/"clips").glob("clip-02-*.mp4")}
    assert old_changed.keys()==new_changed.keys() and all(old_changed[k]!=new_changed[k] for k in old_changed), "Requested clips did not actually change"
    after={p.name:file_hash(p) for p in (ROOT/"clips").glob("clip-01-*.mp4")}
    assert before==after and len(before)==2, "Selective revision altered an unrelated clip"
    data["retention_source"]="SYNTHETIC QA points, not real platform/viewer retention"
    data["retention"]=[{"time":(s["start"]+s["end"])/2,"value":.99 if i in [1,4] else .05} for i,s in enumerate(sentences)]
    retained=plan(data);(ROOT/"plan-synthetic-retention.json").write_text(json.dumps(retained,indent=2)+"\n")
    output={"synthetic_only":True,"real_customer_validation":False,"source_duration":duration,"initial_render":receipt,"revision":revision,"unmodified_clip_hashes_verified":before==after,"requested_clip_hashes_actually_changed":old_changed!=new_changed,"retention_fixture_source":data["retention_source"]}
    (ROOT/"render-evidence.json").write_text(json.dumps(output,indent=2)+"\n")
    print(json.dumps(output,indent=2))

if __name__=="__main__":main()
