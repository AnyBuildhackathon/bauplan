// Sketch to build in the chat: a photo of a hand sketch comes in through the image button
// in the composer, a drop anywhere on the chat column, or a paste into the text field.
// It waits as a thumbnail chip until it is sent with the typed text as the note.
import { useEffect, useRef, useState } from "react";
import { ImagePlus, X } from "lucide-react";

const MAX_BYTES = 8 * 1024 * 1024;
const TYPES = ["image/png", "image/jpeg", "image/webp"];

/** The first image among dropped, pasted or picked files, or an error for the user. */
export function pickImage(files: FileList | File[] | null | undefined): { file?: File; error?: string } | null {
  const list = Array.from(files ?? []);
  if (list.length === 0) return null;
  const image = list.find((f) => f.type.startsWith("image/"));
  if (!image) return { error: "Drop a photo of a sketch: PNG, JPEG or WebP." };
  if (!TYPES.includes(image.type)) return { error: "Please send PNG or JPEG." };
  if (image.size > MAX_BYTES) return { error: "The sketch is larger than 8 MB. Take the photo smaller." };
  return { file: image };
}

/** The image button next to the mic; opens the file picker. */
export function SketchButton({ onPick, onError, large = false }: { onPick: (file: File) => void; onError: (text: string) => void; large?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={input}
        type="file"
        accept={TYPES.join(",")}
        className="hidden"
        onChange={(e) => {
          const picked = pickImage(e.target.files);
          if (picked?.file) onPick(picked.file);
          else if (picked?.error) onError(picked.error);
          e.target.value = "";
        }}
      />
      <button
        type="button"
        data-target="sketch_upload"
        onClick={() => input.current?.click()}
        className={`flex shrink-0 items-center justify-center rounded-full bg-tile text-ink-2 transition hover:bg-track hover:text-ink ${large ? "h-11 w-11" : "h-9 w-9"}`}
        title="Build from a photo of a hand sketch (or drop or paste one)"
        aria-label="Attach a sketch photo"
      >
        <ImagePlus className={large ? "h-5 w-5" : "h-4 w-4"} strokeWidth={2} />
      </button>
    </>
  );
}

/** The attached sketch above the composer, until it is sent or removed. */
export function SketchChip({ file, onRemove }: { file: File; onRemove: () => void }) {
  const [preview, setPreview] = useState<string | null>(null);
  useEffect(() => {
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  return (
    <div className="mb-2 flex items-center gap-3 rounded-[16px] bg-card px-2 py-2 shadow-[var(--shadow-pill)] ring-1 ring-[#e2e2dd]" data-target="sketch_attached">
      {preview && <img src={preview} alt="Attached hand sketch" className="h-12 w-16 shrink-0 rounded-[10px] object-cover ring-1 ring-line" />}
      <div className="min-w-0 flex-1 leading-tight">
        <div className="truncate text-[15px] font-semibold text-ink">Hand sketch</div>
        <div className="truncate text-[13px] text-muted">Add a note if you like, then send to build it</div>
      </div>
      <button
        type="button"
        onClick={onRemove}
        className="rounded-full p-1.5 text-faint transition hover:bg-tile hover:text-ink-2"
        title="Remove the sketch"
        aria-label="Remove the sketch"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

/** The whole chat column takes a dropped sketch: spread `handlers` on the column and render `overlay` inside it. */
export function useSketchDrop(enabled: boolean, onPick: (file: File) => void, onError: (text: string) => void) {
  const [over, setOver] = useState(false);
  // dragenter and dragleave fire for every child; count them so the overlay does not flicker.
  const depth = useRef(0);
  const carriesFiles = (e: React.DragEvent) => enabled && Array.from(e.dataTransfer.types).includes("Files");
  const handlers = {
    onDragEnter: (e: React.DragEvent) => {
      if (!carriesFiles(e)) return;
      e.preventDefault();
      depth.current += 1;
      setOver(true);
    },
    onDragOver: (e: React.DragEvent) => {
      if (carriesFiles(e)) e.preventDefault();
    },
    onDragLeave: (e: React.DragEvent) => {
      if (!carriesFiles(e)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setOver(false);
    },
    onDrop: (e: React.DragEvent) => {
      if (!carriesFiles(e)) return;
      e.preventDefault();
      depth.current = 0;
      setOver(false);
      const picked = pickImage(e.dataTransfer.files);
      if (picked?.file) onPick(picked.file);
      else if (picked?.error) onError(picked.error);
    },
  };
  const overlay = over ? (
    <div className="pointer-events-none absolute inset-3 z-20 flex flex-col items-center justify-center gap-2 rounded-[24px] border-2 border-dashed border-accent bg-accent-soft/90 text-center backdrop-blur-sm">
      <ImagePlus className="h-8 w-8 text-accent" />
      <p className="text-[18px] font-semibold text-accent">Drop the sketch to build it</p>
      <p className="text-[14px] text-ink-2">A photo of a hand drawing with its dimensions</p>
    </div>
  ) : null;
  return { handlers, overlay };
}
