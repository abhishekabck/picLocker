# Section 6 — The 4 Reads Before You Write a Line

> Consolidated from the prerequisites doc §6 so you don't have to go searching.
> Each section: what it is, the ~5 API calls that matter, a literal snippet,
> the one gotcha, and the official link if you want to go deeper.
>
> Read in order. ~20–30 min each. Goal is recognition, not memorization —
> when you later see these lines in real code, they should look familiar.

---

## 1. Pillow (PIL) — decode / resize / convert / save

**What it is:** the standard Python imaging library. It turns a compressed file
on disk (JPEG/PNG/WebP) into an in-memory image object, lets you do basic
operations, and writes it back out. You will *never* write a decoder; you call
`open()` and get an object.

**The only API you need right now:**

```python
from PIL import Image

img = Image.open("photo.jpg")     # decode: file -> Image object (lazy)
img = img.convert("RGB")          # force 3 channels (drops alpha/EXIF orientation quirks)
small = img.resize((224, 224))    # produce a new, smaller Image (does NOT mutate img)
small.save("thumb.jpg")           # encode + write back to disk
print(img.size)                   # (width, height)  -- note: W,H order, not H,W
print(img.mode)                   # "RGB", "RGBA", "L" (grayscale), "P" (palette)...
```

**Things that bite people:**
- `Image.open()` is **lazy** — it doesn't actually read pixels until you touch
  them (e.g. `.load()`, `.resize()`, `.convert()`). That's why decode errors can
  show up *later* than the `open()` line.
- `.size` is `(width, height)`. NumPy/ML code thinks in `(height, width)`. They
  are transposed. This is a classic off-by-confusion.
- `.resize()` and `.convert()` **return a new image**; they don't modify in place.
- For thumbnails specifically, `img.thumbnail((w, h))` resizes *in place* and
  preserves aspect ratio — different from `.resize()` which forces exact dims.
- HEIC (iPhone) needs an extra plugin (`pillow-heif`); plain Pillow can't open it.
- Wrap decode in `try/except` — corrupt files raise `PIL.UnidentifiedImageError`
  or `OSError`.

**Memory note (matters for your <2GB constraint):** a full 36MP phone photo is
~100MB+ as a raw pixel grid in RAM. Pattern: open → resize down → discard the
big one. Don't hold many full-res grids at once.

**Link:** https://pillow.readthedocs.io/en/stable/handbook/tutorial.html
(stop after `Image.open`, `.resize`, `.convert`, `.save`, `.thumbnail`)

---

## 2. imagehash — perceptual hashing for near-duplicate detection

**What it is:** turns an image into a small hash (default 64-bit) such that
*visually similar* images get *nearly identical* hashes. This catches re-encodes,
re-saves at different quality, minor crops — cases where the byte-level SHA-256
is totally different but the picture looks the same.

**The four algorithms** (all same call shape):

| function          | idea                                  | use |
|-------------------|---------------------------------------|-----|
| `average_hash`    | compare each pixel to the mean        | fast, crude |
| `phash`           | discrete cosine transform (frequency) | **best general default** |
| `dhash`           | compare adjacent pixel gradients      | fast, robust |
| `whash`           | wavelet transform                     | slower |

**The API:**

```python
from PIL import Image
import imagehash

h1 = imagehash.phash(Image.open("photo.jpg"))     # -> ImageHash object
h2 = imagehash.phash(Image.open("photo_resaved.jpg"))

distance = h1 - h2        # Hamming distance: number of differing bits (int)
same = (h1 == h2)         # exact-hash equality (bool)

print(str(h1))            # hex string, e.g. "ffd8a1c3..." -- storable in a DB
# round-trip from stored string:
h = imagehash.hex_to_hash("ffd8a1c3...")
```

**Threshold intuition (you decide the real number, but anchor here):**
- `h1 - h2 == 0` → identical hash (pixels essentially the same).
- `0 < distance <= ~5` → almost always the same photo (re-encode / re-save).
- `distance ~6–10` → maybe; depends on your tolerance.
- `distance > 10` → treat as different photos.
- This is on the **default 64-bit hash**. Bigger `hash_size` = more bits = the
  threshold scales up. Don't compare distances across different hash sizes.

**Why it works (so the threshold isn't magic):** step 1 resizes to ~8×8 and
grayscales — that deliberately throws away resolution and color so two versions
of the same shot collapse to the same low-frequency structure. The hash encodes
that structure. Similar structure → few differing bits.

**Gotcha:** pHash is for "same photo, different bytes." It will NOT match "two
different photos of the same dog" — that's semantic similarity, which is CLIP's
job (§4 below). Don't expect pHash to do CLIP's work or vice versa.

**Link:** https://github.com/JohannesBuchner/imagehash (README is short — read it)

---

## 3. sentence-transformers CLIP — image & text in one embedding space

**What it is:** CLIP produces an embedding (a vector of ~512 floats) for an
**image** AND for **text**, in the *same* space. So the vector for a dog photo
sits close to the vector for the string `"a dog"`. That single fact is what makes
natural-language photo search possible.

**The current API** (important — old tutorials show `util.cos_sim`; the modern
sentence-transformers API uses `model.encode` + `model.similarity`):

```python
from sentence_transformers import SentenceTransformer
from PIL import Image

# Load once. Downloads ~600MB on first run, then cached on disk.
model = SentenceTransformer("sentence-transformers/clip-ViT-B-32")

# Encode an image -> 512-dim vector. Pass a PIL Image directly;
# the model does its OWN preprocessing (resize/normalize) internally.
img_emb = model.encode(Image.open("two_dogs_in_snow.jpg"))

# Encode text -> 512-dim vector(s). Pass a list of strings.
text_emb = model.encode([
    "Two dogs in the snow",
    "A cat on a table",
    "A picture of London at night",
])

# Similarity: rows = images, cols = texts. Higher = more related.
scores = model.similarity(img_emb, text_emb)
print(scores)   # tensor of similarity scores
```

**The big relief:** you do **not** hand-write the §2 preprocessing (resize to
224, normalize with ImageNet mean) for CLIP. `model.encode(PIL_image)` runs the
correct preprocessing internally. You only do manual Pillow resize for *your own*
purposes (thumbnails, the pHash input) — not to feed CLIP.

**Search flow (what you'll actually build):**
1. At ingest: `emb = model.encode(image)` for each photo → store the 512 floats
   in your local index, tied to the photo's ID.
2. At query time: `q = model.encode([user_query_string])` once.
3. Compare `q` against all stored photo embeddings, sort descending, take top N.

**Gotchas:**
- First call is slow (model download + load into RAM). Cache the loaded model;
  don't reload per request. This connects to §8 Q8 in the brief ("what does
  /search return while the model is warming up?").
- `"sentence-transformers/clip-ViT-B-32"` is the standard small CPU-friendly one.
  B-32 = the image-patch size; bigger variants are more accurate but slower.
- CPU inference is fine here (~100ms–1s per image). Never put `.to("cuda")`.
- Embeddings come back as float32; 512 floats ≈ 2KB/photo. 10k photos ≈ 20MB.
  Trivially small — justifies keeping the whole index in RAM (see §4).

**Link:** https://sbert.net/examples/applications/image-search/README.html

---

## 4. NumPy cosine similarity — how "close" is measured

**What it is:** the math operation that turns "are these two vectors similar?"
into one number in `[-1, 1]`. `model.similarity()` (§3) does this for you, but you
must understand it because tutorials say things like "keep results where sim >
0.25" and you need to know that's reasonable, not magic.

**The formula and the primitives:**

```python
import numpy as np

def cosine(a, b):
    return (a @ b) / (np.linalg.norm(a) * np.linalg.norm(b))
    #        dot      magnitude of a       magnitude of b
```

- `a @ b` (or `np.dot(a, b)`) → dot product (a single number).
- `np.linalg.norm(a)` → length/magnitude of the vector.
- Result range: `1.0` = identical direction (same), `0.0` = unrelated,
  `-1.0` = opposite.

**The trick that makes it fast (your <200ms over 10k constraint):** if you
**normalize** every embedding to unit length once (divide each by its norm at
store time), then cosine similarity collapses to a plain matrix multiply:

```python
# index: shape (N, 512), already unit-normalized at ingest time
# query: shape (512,), unit-normalized
sims = index @ query          # shape (N,) -- ALL N cosine sims in one BLAS call
top = np.argsort(-sims)[:20]  # indices of the 20 highest scores
```

10,000 × 512 matmul is ~single-digit milliseconds in NumPy. The real bottleneck
becomes *loading* embeddings from disk — which is the argument for loading the
index into RAM once and keeping it there.

**CLIP-specific number to remember:** absolute cosine scores from CLIP are low —
a "good" text↔image match is often ~0.25–0.35, not 0.9. So you rank by *relative*
order (top-N) rather than trusting an absolute threshold. If you do threshold for
"no results found," tune it empirically against your own library.

**Alternatives you'll see:** `sklearn.metrics.pairwise.cosine_similarity(A, B)`
is a one-liner if you don't want to normalize yourself. Same math, more overhead.

**Link:** any "numpy cosine similarity" SO answer; formula above is the whole story.

---

## How these four snap together (the §5 flow, annotated)

```
new photo
  -> SHA-256 of bytes ............ exact-dup check (not in this doc; trivial)
  -> Pillow open/convert ......... §1
  -> imagehash.phash ............. §2  -> near-dup check (Hamming distance)
  -> model.encode(image) ......... §3  -> 512-d vector -> store in index
  -> upload original to S3

search "sunset"
  -> model.encode(["sunset"]) .... §3
  -> index @ query ............... §4  -> top-N
  -> presigned URLs -> HTML grid
```

The entire ML surface is **two function calls** (`encode` image, `encode` text)
and **one math op** (cosine / matmul). Everything else is the systems plumbing
you already know.
