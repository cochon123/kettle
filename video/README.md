# Kettle — the film

A 2:56 brand film for the Hack the Change 2026 submission. It's built as code: `film.html` is the film, rendered frame by frame in headless Chrome, so every number on screen comes from `../data/` (via `build_data.py`) and every product screen is a real screenshot of the running app.

| | |
|---|---|
| Picture | `film.html` + `film.js` + `film.css`: motion design in the Kettle night palette, plus real UI captures in `assets/` |
| 3D | `world.js` (three.js, vendored in `vendor/three/`, MIT): Margaret's house and kitchen, her street, Priya's walk over, and the kettle coming on |
| Voice | Gemini TTS (`gemini-3.8-flash-tts`, voice "Sulafat"), one take cut into lines: `audio/vo/` |
| Music | Lyria RealTime, steered scene by scene: `audio/music.opus`; `mix.py` darkens it at the end and closes on a synthesized D major chord |
| Sound effects | Synthesized in `audio/mix.py` (kettle switch, landline ring, phone buzz, pendant click, chimes, swells, wind), with no samples |
| Captions | `kettle-film.en.srt` / `.vtt` |
| Timing | `timeline.json`: where each voice line sits; `film.js` and `mix.py` both key off it |

## Build it

```bash
python video/build_data.py                               # real numbers → data.js (only if data/ changed)
python video/render.py --stills 12,48,95 --out /tmp/st   # look at a few frames
python video/render.py --out /tmp/picture.mp4            # whole film, silent (≈20 min on 4 cores)
python video/audio/mix.py /tmp/sound.wav                 # soundtrack, loudness-normalized to −16 LUFS
ffmpeg -i /tmp/picture.mp4 -i /tmp/sound.wav -vf "noise=c0s=6:c0f=t+u" \
  -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p -c:a aac -b:a 256k -movflags +faststart -shortest kettle-film.mp4
```

`render.py` needs `google-chrome`, `ffmpeg` and `websockets`; `mix.py` needs `numpy`, `scipy` and `soundfile`. Open `film.html?t=93` in a browser (served over HTTP, for the fonts) to look at one moment, or `film.html?play` to watch it run in real time without sound.

## What's real

- **Numbers:** StatCan 2021 (42% of 85+ live alone), Fleming & Brayne, BMJ 2008 (8 in 10), REFIT House 11 (Margaret's mornings and the boil trace), AESO pool price and ECCC temperature for Jan 13 2024, and the REFIT evaluation (9,242 home-days, F1 0.96, 4.7 check-ins per home per month).
- **Screens:** the circle app, the kitchen display and the stage, captured from `python -m kettle demo`. Demo time is accelerated.
- **Stylized:** Margaret's house, kitchen and street (3D), the Calgary city lights, Alberta's outline and the "every phone" dots, which are illustrative rather than real phone locations.
- **Photo:** the closing photo is by kawilson on Pixabay (Pixabay Content License), `assets/grandparents.jpg`.

Margaret, Priya and Tom are personas. Fonts: Fraunces and Inter (SIL OFL, `fonts/`).
