"""Builds the v3 demo film (16:9) from real app recordings, rendered cards, voice lines and music.
Usage: python3 video/v3/build.py <workDir>   (workDir holds png/, vo/, live/ and ../v2/capm, ../music)
Cuts sit on the music's bar grid (The Complex, 104 BPM), like the reference films."""
import glob, json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

RAW = os.environ.get("RAW") == "1"  # clips only, without kickers, for the HyperFrames composition
W = os.path.abspath(sys.argv[1]); SEG = f"{W}/segraw" if RAW else f"{W}/seg"; os.makedirs(SEG, exist_ok=True)
B = 60 / 104 * 4  # one bar
CAPM = glob.glob(f"{W}/../v2/capm/*.webm")[0]; LIVE = glob.glob(f"{W}/live/*.webm")[0]
OFF = 1.2  # recording starts this long after the capture script's clock

# (kind, args..., bars, kicker, voice lines [(name, offset)])
S = [
    ("kin", "c01", 6, 0.6, 0.38, 3, None, [("01n", 1.0)]),
    ("card", "logo", 1.5, None, [("02n", 0.3)]),
    ("kin", "c02", 3, 0.2, 0.55, 2, None, []),
    ("card", "mascot", 1.5, None, [("02m", 0.4)]),
    ("card", "ch-listens", 1, None, [("03n", 0.25)]),
    ("clip", CAPM, 4.0, 26, 1.0, 1.6, 0.13, 0.32, 3, "kickoff", []),
    ("clip", CAPM, 20, 30, 1.6, 1.95, 0.13, 0.6, 2, "warn", []),
    ("card", "ch-plans", 1, None, [("04n", 0.25)]),
    ("clip", CAPM, 30, 60, 1.05, 1.4, 0.25, 0.45, 2.5, "agents", []),
    ("card", "ch-tests", 1, None, [("05n", 0.2)]),
    ("clip", CAPM, 86.2, 102, 1.05, 1.25, 0.62, 0.5, 3, "sim", [("05m", 1.7)]),
    ("card", "ch-builds", 1, None, [("06n", 0.2)]),
    ("clip", CAPM, 110.6, 114, 1.0, 1.2, 0.62, 0.5, 1.5, "cad", []),
    ("clip", CAPM, 114, 121, 1.1, 1.3, 0.62, 0.5, 1.5, "render", []),
    ("card", "ch-changes", 1.5, None, [("07n", 0.3)]),
    ("clip", CAPM, 135, 144.4, 1.0, 1.6, 0.55, 0.82, 3, "ask", [("07m", 0.5)]),
    ("clip", CAPM, 146.6, 176.2, 1.0, 1.15, 0.6, 0.5, 3, "v2", [("08n", 0.3)]),
    ("card", "ch-learns", 1, None, [("09n", 0.25)]),
    ("clip", CAPM, 196, 214, 1.0, 1.25, 0.45, 0.4, 4, "train", []),
    ("card", "ch-ships", 1, None, [("10n", 0.2)]),
    ("clip", f"{W}/../v2/capm/stills/bom-v2.png", 0, 6, 1.0, 1.35, 0.8, 0.28, 2.5, "bom", []),
    ("card", "ch-any", 1, None, [("11n", 0.25)]),
    ("clip", LIVE, 4.2, 11.5, 1.5, 1.9, 0.13, 0.15, 1.5, "live", []),
    ("clip", LIVE, 11.5, 141, 1.0, 1.1, 0.5, 0.5, 3, "live", []),
    ("clip", LIVE, 141, 150, 1.0, 1.2, 0.6, 0.5, 2, "stand", []),
    ("clip", LIVE, 172.6, 176.2, 1.0, 1.12, 0.55, 0.4, 2, "lib", []),
    ("card", "tech", 2, None, [("12n", 0.3)]),
    ("card", "end", 3.5, None, [("13n", 0.4)]),
]
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30", "-an"]
def ease(n): return f"(({{p}})*({{p}})*(3-2*({{p}})))".replace("{p}", f"min(1,on/{n})")

def zp(z0, z1, fx, fy, n):
    z = f"{z0}+({z1}-{z0})*{ease(n)}"
    return (f"zoompan=z='{z}':x='max(0,min(iw-iw/zoom,{fx}*iw-iw/zoom/2))':"
            f"y='max(0,min(ih-ih/zoom,{fy}*ih-ih/zoom/2))':d=1:s=1920x1080:fps=30")

def job(i, s):
    out = f"{SEG}/{i:02d}.mp4"; kind = s[0]
    if kind == "kin":
        _, name, nw, t0, step, bars, _, _ = s; dur = bars * B
        lst = f"{SEG}/{i:02d}.txt"
        with open(lst, "w") as f:
            for w in range(nw):
                d = (t0 + step if w == 0 else step) if w < nw - 1 else dur - t0 - step * (nw - 1)
                f.write(f"file '{W}/png/{name}-{w}.png'\nduration {d:.3f}\n")
            f.write(f"file '{W}/png/{name}-{nw-1}.png'\n")
        n = round(dur * 30)
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
               "-vf", f"fps=30,scale=2880:-2,{zp(1.0, 1.06, .5, .5, n)},trim=duration={dur:.3f}", *X264, out]
    elif kind == "card":
        _, name, bars, _, _ = s; dur = bars * B; n = round(dur * 30)
        cmd = ["ffmpeg", "-v", "error", "-y", "-loop", "1", "-t", f"{dur:.3f}", "-framerate", "30", "-i", f"{W}/png/{name}.png",
               "-vf", f"scale=2880:-2,{zp(1.0, 1.05, .5, .5, n)},trim=duration={dur:.3f}", *X264, out]
    else:
        _, src, a, b, z0, z1, fx, fy, bars, kick, _ = s; dur = bars * B; n = round(dur * 30)
        sp = (b - a) / dur
        src_in = ["-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}", "-i", src] if src.endswith(".png") else ["-ss", f"{a - OFF:.3f}", "-t", f"{b - a:.3f}", "-i", src]
        if src.endswith(".png"): sp = 1
        if RAW:
            cmd = ["ffmpeg", "-v", "error", "-y", *src_in, "-vf",
                   f"setpts=(PTS-STARTPTS)/{sp:.4f},fps=30,scale=2880:-2,{zp(z0, z1, fx, fy, n)},trim=duration={dur:.3f},tpad=stop_mode=clone:stop_duration=1,trim=duration={dur:.3f}",
                   *X264, out]
            subprocess.run(cmd, check=True)
            return i
        cmd = ["ffmpeg", "-v", "error", "-y", *src_in,
               "-loop", "1", "-t", f"{dur:.3f}", "-framerate", "30", "-i", f"{W}/png/k-{kick}.png",
               "-filter_complex",
               f"[0:v]setpts=(PTS-STARTPTS)/{sp:.4f},fps=30,scale=2880:-2,{zp(z0, z1, fx, fy, n)},trim=duration={dur:.3f},setpts=PTS-STARTPTS[v];"
               f"[1:v]format=rgba,fade=in:st=0.15:d=0.35:alpha=1[k];[v][k]overlay=0:0:shortest=1,tpad=stop_mode=clone:stop_duration=1,trim=duration={dur:.3f}",
               *X264, out]
    subprocess.run(cmd, check=True)
    return i

starts, t = [], 0.0
for s in S:
    starts.append(t); t += (s[5] if s[0] == "kin" else s[2] if s[0] == "card" else s[8]) * B
total = t
print(f"total {total:.2f}s, {len(S)} shots")
if RAW:
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda p: job(*p), [(i, s) for i, s in enumerate(S) if s[0] == "clip"]))
    json.dump([[i, s[0], s[1] if s[0] != "clip" else s[9]] for i, s in enumerate(S)], open(f"{SEG}/shots.json", "w"))
    sys.exit(print("raw clips", SEG))
with ThreadPoolExecutor(6) as ex:
    for i in ex.map(lambda p: job(*p), enumerate(S)): print("seg", i, flush=True)
with open(f"{SEG}/list.txt", "w") as f:
    f.writelines(f"file '{SEG}/{i:02d}.mp4'\n" for i in range(len(S)))
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", f"{SEG}/list.txt", "-c", "copy", f"{W}/video.mp4"], check=True)

# Audio: voice lines on their shots; music in three parts (build, the big section from "It learns", the ending), ducked under voice.
vo = [(name, starts[i] + off) for i, s in enumerate(S) for name, off in s[-1]]
learn = starts[[s[1] for s in S].index("ch-learns")]
music = f"{W}/../music/The Complex.mp3"; tail = 16.25
inp, fl = [], []
for k, (name, at) in enumerate(vo):
    inp += ["-i", f"{W}/vo/{name}.mp3"]; fl.append(f"[{k}:a]adelay={int(at*1000)}:all=1,volume=1.15[v{k}]")
m = len(vo); inp += ["-i", music, "-i", music, "-i", music]
fl += [f"[{m}:a]atrim=0:{learn+0.6:.3f},afade=t=out:st={learn-0.2:.3f}:d=0.8[ma]",
       f"[{m+1}:a]atrim=106:{106+total-tail-learn+1.5:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.3,afade=t=out:st={total-tail-learn+0.5:.3f}:d=1,adelay={int((learn-0.25)*1000)}:all=1[mb]",
       f"[{m+2}:a]atrim=251.75,asetpts=PTS-STARTPTS,afade=t=in:d=1,adelay={int((total-tail)*1000)}:all=1[mc]",
       "[ma][mb][mc]amix=inputs=3:normalize=0,volume=0.6[mus]",
       "".join(f"[v{k}]" for k in range(m)) + f"amix=inputs={m}:normalize=0,asplit[vo1][vo2]",
       "[mus][vo1]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=450[duck]",
       f"[duck][vo2]amix=inputs=2:normalize=0,atrim=0:{total:.3f},afade=t=out:st={total-1.2:.3f}:d=1.2,loudnorm=I=-14:TP=-1.5:LRA=11[a]"]
subprocess.run(["ffmpeg", "-v", "error", "-y", *inp, "-filter_complex", ";".join(fl), "-map", "[a]", "-ar", "48000", f"{W}/audio.wav"], check=True)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f"{W}/video.mp4", "-i", f"{W}/audio.wav", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart", f"{W}/AnyBuild-demo-v3-16x9.mp4"], check=True)
json.dump({"total": total, "starts": starts, "vo": vo}, open(f"{W}/timeline.json", "w"), indent=1)
print("done", f"{W}/AnyBuild-demo-v3-16x9.mp4")
