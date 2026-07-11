#!/usr/bin/env python3
"""Build extraction packets: for every beat in the current plans, a numbered transcript
window from the real source clip. Agent will pick clean sentence boundaries; we assemble
verbatim. Output: packets.json (+ refreshes plan_NN.json from current repo)."""
import re, json, os, glob, subprocess, sys
SCR = "/private/tmp/claude-501/-Users-romansergeev-YTAI/ef55ceeb-461d-4280-9fc6-05257ea4e213/scratchpad"
PROJ = {"03":"YTAgeFree03_Caregiver_Burnout","04":"YTAgeFree04_Avoiding_Breakdowns",
        "05":"YTAgeFree05_Home_Safety_Bathroom","06":"YTAgeFree06_Dementia_Home_Setup"}

def to_sec(tc):
    tc=str(tc).strip().replace(",",".")
    m=re.match(r'(?:(\d+):)?(\d+)(?:\.(\d+))?$',tc)
    return int(m.group(1) or 0)*60+int(m.group(2))+float("0."+(m.group(3) or "0")) if m else None

def tpath(nn,fname):
    DISK=f"/Volumes/T7-Beige-RYA/YTAgeFree/{PROJ[nn]}/99_Pipeline/Transcripts"
    stem=fname.replace(".MP4","").replace(".mp4","")
    for c in (f"{DISK}/{stem}/{stem}_transcript.json",f"{DISK}/{stem}/{stem}.json",f"{DISK}/{stem}.json"):
        if os.path.exists(c): return c
    g=glob.glob(f"{DISK}/{stem}*/*.json")
    return g[0] if g else None

_seg={}
def segs(p):
    if p not in _seg: _seg[p]=json.load(open(p)).get("segments",[])
    return _seg[p]

# refresh plans from current repo
for nn in PROJ: subprocess.run([sys.executable,f"{SCR}/reconstruct_plan.py",nn],check=True,capture_output=True)

packets=[]
for nn in PROJ:
    plan=json.load(open(f"{SCR}/plan_{nn}.json"))
    beats=[("hook",0,b) for b in plan.get("hook",{}).get("beats",[])]
    for si,s in enumerate(plan.get("sections",[]),1):
        beats+=[(f"s{si}",si,b) for b in s.get("beats",[])]
    beats+=[("cta",99,b) for b in plan.get("cta",{}).get("beats",[])]
    # section headings map
    heads={"hook":plan.get("hook",{}).get("heading","")}
    for si,s in enumerate(plan.get("sections",[]),1): heads[f"s{si}"]=s.get("heading","")
    heads["cta"]="Призыв"
    for bi,(secid,_,b) in enumerate(beats):
        p=tpath(nn,b.get("source_file",""))
        if not p:
            packets.append({"key":f"{nn}:{bi}","nn":nn,"secid":secid,"heading":heads.get(secid,""),
                            "why":b.get("why",""),"source_file":b.get("source_file"),"cur_quote":b.get("quote",""),
                            "cur_tc":f'{b.get("tc_in")}–{b.get("tc_out")}',"window":None,"nofile":True}); continue
        t0=to_sec(b.get("tc_in")); t1=to_sec(b.get("tc_out"))
        ss=segs(p); win=[]
        for i,s in enumerate(ss):
            if s["end"]>=t0-25 and s["start"]<=t1+40:
                win.append({"i":len(win),"gi":i,"s":round(s["start"],2),"e":round(s["end"],2),
                            "spk":s.get("speaker",""),"text":s.get("text",""),
                            "in_span":(s["start"]>=t0-1 and s["end"]<=t1+1)})
        packets.append({"key":f"{nn}:{bi}","nn":nn,"secid":secid,"heading":heads.get(secid,""),
                        "why":b.get("why",""),"source_file":b.get("source_file"),"cur_quote":b.get("quote",""),
                        "cur_tc":f'{b.get("tc_in")}–{b.get("tc_out")}',"tpath":p,"window":win})

json.dump(packets,open(f"{SCR}/packets.json","w"),ensure_ascii=False,indent=1)
byv={}
for pk in packets: byv[pk["nn"]]=byv.get(pk["nn"],0)+1
print("packets:",len(packets),"by video:",byv,"| nofile:",sum(1 for p in packets if p.get("nofile")))
print("avg window segs:",round(sum(len(p["window"]) for p in packets if p.get("window"))/max(1,sum(1 for p in packets if p.get("window"))),1))
