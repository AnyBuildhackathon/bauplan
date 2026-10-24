# Mechanic loop clips

Endless, transparent animation loops of Mechanic, one per mascot state: `calm`, `talking`, `thinking`, `pleased`, `worried`.
Each clip is 4.7 s, 540x960, 24 fps, with the end crossfaded into the start so it loops without a visible cut.
The pose matches the `../full-<state>.webp` still, but the figure is framed smaller in a taller canvas, so swap the still for `<state>-poster.webp` when you show the loop.

Each state ships in three files with the same picture:

- `<state>.webm`: VP9 with alpha, for Chrome, Edge and Firefox.
- `<state>-hevc.mov`: HEVC with alpha, for Safari and WKWebView (the Tauri desktop app on macOS).
- `<state>-poster.webp`: the first frame as a transparent still, for the poster and for reduced motion.

Use both videos as sources so every browser picks the one it can play with transparency:

```tsx
const loop = (name: string) => `${import.meta.env.BASE_URL}mascot/loops/${name}`;

<video autoPlay loop muted playsInline poster={loop(`${clip}-poster.webp`)} className="h-full w-auto">
  <source src={loop(`${clip}-hevc.mov`)} type='video/mp4; codecs="hvc1"' />
  <source src={loop(`${clip}.webm`)} type="video/webm" />
</video>
```

The HEVC source must come first: Safari would otherwise pick the WebM and drop the alpha channel.
Keep `muted` and `playsInline`, or autoplay is blocked.
Under `prefers-reduced-motion`, show `<state>-poster.webp` instead of the video.
The green-screen masters and sources live in the team Drive under `Content/AnyBuild-Hackathon/mascot-anim/`.
