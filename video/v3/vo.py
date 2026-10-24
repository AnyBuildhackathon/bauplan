import json, os, sys, urllib.request
key = [l.split("=",1)[1].strip().strip('"') for l in open(os.path.expanduser("~/.config/anybuild/secrets.env")) if l.startswith("ELEVENLABS_API_KEY=")][0]
voices = {"N": "EXAVITQu4vr4xnSDxMaL", "M": "CwhRBWXzGAHq8TQ4Fs17"}
d = sys.argv[1]
for name, who, text in json.load(open(f"{d}/lines.json")):
    body = {"text": text, "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.45 if who == "N" else 0.3, "similarity_boost": 0.8, "style": 0.15 if who == "N" else 0.45}}
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{voices[who]}?output_format=mp3_44100_128",
        data=json.dumps(body).encode(), headers={"xi-api-key": key, "content-type": "application/json"})
    open(f"{d}/vo/{name}.mp3", "wb").write(urllib.request.urlopen(req).read())
    print(name, "ok", flush=True)
