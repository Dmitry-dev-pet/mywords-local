"""Create an offline comparison page from actual generated mp3 files.

This assembles *only* public pilot audio from the two Actions artifacts.
No private study text, scripts, external JavaScript or remote resources.
"""
from pathlib import Path
from html import escape
import hashlib
import json
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "pilot")
ENGINES = ("piper", "kokoro")


def read_engine(engine):
    manifest = json.loads((ROOT / engine / "manifest.json").read_text(encoding="utf-8"))
    if manifest["engine"] != engine or manifest["language"] != "pt-PT":
        raise ValueError("Unexpected engine or language")
    for entry in manifest["samples"]:
        filename = entry["file"]
        if "/" in filename or ".." in filename or not filename.endswith(".mp3"):
            raise ValueError("Unexpected file path")
        file = ROOT / engine / filename
        if not file.is_file():
            raise FileNotFoundError(file)
        if hashlib.sha256(file.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Audio checksum mismatch")
    return manifest


def main():
    models = {e: read_engine(e) for e in ENGINES}
    a, b = (models[e]["samples"] for e in ENGINES)
    if len(a) != 10 or len(b) != 10:
        raise ValueError("Expected ten phrases from each model")
    if [(x["ru"], x["pt-PT"], x["basename"]) for x in a] != [
        (x["ru"], x["pt-PT"], x["basename"]) for x in b
    ]:
        raise ValueError("Audio engines must use identical exact source text")
    if models["piper"]["source_sha256"] != models["kokoro"]["source_sha256"]:
        raise ValueError("Sources have changed between generations")
    rows = []
    for i, phrase in enumerate(a, 1):
        def audio(engine):
            name = escape(phrase["file"], quote=True)
            return (f'<audio controls preload="none" src="{engine}/{name}">'
                    f'Аудио не поддерживается.</audio>')
        rows.append(
            f'<section class="phrase"><div class="ordinal">Фраза {i} из 10</div>'
            f'<h2 lang="pt-PT">{escape(phrase["pt-PT"])}</h2>'
            f'<p lang="ru">{escape(phrase["ru"])}</p>'
            '<div class="compare">'
            f'<div><strong>A · Piper Tugão</strong>{audio("piper")}</div>'
            f'<div><strong>B · Kokoro EU-PT</strong>{audio("kokoro")}</div>'
            '</div></section>'
        )
    html = '''<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MyWords: pt-PT TTS pilot</title>
<style>
:root{color-scheme:light;font-family:system-ui,Arial,sans-serif;background:#edf4fa;color:#1c304b}
*{box-sizing:border-box}body{margin:0;padding:20px 12px}
main{max-width:850px;margin:0 auto}
header{background:linear-gradient(110deg,#2d7fc6,#4c55ad);color:white;border-radius:20px;padding:22px}
h1{font-size:25px;margin:0 0 10px}header p{margin:4px 0;font-size:14px;line-height:1.5}
.phrase{background:white;border:1px solid #d7e4f1;border-radius:16px;padding:20px;margin:14px 0}
.ordinal{color:#7691a9;font-size:12px;font-weight:800}
h2{font-size:21px;margin:10px 0 4px;font-weight:740}
.phrase>p{color:#74859d;font-size:14px;margin:0 0 18px}
.compare{display:grid;grid-template-columns:1fr 1fr;gap:13px}
.compare>div{min-width:0;background:#f5f9ff;border:1px solid #e0e9f4;border-radius:13px;padding:14px}
.compare strong{font-size:13px;display:block;margin:0 0 11px}
audio{width:100%;max-width:100%;height:42px}
footer{font-size:12px;color:#65778d;line-height:1.6;margin:18px 8px}
@media(max-width:620px){.compare{grid-template-columns:1fr}h2{font-size:20px}.phrase{padding:15px}}
</style></head><body><main>
<header><h1>MyWords · 🇵🇹 Проверка голосов</h1>
<p>Две независимые синтетические версии одних и тех же 10 предложений.
Нажимай ▶ под фразой и сравнивай чёткость, интонацию и европейский акцент.</p>
<p>Все файлы находятся рядом с этой страницей. Интернет для прослушивания после
распаковки не требуется. Оригинальные мысли из публичного учебного каталога.</p>
</header>
''' + "\n".join(rows) + '''
<footer>Пилотный эксперимент. Это синтезированная, а не записанная человеком речь.
Piper Tugão: модель rhasspy/piper-voices (MIT, датасет CC0).
Kokoro: модель logus2k/kokoro_tts_eu_pt (Apache-2.0).
Качество и естественность произношения оцениваются на слух.
Контрольные суммы исходных файлов находятся в manifest.json каждой модели.</footer>
</main></body></html>'''
    (ROOT / "index.html").write_text(html, encoding="utf-8")
    print("PASS offline comparison page with 10 A/B pairs and verified checksums")


if __name__ == "__main__":
    main()
