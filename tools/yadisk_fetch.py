"""Фото и видео щенков от клиента с Яндекс Диска (публичные папки).

python3 tools/yadisk_fetch.py list   — обходит папки из tools/yadisk.json, пишет tools/yadisk/manifest.json и листы-превью
                                       tools/yadisk/sheet-<папка>-<n>.jpg (номер кадра на каждой миниатюре), для видео — кадр.
python3 tools/yadisk_fetch.py pick   — качает выбранное из tools/yadisk-pick.json: фото → assets/img/<name>.jpg (до 1600 px),
                                       видео → assets/video/<name>.mp4 (720p, H.264, без звука по флагу) + постер assets/img/<name>.jpg.
Запускается в GitHub Actions (.github/workflows/fetch-yadisk.yml): из песочницы Яндекс Диск недоступен.
"""
import io, json, pathlib, subprocess, sys, urllib.parse, urllib.request
from PIL import Image, ImageDraw, ImageOps

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "yadisk"
API = "https://cloud-api.yandex.net/v1/disk/public/resources"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def get(url, raw=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    return data if raw else json.loads(data)


def listing(key, path="/"):
    items, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"public_key": key, "path": path, "limit": 200, "offset": offset, "preview_size": "XL"})
        d = get(f"{API}?{q}")
        emb = d.get("_embedded", {})
        batch = emb.get("items", [])
        for it in batch:
            if it["type"] == "dir":
                items += listing(key, it["path"])
            else:
                items.append({"key": key, "path": it["path"], "name": it["name"], "size": it.get("size"),
                              "media": it.get("media_type"), "mime": it.get("mime_type")})
        offset += len(batch)
        if offset >= emb.get("total", 0) or not batch:
            return items


def download_url(key, path):
    q = urllib.parse.urlencode({"public_key": key, "path": path})
    return get(f"{API}/download?{q}")["href"]


def fetch(key, path):
    return get(download_url(key, path), raw=True)


def cmd_list():
    srcs = json.loads((ROOT / "tools" / "yadisk.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for s in srcs:
        try:
            files = listing(s["key"], s.get("path", "/"))
        except Exception as e:
            print("LIST FAILED", s, e)
            continue
        for f in files:
            f["folder"] = s["label"]
        manifest += files
        print(s["label"], len(files), "files")
    # numbered thumbnails per folder
    tmp = pathlib.Path("/tmp/yd")
    tmp.mkdir(exist_ok=True)
    for n, f in enumerate(manifest, 1):
        f["n"] = n
        try:
            if f["media"] == "image":
                im = Image.open(io.BytesIO(fetch(f["key"], f["path"])))
                im = ImageOps.exif_transpose(im).convert("RGB")
                f["w"], f["h"] = im.size
            elif f["media"] == "video":
                vp = tmp / f"v{n}"
                vp.write_bytes(fetch(f["key"], f["path"]))
                probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json", str(vp)], capture_output=True, text=True)
                meta = json.loads(probe.stdout or "{}")
                st = (meta.get("streams") or [{}])[0]
                f["w"], f["h"] = st.get("width"), st.get("height")
                f["duration"] = float((meta.get("format") or {}).get("duration") or 0)
                fr = tmp / f"v{n}.jpg"
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(min(2, f["duration"] / 3)), "-i", str(vp), "-frames:v", "1", str(fr)])
                im = Image.open(fr).convert("RGB")
                vp.unlink()
            else:
                continue
            im.thumbnail((360, 360))
            im.save(tmp / f"t{n}.jpg", quality=80)
            f["thumb"] = True
        except Exception as e:
            print("THUMB FAILED", f["name"], e)
    for label in dict.fromkeys(f["folder"] for f in manifest):
        group = [f for f in manifest if f["folder"] == label and f.get("thumb")]
        for page in range(0, len(group), 30):
            chunk = group[page:page + 30]
            sheet = Image.new("RGB", (6 * 370, ((len(chunk) + 5) // 6) * 400), "white")
            d = ImageDraw.Draw(sheet)
            for i, f in enumerate(chunk):
                t = Image.open(tmp / f"t{f['n']}.jpg")
                x, y = (i % 6) * 370 + 5, (i // 6) * 400 + 5
                sheet.paste(t, (x, y))
                tag = f"#{f['n']}" + (" VIDEO %ds" % f.get("duration", 0) if f["media"] == "video" else "")
                d.rectangle([x, y + 362, x + 360, y + 392], fill="black")
                d.text((x + 6, y + 368), tag, fill="white")
            safe = "".join(ch if ch.isalnum() else "-" for ch in label)
            sheet.save(OUT / f"sheet-{safe}-{page // 30 + 1}.jpg", quality=78)
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_pick():
    picks = json.loads((ROOT / "tools" / "yadisk-pick.json").read_text(encoding="utf-8"))
    img_dir, vid_dir = ROOT / "assets" / "img", ROOT / "assets" / "video"
    img_dir.mkdir(parents=True, exist_ok=True)
    vid_dir.mkdir(parents=True, exist_ok=True)
    for p in picks:
        data = fetch(p["key"], p["path"])
        if p.get("kind") == "video":
            src = pathlib.Path("/tmp") / ("in-" + p["name"])
            src.write_bytes(data)
            out = vid_dir / f"{p['name']}.mp4"
            vf = "scale='if(gt(iw,ih),-2,720)':'if(gt(iw,ih),720,-2)',fps=30"
            args = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
            if p.get("start"):
                args[4:4] = ["-ss", str(p["start"])]
            args += ["-t", str(p.get("max_seconds", 30)), "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", "26",
                     "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
            args += ["-an"] if p.get("mute") else ["-c:a", "aac", "-b:a", "96k"]
            subprocess.run(args + [str(out)], check=True)
            poster = img_dir / f"{p['name']}.jpg"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(p.get("poster_at", 1)), "-i", str(out), "-frames:v", "1", "-q:v", "3", str(poster)], check=True)
            print(out.relative_to(ROOT), out.stat().st_size // 1024, "KB")
        else:
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
            im.thumbnail((1600, 1600))
            dest = img_dir / f"{p['name']}.jpg"
            im.save(dest, "JPEG", quality=86, optimize=True, progressive=True)
            print(dest.relative_to(ROOT), im.size, dest.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    {"list": cmd_list, "pick": cmd_pick}[sys.argv[1] if len(sys.argv) > 1 else "list"]()
