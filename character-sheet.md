# Mechanic: Character Sheet

The visual bible for **Mechanic**, AnyBuild's mascot. Personality and voice live in [character-style.md](character-style.md). This file covers how he looks: the fixed design that every image must match, and prompts ready to paste into an image generator.

**One-line pitch:** a genius garage engineer in his early 40s, with a sharp goatee, tinted HUD glasses and a grin that says he already solved it.

---

## 1. Fixed design (never changes)

The canonical description. Every prompt in §4 already contains it, so you don't need to paste it yourself.

```
CHARACTER: "Mechanic" — charismatic male genius engineer, early 40s, lean athletic build, 5'10".
FACE: angular jaw, defined cheekbones, warm olive skin, faint smile lines, expressive dark-brown eyes,
one eyebrow habitually raised, confident asymmetric half-smirk (left corner higher).
GOATEE: sharply sculpted anchor goatee connected to a thin trimmed mustache, very short and precise,
crisp razor-clean edges, clean-shaven cheeks and neck, a few grey hairs at the chin.
HAIR: dark brown, short faded sides, textured tousled top swept up and slightly back, a little messy.
GLASSES: thin gunmetal metal frames, rectangular-aviator hybrid shape, amber-tinted lenses
(eyes visible through tint), faint cyan holographic HUD lines and tiny data readouts glowing inside the lenses.
SIGNATURE: glowing cyan circular core emblem on the chest; small grease smudge on right cheekbone.
```

### Design specs

| Feature | Spec | Avoid |
|---|---|---|
| **Goatee** | Anchor goatee joined to a thin mustache, short and sculpted, sharp edges | Full beard, stubble across the cheeks, a handlebar mustache, a long chin beard |
| **Hair** | Faded sides, textured top swept up, slightly messy | A perfect slick-back, long hair, a buzz cut |
| **Glasses** | Thin metal rectangular-aviator frames, amber tint, cyan HUD inside the lenses | Thick plastic frames, fully opaque lenses that hide the eyes |
| **Expression** | Half-smirk, raised eyebrow, amused eyes | A wide toothy grin as the default, a blank face |
| **Build** | Lean and athletic, not bulky | A superhero-bodybuilder build |
| **Chest core** | A small glowing cyan circle, about 6 cm | A triangle core, red-and-gold color scheme |

### Color palette

| Swatch | Name | Hex | Used for |
|---|---|---|---|
| ![](https://placehold.co/24x24/1E2228/1E2228.png) | Gunmetal | `#1E2228` | Suit, jacket, UI background |
| ![](https://placehold.co/24x24/2E343C/2E343C.png) | Graphite | `#2E343C` | Secondary fabric, armor panels |
| ![](https://placehold.co/24x24/00E5FF/00E5FF.png) | Arc Cyan | `#00E5FF` | Chest core, HUD, holograms, suit seams |
| ![](https://placehold.co/24x24/FFB347/FFB347.png) | Lens Amber | `#FFB347` | Glasses tint |
| ![](https://placehold.co/24x24/C0C6CC/C0C6CC.png) | Brushed Silver | `#C0C6CC` | Frames, bolts, highlights |
| ![](https://placehold.co/24x24/FF6A00/FF6A00.png) | Spark Orange | `#FF6A00` | Welding sparks, warnings (use sparingly) |
| ![](https://placehold.co/24x24/C68E6A/C68E6A.png) | Skin | `#C68E6A` | Base skin tone |
| ![](https://placehold.co/24x24/3B2A20/3B2A20.png) | Hair | `#3B2A20` | Hair and goatee |

**Silhouette test:** a black silhouette of Mechanic should still read as him through the tousled hair spike, the glasses outline, the goatee point and the hands-in-pockets lean.

---

## 2. The three looks

### Look A: Garage (main mascot, about 70% of the app)
- Fitted charcoal crew-neck tech tee with the cyan core glowing through the fabric
- Open dark-olive canvas work jacket, sleeves pushed to the elbows, with a tool loop and a small AnyBuild patch on the left sleeve
- Dark slim work pants and scuffed brown leather work boots
- Fingerless black leather gloves, a smartwatch with a cyan face, a torque wrench or multi-tool in hand
- Grease smudge on the right cheekbone and the forearms

### Look B: Keynote (intro, simulation results, pitch slide)
- Slim-fit gunmetal suit with a subtle tonal check, no tie, crisp black shirt open two buttons
- Cyan core glow visible at the collar
- Pocket square in cyan, a brushed-silver watch
- Holding a floating cyan hologram of the user's build in one palm

### Look C: Tech Suit (hero art, "build complete" celebration)
- Sleek armored suit of matte gunmetal plates with brushed-silver edges, thin glowing cyan seams along the panels
- Bright glowing cyan circular chest core, palm emitters that glow cyan
- **Helmet off** so the face, glasses and goatee always show
- Visible rivets and slightly mismatched plates: **he built it himself**

---

## 3. Expressions and poses

| # | Expression | When it shows in the app | Notes |
|---|---|---|---|
| E1 | **Smirk** (default) | Idle, chat | Left corner up, right eyebrow raised |
| E2 | **Finger-gun wink** | "You're welcome" moments | Right hand finger-gun, left eye wink |
| E3 | **Focused** | Simulations running | Glasses HUD glowing, eyes narrowed, hand on chin |
| E4 | **Serious** | Safety warnings | Pushing glasses up the nose with one finger, no smile |
| E5 | **Facepalm** | Errors | Half facepalm, peeking through fingers, slight grin |
| E6 | **Laughing** | Funny fails | Head tilted back, genuine laugh |
| E7 | **Proud** | Build complete | Slow clap or thumbs up, warm real smile |
| E8 | **Skeptical** | User picks a bad option | One eyebrow way up, lips pursed |

| # | Pose | When it shows in the app |
|---|---|---|
| P1 | Hands in pockets, weight on one leg, lean | Onboarding |
| P2 | Wrench resting on his shoulder | Build steps |
| P3 | Spinning a hologram in his palm | Simulation and results |
| P4 | Leaning over a workbench, soldering | Parts and assembly |
| P5 | Arms crossed, smirking | Confirm screen |
| P6 | Heroic low-angle in the tech suit | Launch, "build complete" |

---

## 4. Prompts

Every prompt below is **text only**: you don't need reference images. The details that the reference photos used to show are written into the words: the goatee shape, the glasses, the open-collar blazer with the chest glow, the riveted hand-built armor, the wireframe hologram and the lived-in garage. Each prompt already contains the full character description, so you can paste any one of them on its own.

**Style tag** (already in every prompt, keep it identical for consistency):
`stylized 3D animated-film style, Pixar and Arcane quality, cinematic lighting, high detail`

### 4.0 Complete character sheet (one image, everything) ⭐
```
A professional, presentation-ready character design sheet on a single wide canvas, stylized 3D animated-film style,
Pixar and Arcane quality, cinematic lighting, high detail. Title at top left in clean bold sans-serif: "MECHANIC",
subtitle "AnyBuild mascot".

THE CHARACTER — "Mechanic": a charismatic male genius engineer in his early 40s, lean athletic build, 5'10".
Angular jaw, defined cheekbones, warm olive skin, faint smile lines at the eyes, expressive dark-brown eyes,
right eyebrow habitually raised, confident asymmetric half-smirk with the left corner of the mouth higher.
Goatee: a sharply sculpted anchor goatee — a short, dense chin beard with a rounded-pointed tip, connected at the
mouth corners to a thin, neatly trimmed mustache; razor-crisp edges; cheeks and neck perfectly clean-shaven;
a few silver-grey hairs at the chin. Hair: dark brown, short faded sides, thick textured top tousled upward and
slightly back, a little messy, as if he ran a hand through it. Glasses: thin gunmetal metal frames in a
rectangular-aviator hybrid shape with a slim double bridge, amber-tinted lenses that still show his eyes,
faint cyan holographic HUD lines and tiny data readouts glowing inside the lenses.
Signature: a small glowing cyan circular core on the center of his chest, and a small grease smudge on his right cheekbone.

LAYOUT (left to right, clearly separated panels with thin divider lines and small labels):
1) TURNAROUND — full-body neutral A-pose in the Garage outfit, five views: front, three-quarter front,
   side profile, three-quarter back, back; identical proportions and lighting, orthographic camera,
   faint height-guide lines behind.
2) OUTFITS — three full-body versions side by side:
   "GARAGE": fitted charcoal crew-neck tech tee with the cyan core glowing through the fabric, open dark-olive
   canvas work jacket with sleeves pushed to the elbows and a tool loop, slim dark work pants, scuffed brown
   leather work boots, fingerless black leather gloves, smartwatch with a cyan face, torque wrench in hand,
   grease on forearms.
   "KEYNOTE": slim-fit gunmetal suit with a subtle tonal check, no tie, crisp black shirt open two buttons with the
   cyan core glow visible at the collar, cyan pocket square, brushed-silver watch, one hand in pocket,
   other palm holding a small floating cyan wireframe hologram.
   "TECH SUIT": sleek hand-built armored suit of matte gunmetal plates with brushed-silver edges, slightly
   mismatched panels with visible rivets and hex bolts, thin glowing cyan seam lines, bright cyan circular
   chest core, glowing cyan palm emitters; helmet off, face fully visible.
3) EXPRESSIONS — 3x3 grid of head-and-shoulders portraits with labels: smirk, finger-gun wink, focused with
   glowing HUD lenses, serious pushing glasses up, half facepalm, head-back laugh, proud smile with thumbs up,
   skeptical raised eyebrow, talking mid-sentence.
4) DETAILS — callout close-ups with arrows and short notes: the anchor goatee shape (front and side),
   the glasses with the HUD readout "SIM 0847 / 1024", the cyan chest core, the riveted armor plate,
   the fingerless glove and smartwatch.
5) PROPS — torque wrench, multitool, soldering iron, small palm hologram projector puck.
6) PALETTE — a row of labeled color swatches: Gunmetal #1E2228, Graphite #2E343C, Arc Cyan #00E5FF,
   Lens Amber #FFB347, Brushed Silver #C0C6CC, Spark Orange #FF6A00, Skin #C68E6A, Hair #3B2A20.

Clean light-grey studio background, soft even lighting across all panels, consistent character in every panel,
crisp edges, professional animation-studio model sheet, ultra detailed, 8k.
```

### 4.1 Turnaround sheet
```
Professional character turnaround model sheet, stylized 3D animated-film style, Pixar and Arcane quality,
cinematic lighting, high detail.
"Mechanic" — charismatic male genius engineer, early 40s, lean athletic build, angular jaw, defined cheekbones,
warm olive skin, faint smile lines, dark-brown eyes, right eyebrow slightly raised, confident half-smirk.
Sharply sculpted anchor goatee: short dense chin beard with a rounded-pointed tip, joined to a thin trimmed
mustache, razor-crisp edges, clean-shaven cheeks and neck, a few grey hairs at the chin. Dark brown hair, short
faded sides, textured tousled top swept up and back. Thin gunmetal rectangular-aviator glasses with a slim
double bridge, amber-tinted lenses showing the eyes, faint cyan HUD lines inside the lenses.
OUTFIT: fitted charcoal crew-neck tech tee with a glowing cyan circular core on the chest, open dark-olive canvas
work jacket with sleeves pushed to the elbows and a tool loop, fingerless black leather gloves, cyan-faced
smartwatch, slim dark work pants, scuffed brown leather boots, small grease smudge on right cheekbone.
SCENE: full-body neutral A-pose in five views — front, three-quarter front, side profile, three-quarter back,
back — evenly spaced in one row, identical proportions and lighting, orthographic camera, faint horizontal
height-guide lines (head, shoulders, waist, knees), clean light-grey background, color swatch strip along the
bottom (#1E2228, #00E5FF, #FFB347, #C0C6CC), small label "MECHANIC — AnyBuild", 8k, sharp focus.
```

### 4.2 Expression sheet
```
Character expression sheet, 3x3 grid of head-and-shoulders portraits, the exact same character in every panel,
stylized 3D animated-film style, Pixar and Arcane quality, cinematic lighting, high detail.
"Mechanic" — male genius engineer, early 40s, angular jaw, warm olive skin, faint smile lines, sharply sculpted
anchor goatee joined to a thin trimmed mustache with clean-shaven cheeks and a few grey chin hairs, dark brown
hair with faded sides and tousled textured top, thin gunmetal rectangular-aviator glasses with amber-tinted
lenses and faint cyan HUD glow, charcoal tech tee with a glowing cyan circular core at the chest.
EXPRESSIONS (labeled under each panel):
1 SMIRK — asymmetric half-smirk, left mouth corner up, right eyebrow raised, amused eyes.
2 YOU'RE WELCOME — finger-gun pointed at viewer, left eye winking.
3 FOCUSED — eyes narrowed, HUD in lenses glowing bright cyan with scrolling data, hand on chin.
4 SERIOUS — no smile, pushing glasses up the nose bridge with one finger, steady eye contact.
5 OOPS — half facepalm, peeking through fingers, sheepish grin.
6 LAUGH — head tilted back, genuine open laugh, eyes crinkled.
7 PROUD — warm, real smile, thumbs up.
8 SKEPTICAL — one eyebrow way up, lips pursed sideways.
9 TALKING — mid-sentence, hands gesturing, eyebrows lively.
Consistent lighting and camera angle in every panel, clean white background, thin panel borders.
```

### 4.3 Outfit sheet (three looks side by side)
```
Character outfit design sheet, three full-body views of the same character standing side by side, labeled
"GARAGE", "KEYNOTE", "TECH SUIT", stylized 3D animated-film style, Pixar and Arcane quality, cinematic
lighting, high detail.
"Mechanic" — lean male genius engineer, early 40s, warm olive skin, angular jaw, sharply sculpted anchor goatee
with thin mustache and clean cheeks, dark brown tousled hair with faded sides, thin gunmetal amber-tinted
rectangular-aviator glasses with cyan HUD glow, confident half-smirk, glowing cyan circular chest core.
GARAGE: fitted charcoal tech tee with the core glowing through the fabric, open dark-olive canvas work jacket,
sleeves pushed up, tool loop, fingerless leather gloves, cyan smartwatch, slim dark work pants, scuffed brown
boots, torque wrench in hand, grease on forearms.
KEYNOTE: slim-fit gunmetal suit with subtle tonal check, crisp black shirt open two buttons, no tie, core glow
visible at the collar, cyan pocket square, brushed-silver watch, one hand in pocket, other hand adjusting
his glasses.
TECH SUIT: sleek hand-built armor of matte gunmetal plates with brushed-silver edges, slightly mismatched
panels, visible rivets and hex bolts, thin glowing cyan seams, bright cyan circular chest core, cyan palm
emitters, helmet off and face fully visible.
Same height and proportions in all three, neutral relaxed stance, clean light-grey background,
soft studio lighting, small fabric and material swatches under each outfit.
```

### 4.4 Garage hero shot
```
Stylized 3D animated-film character render, Pixar and Arcane quality, cinematic lighting, high detail.
"Mechanic" — charismatic male genius engineer, early 40s, lean athletic, angular jaw, warm olive skin, faint smile
lines, sharply sculpted anchor goatee joined to a thin mustache, clean-shaven cheeks, dark brown hair with faded
sides and tousled textured top, thin gunmetal rectangular-aviator glasses with amber-tinted lenses and faint cyan
HUD readouts, confident half-smirk with right eyebrow raised.
OUTFIT: fitted charcoal tech tee with a glowing cyan circular core, open dark-olive canvas work jacket with
sleeves pushed up, fingerless leather gloves, cyan smartwatch, grease smudges on cheekbone and forearms.
SCENE: three-quarter body, torque wrench resting on his shoulder, in a cluttered, lived-in high-tech garage at night:
heavy steel workbench with a half-built quadcopter drone, a robotic arm, pegboard wall packed with hand tools,
coiled cables, open parts bins, a soldering station with a thin smoke curl, a vintage motorcycle under a tarp
in the background, floating cyan holographic blueprints. Warm tungsten key light from the workbench lamp,
strong cyan rim light from the holograms, volumetric haze, floating dust, a few orange sparks.
50mm lens, shallow depth of field, cinematic color grade, ultra detailed, 8k.
```

### 4.5 Keynote reveal
```
Stylized 3D animated-film character render, Pixar and Arcane quality, cinematic lighting, high detail.
"Mechanic" — charismatic male genius engineer, early 40s, sharply sculpted anchor goatee with thin mustache and
clean cheeks, dark brown tousled hair with faded sides, thin gunmetal amber-tinted rectangular-aviator glasses
with cyan HUD reflections, sly half-smirk.
OUTFIT: slim-fit gunmetal suit with subtle tonal check, crisp black shirt open two buttons, no tie, faint cyan
core glow at the collar, cyan pocket square, brushed-silver watch.
SCENE: center stage at a dark tech keynote, left hand in pocket, right palm raised presenting a glowing cyan
wireframe hologram of a quadcopter drone made of thin luminous lines, splitting outward into dozens of
translucent ghost copies fanning into the air (1024 simulations), one copy highlighted brighter as the winner.
Huge dark LED wall behind with a subtle grid and the number "1024", single dramatic top spotlight, cyan light
reflecting on his face and lenses, faint stage haze, low-angle camera, premium tech-launch mood, 8k.
```

### 4.6 Tech suit hero
```
Stylized 3D animated-film character render, Pixar and Arcane quality, cinematic lighting, high detail.
"Mechanic" — male genius engineer, early 40s, angular jaw, warm olive skin, sharply sculpted anchor goatee with
thin mustache, dark brown tousled hair with faded sides, thin gunmetal amber-tinted glasses with glowing cyan HUD,
confident smirk, HELMET OFF, face fully visible.
OUTFIT: sleek custom armored suit he built himself — matte gunmetal plates with brushed-silver beveled edges,
slightly mismatched panels, visible rivets and hex bolts, a few scratches and one welded repair seam,
thin glowing cyan seam lines tracing the panels, bright glowing cyan circular chest core, glowing cyan palm emitters.
SCENE: heroic low-angle full-body pose on a garage rooftop at dusk, one fist clenched with the palm emitter
glowing, sparks and floating holographic blueprint fragments swirling around him, city lights behind,
strong cyan rim light and warm orange sunset fill, dramatic clouds, ultra detailed, 8k.
```

### 4.7 Tech suit detail sheet
```
Armor design callout sheet, stylized 3D animated-film style, Pixar and Arcane quality, high detail.
Hand-built futuristic armored suit for "Mechanic": front and back full-body views of the suit (helmet off,
character's face with sculpted anchor goatee and amber-tinted gunmetal glasses visible), plus labeled close-up
callouts with arrows: the glowing cyan circular chest core with concentric rings and a brushed-silver housing;
a shoulder plate showing rivets, hex bolts and a welded repair seam; a forearm panel with thin glowing cyan seam
lines; the palm emitter glowing cyan; the knee joint mechanism; a small stamped "MK 1" serial on the hip plate.
Materials: matte gunmetal #1E2228 and graphite #2E343C plates, brushed silver #C0C6CC edges, cyan #00E5FF glow.
Clean light-grey background, technical-drawing annotation style, soft studio lighting.
```

### 4.8 Glasses HUD close-up
```
Extreme close-up of the eyes and glasses of "Mechanic" — male engineer, early 40s, warm olive skin, faint smile
lines, dark-brown eyes narrowed in focus, right eyebrow raised, edge of a sculpted goatee visible at the bottom.
Thin gunmetal rectangular-aviator frames with a slim double bridge and amber-tinted lenses. Inside the lenses:
a glowing cyan holographic HUD — a tiny rotating 3D wireframe of a walking robot, a counter reading
"SIM 0847 / 1024", scrolling data lines, small bar graphs and success checkmarks. Reflections of a cyan
hologram on the lens surface. Dark background, shallow depth of field, macro look, stylized 3D animated-film
style, Pixar and Arcane quality, ultra detailed.
```

### 4.9 Pose sheet
```
Character pose sheet, six full-body poses of the same character in a 3x2 grid, labeled, stylized 3D
animated-film style, Pixar and Arcane quality, high detail.
"Mechanic" — lean male genius engineer, early 40s, sculpted anchor goatee with thin mustache, dark brown tousled
hair with faded sides, thin gunmetal amber-tinted glasses with cyan HUD, charcoal tech tee with glowing cyan
chest core, open dark-olive work jacket, fingerless gloves, dark work pants, brown boots.
POSES: 1 hands in pockets, weight on one leg, relaxed lean; 2 torque wrench resting on shoulder;
3 spinning a small cyan wireframe hologram on one fingertip; 4 leaning over a workbench soldering with tiny
orange sparks; 5 arms crossed, smirking; 6 pointing a finger-gun at the viewer with a wink.
Consistent proportions, clean light-grey background, soft studio lighting.
```

### 4.10 Props and gadgets sheet
```
Prop design sheet for the mascot "Mechanic", stylized 3D animated-film style, Pixar and Arcane quality,
high detail, each item labeled on a clean light-grey background with soft studio lighting:
1 torque wrench in brushed steel with a gunmetal grip and a small cyan LED readout;
2 folding multitool with gunmetal handles;
3 soldering iron with a coiled cable and a thin wisp of smoke;
4 his glasses — thin gunmetal rectangular-aviator frames, amber lenses, cyan HUD lines — shown front and side;
5 smartwatch with a cyan holographic face projecting a tiny rotating gear;
6 palm hologram projector puck, matte graphite with a cyan ring, projecting a small wireframe drone;
7 fingerless black leather work glove with worn knuckles.
Palette: gunmetal #1E2228, brushed silver #C0C6CC, arc cyan #00E5FF, amber #FFB347.
```

### 4.11 Environment sheet: the garage
```
Environment concept sheet, Mechanic's garage workshop, stylized 3D animated-film style, Pixar and Arcane
quality, cinematic lighting, high detail. Wide establishing shot plus three smaller detail panels.
WIDE: a lived-in, cluttered high-tech garage at night — roll-up door half open to a rainy street, concrete floor
with oil stains, heavy steel workbench with a half-built quadcopter drone, robotic arm with a cyan status light,
pegboard wall packed with hand tools, open parts bins, coiled cables, a vintage motorcycle under a tarp,
a whiteboard full of sketches, a beat-up leather couch, floating cyan holographic blueprints over the bench.
DETAILS: 1 the workbench close-up with soldering station and scattered screws; 2 the pegboard tool wall;
3 a cyan hologram table projecting a wireframe robot.
Warm tungsten lamps mixed with cyan hologram glow, volumetric haze, no characters, ultra detailed, 8k.
```

### 4.12 Hologram and 1024-simulation effect sheet
```
Visual effects design sheet for a holographic simulation UI, stylized 3D, cinematic, high detail, dark background.
Panels: 1 a single glowing cyan wireframe quadcopter drone made of thin luminous lines with soft bloom;
2 the same drone splitting into a fan of dozens of translucent ghost copies spreading outward (1024 simulations);
3 a few ghost copies flickering red and breaking apart (failed simulations) while one copy glows brighter cyan
with a checkmark (the winner); 4 a circular progress ring reading "SIM 0847 / 1024" with scrolling data;
5 a hand-sized projector puck emitting the hologram cone.
Colors: arc cyan #00E5FF main glow, spark orange #FF6A00 for failures, white highlights, deep gunmetal #1E2228 background.
```

### 4.13 App avatar / icon
```
App mascot avatar icon, head and shoulders of "Mechanic" — male genius engineer, early 40s, warm olive skin,
sharply sculpted anchor goatee with thin mustache, dark brown tousled hair with faded sides, thin gunmetal
amber-tinted rectangular-aviator glasses with cyan HUD glow, confident half-smirk with raised right eyebrow,
charcoal collar with cyan core glow below. Centered in a circle, bold simplified stylized 3D, strong silhouette
readable at 48px, gunmetal #1E2228 background with cyan #00E5FF rim light, clean edges, no text, high contrast.
```

### 4.14 Flat 2D sticker pack (UI, loaders, chat)
```
Flat 2D vector sticker pack, 8 stickers in a grid, thick clean outlines, minimal cel shading, white sticker border,
transparent background, limited palette (#1E2228, #2E343C, #00E5FF, #FFB347, #C0C6CC, #C68E6A, #3B2A20, #FF6A00):
"Mechanic" — male genius engineer with an angular jaw, sharp anchor goatee with thin mustache, spiky tousled
dark hair, rectangular-aviator amber glasses with a cyan HUD line, half-smirk, charcoal tee with a glowing cyan
circle on the chest, olive work jacket.
STICKERS: 1 smirk with wrench, 2 finger-gun wink "You're welcome", 3 thinking with glowing glasses,
4 facepalm "Oops", 5 thumbs up "Nailed it", 6 pushing glasses up "Safety first", 7 holding a tiny hologram drone,
8 laughing. Consistent character, sticker-sheet layout.
```

### Negative prompt (Stable Diffusion / Flux / Leonardo)
```
full beard, cheek stubble, handlebar mustache, long chin beard, long hair, bald, slicked-back hair,
thick plastic frames, round frames, opaque black sunglasses, eyes hidden, red and gold armor,
triangle chest light, helmet on, face hidden, bodybuilder, chibi, extra fingers, deformed hands,
asymmetrical eyes, different face between panels, inconsistent character, blurry, low detail,
watermark, garbled text
```

---

## 5. Generator settings (text-only consistency)

| Tool | Settings |
|---|---|
| **Midjourney v7** | `--ar 21:9 --style raw --s 200` for 4.0 / 4.1 / 4.3, `--ar 16:9` for scenes, `--ar 1:1` for 4.13. Lock a `--seed` you like and reuse it. |
| **GPT-image / ChatGPT** | Paste 4.0 first. Keep generating in the **same chat** and say "same character as above" for each next prompt. |
| **Flux / Stable Diffusion** | Use the negative prompt, 30–40 steps, CFG 4–6, a fixed seed. |
| **Leonardo / Ideogram** | Use the same seed and model preset for every prompt; paste the negative prompt into the negative field. |

**How to keep him consistent without reference images:**
1. Never edit the character description inside the prompts. Change only the SCENE / OUTFIT / POSES parts.
2. Use the same style tag, model and seed for every generation.
3. Generate in this order: **4.0 complete sheet** → **4.1 turnaround** → **4.2 expressions** → **4.3 outfits** → **4.4–4.6 hero shots** → **4.7–4.12 detail sheets** → **4.13 avatar** → **4.14 stickers**.
4. If one face drifts, regenerate that image. Don't change the words.

---

## 6. Animation states (for the app)

| State | Visual | Loop |
|---|---|---|
| `idle` | Smirk, slow breathing, chest core pulses every 3 s | Yes |
| `thinking` | HUD lights up in the lenses, scrolling data, hand on chin | Yes |
| `simulating` | Hologram in palm splits into ghost copies, core glows brighter | Yes |
| `talking` | Mouth moves, eyebrow pops on punchlines | Yes |
| `success` | Finger-gun wink, core flashes bright | No |
| `error` | Half facepalm, a small spark puff | No |
| `safety` | Pushes glasses up, HUD turns orange `#FF6A00` | No |
| `celebrate` | Switches to the tech suit, sparks, slow clap | No |

The app's `mascot` event currently has five states (`docs/events.md`). They map like this: `ruhig` → `idle`, `denkt` → `thinking` / `simulating`, `erklaert` → `talking`, `freut_sich` → `success` / `celebrate`, `besorgt` → `error` / `safety`.

