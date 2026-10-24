# Mechanic: Character Sheet

The visual bible for **Mechanic**, AnyBuild's mascot. Personality and voice live in [character-style.md](character-style.md). This file covers how he looks: the fixed design that every image must match, and prompts ready to paste into an image generator.

**One-line pitch:** a genius garage engineer in his early 40s, with a sharp goatee, tinted HUD glasses and a grin that says he already solved it.

---

## 1. Fixed design (never changes)

Paste this block at the top of every prompt so each image shows the same character.

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

Each prompt is self-contained: the fixed design block from §1 is already included. Change only the part after **SCENE**.

### 4.1 Master turnaround sheet (generate this first)
```
Professional character turnaround model sheet, stylized 3D animated-film style (Pixar / Arcane quality),
"Mechanic" — charismatic male genius engineer, early 40s, lean athletic build, angular jaw, warm olive skin,
sharply sculpted anchor goatee connected to a thin trimmed mustache with crisp clean edges and clean-shaven cheeks,
dark brown hair with short faded sides and textured tousled top swept up, thin gunmetal rectangular-aviator glasses
with amber-tinted lenses and faint cyan holographic HUD lines inside the lenses, confident half-smirk.
OUTFIT: fitted charcoal tech t-shirt with glowing cyan circular emblem on chest, open dark-olive canvas work jacket
with sleeves pushed up, fingerless black leather gloves, slim dark work pants, scuffed brown leather boots,
small grease smudge on right cheekbone.
SCENE: full-body A-pose shown in five views — front, 3/4 front, side profile, 3/4 back, back —
evenly spaced in a row, identical proportions and lighting across all views, orthographic camera,
neutral soft studio lighting, clean light-grey background, thin construction guidelines, color swatch strip
at bottom (#1E2228, #00E5FF, #FFB347, #C0C6CC), labeled "MECHANIC — AnyBuild", high detail, 8k, sharp focus.
```

### 4.2 Expression sheet
```
Character expression sheet, 8 head-and-shoulders portraits in a 4x2 grid, same character in every panel:
"Mechanic" — male genius engineer, early 40s, angular jaw, warm olive skin, sharply sculpted anchor goatee with
thin mustache and clean-shaven cheeks, tousled dark brown hair with faded sides, thin gunmetal amber-tinted
aviator-rectangle glasses with cyan HUD glow, charcoal tech tee with glowing cyan chest emblem.
SCENE: expressions labeled — 1 confident half-smirk with raised eyebrow, 2 finger-gun with wink,
3 focused with glowing HUD lenses and hand on chin, 4 serious pushing glasses up nose,
5 half facepalm peeking through fingers, 6 head-back genuine laugh, 7 proud warm smile with thumbs up,
8 skeptical one eyebrow raised lips pursed. Stylized 3D animated-film style, consistent lighting,
clean white background, model-sheet layout, high detail.
```

### 4.3 Look A: Garage hero shot
```
Stylized 3D animated-film character render, "Mechanic" — charismatic male genius engineer, early 40s,
lean athletic, angular jaw, warm olive skin, sharply sculpted anchor goatee with thin mustache, clean cheeks,
tousled dark brown hair with faded sides, thin gunmetal amber-tinted rectangular-aviator glasses with faint
cyan HUD readouts in the lenses, confident half-smirk with one eyebrow raised.
OUTFIT: fitted charcoal tech tee with glowing cyan circular core emblem, open dark-olive canvas work jacket
sleeves pushed up, fingerless leather gloves, grease smudge on cheekbone and forearms.
SCENE: three-quarter body, resting a torque wrench on his shoulder, standing in a cluttered high-tech garage
workshop at night — workbench with half-built drone, robotic arm, scattered tools, pegboard, soldering station,
floating cyan holographic blueprints. Lighting: warm tungsten key light from workbench, strong cyan rim light
from holograms, volumetric haze, floating dust and a few orange sparks. Shallow depth of field, 50mm lens,
cinematic color grade, ultra detailed, 8k.
```

### 4.4 Look B: Keynote reveal
```
Stylized 3D animated-film character render, "Mechanic" — charismatic male genius engineer, early 40s,
sharply sculpted anchor goatee with thin mustache, clean cheeks, tousled dark brown hair with faded sides,
thin gunmetal amber-tinted aviator-rectangle glasses with cyan HUD reflections, sly half-smirk.
OUTFIT: slim-fit gunmetal suit with subtle tonal check, crisp black shirt open at collar no tie,
cyan pocket square, faint cyan core glow visible under the shirt, brushed silver watch.
SCENE: standing center stage at a dark tech keynote, left hand in pocket, right palm raised presenting a floating
glowing cyan holographic wireframe of a quadcopter drone that is splitting into many translucent ghost copies
(representing 1024 simulations), huge dark LED screen behind him with subtle grid, single dramatic top spotlight,
cyan light reflecting on his face and lenses, low-angle camera, cinematic, premium tech launch mood, 8k.
```

### 4.5 Look C: Tech suit hero
```
Stylized 3D animated-film character render, "Mechanic" — male genius engineer, early 40s, angular jaw,
sharply sculpted anchor goatee with thin mustache, tousled dark brown hair with faded sides,
thin gunmetal amber-tinted glasses with glowing cyan HUD, confident smirk, HELMET OFF face fully visible.
OUTFIT: sleek custom armored suit — matte gunmetal plates with brushed-silver edges, slightly mismatched
hand-built panels with visible rivets and bolts, thin glowing cyan seam lines, bright glowing cyan circular
chest core, glowing cyan palm emitters.
SCENE: heroic low-angle full-body pose on a garage rooftop at dusk, one fist clenched with palm emitter
glowing, sparks and floating holographic blueprint fragments swirling around him, city lights behind,
strong cyan rim light and warm orange sunset fill, dramatic clouds, cinematic, ultra detailed, 8k.
```

### 4.6 Glasses HUD close-up (the simulation-screen detail)
```
Extreme close-up of the eyes and glasses of "Mechanic" — male engineer early 40s, warm olive skin,
dark brown eyes narrowed in focus, one eyebrow raised, thin gunmetal rectangular-aviator frames with
amber-tinted lenses. Inside the lenses: glowing cyan holographic HUD — tiny rotating 3D wireframe of a robot,
counter reading "SIM 0847 / 1024", scrolling data lines, small graphs, success checkmarks.
Reflections of a cyan hologram on the lens surface. Dark background, shallow depth of field,
macro photography look, stylized 3D animated-film style, ultra detailed.
```

### 4.7 Pose sheet
```
Character pose sheet, six full-body poses of the same character in a 3x2 grid, stylized 3D animated-film style:
"Mechanic" — lean male genius engineer early 40s, sculpted anchor goatee with thin mustache, tousled dark
brown hair, thin amber-tinted gunmetal glasses with cyan HUD, charcoal tech tee with glowing cyan chest emblem,
open dark-olive work jacket, fingerless gloves, dark work pants, brown boots.
SCENE: 1 hands in pockets leaning with weight on one leg, 2 wrench resting on shoulder,
3 spinning a small cyan hologram on fingertip, 4 leaning over workbench soldering with sparks,
5 arms crossed smirking, 6 pointing finger-gun at viewer with a wink.
Consistent proportions, clean light-grey background, soft studio lighting, labeled poses.
```

### 4.8 App avatar / icon
```
App mascot avatar icon, head and shoulders of "Mechanic" — male genius engineer early 40s, sculpted anchor goatee
with thin mustache, tousled dark brown hair with faded sides, thin gunmetal amber-tinted glasses with cyan HUD glow,
confident half-smirk with raised eyebrow, charcoal collar with cyan core glow below.
SCENE: centered in a circle, bold simplified stylized 3D, strong silhouette readable at 48px,
gunmetal #1E2228 background with cyan #00E5FF rim light, clean edges, no text, high contrast.
```

### 4.9 Flat 2D vector version (for UI, stickers, loaders)
```
Flat 2D vector mascot illustration, thick clean outlines, minimal cel shading, limited palette
(#1E2228, #2E343C, #00E5FF, #FFB347, #C0C6CC, #C68E6A, #3B2A20):
"Mechanic" — male genius engineer, angular jaw, sharp anchor goatee with thin mustache, spiky tousled dark hair,
rectangular-aviator amber-tinted glasses with a cyan HUD line, half-smirk, charcoal tee with glowing cyan circle
on chest, olive work jacket, holding a wrench. Sticker style, white outline border, transparent background.
```

### Negative prompt (use with Stable Diffusion / Flux / Leonardo)
```
full beard, cheek stubble, handlebar mustache, long hair, bald, thick plastic frames, opaque black sunglasses,
red and gold armor, triangle chest light, helmet on, face hidden, bodybuilder, cartoonish chibi, extra fingers,
deformed hands, asymmetrical eyes, blurry, low detail, watermark, text artifacts, inconsistent character
```

---

## 5. Generator settings

| Tool | Settings |
|---|---|
| **Midjourney v7** | Add `--ar 16:9 --style raw --s 250` for scenes, `--ar 21:9` for the turnaround. After 4.1 works, add `--cref <turnaround URL> --cw 100` to every other prompt to lock the face. Use `--cw 30` to change outfit but keep the face. |
| **GPT-image / ChatGPT** | Paste the prompt, then upload the approved turnaround and say: "Same exact character as the attached sheet." |
| **Flux / Stable Diffusion** | Use the negative prompt, 30–40 steps, CFG 4–6. For consistency use IP-Adapter FaceID or a character-turnaround LoRA, with the turnaround as the reference image. |
| **Leonardo / Ideogram** | Use "Character Reference" with the turnaround at high strength. |

**Workflow for a consistent character:**
1. Generate **4.1 turnaround** until the face is right. That image becomes the source of truth.
2. Feed it as a reference into **4.2 expressions** and **4.7 poses**.
3. Then generate the three looks (**4.3–5.5**) with the same reference.
4. Generate **4.8 avatar** and **4.9 vector** last, for the app UI.

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

