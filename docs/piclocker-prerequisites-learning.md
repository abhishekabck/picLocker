# PicLocker — Prerequisite Knowledge (Self-Study Guide)

> You said: *"I've never processed an image, I don't know how to detect
> duplicates, I don't know how to build an ML model — only some price
> prediction from a tutorial."*
>
> Good. This doc is for that exact starting point. It does **not**
> contain code. It contains the *mental models* you need so that when
> you do read code (in tutorials, docs, examples) it makes sense
> instead of looking like alien runes.
>
> Read this once end-to-end. Don't try to memorize. Goal: when you
> later look at a `from PIL import Image` line, you already know what
> the next 5 lines will be about, even if you can't write them yet.

---

## 0. The single most important thing

You will not be **building** a machine learning model. You will be
**using** one that already exists.

That distinction is everything. Building a model means: collecting
data, choosing an architecture, defining a loss function, training for
hours on a GPU, evaluating, tuning. That's what your price-prediction
tutorial taught you a tiny slice of.

Using a model means: downloading the weights, loading them into RAM,
calling one function with input, getting a number (or a vector of
numbers) back, and doing something with that number.

For PicLocker, every single "ML" thing you do is **using**, not
building. The hardest part of "using" CLIP — the model you'll use — is
remembering which preprocessing the model expects. That's it.

If price prediction made sense to you, this will too. It's a smaller
problem dressed up in scarier vocabulary.

---

## 1. What is an image, to a computer?

A photo on disk is a compressed file: JPEG, PNG, WebP, HEIC. The
compression matters only for storage and bandwidth — once you load it
into memory, all formats become the same thing:

> A 3D grid of numbers. Height × Width × Channels.

For a typical color photo:

- **Height** and **Width** are the pixel dimensions (e.g. 4032 × 3024
  for a phone shot).
- **Channels** are usually 3: Red, Green, Blue. Each channel is a
  number from 0 (no light) to 255 (full intensity).

So a 100×100 RGB image is a grid of 100 × 100 × 3 = **30,000 numbers**.
A 4032 × 3024 phone shot is ~36 million numbers in memory. (This is
why your brief has a "memory under 2 GB" constraint — load too many
of these at full size and you blow RAM.)

When you read about NumPy arrays, tensors, or `shape=(H, W, C)` in
image code, that's all it is. Tensors are just multi-dimensional
arrays. A photo is one. A batch of 32 photos is a tensor of shape
`(32, H, W, 3)`. You add a dimension for "how many," it's still just
nested grids of numbers.

**Loading**: a library (Pillow, OpenCV) reads the JPEG bytes from
disk, runs the decompression algorithm, and hands you back this grid.
You don't write the decoder. You call `open()` and you get the grid.

**Saving**: same in reverse — hand the library a grid, it compresses
and writes a file.

That is the entire image-loading model. The rest is operations *on*
the grid.

---

## 2. The four image operations you actually need

You don't need to learn image processing as a field. You need to know
that these four things exist, what they do, and roughly when to use
them. Look up the API when you write code — don't memorize.

### 2.1 Decode

File on disk → grid of numbers in memory. One function call. Library:
**Pillow** (the standard `PIL` you'll see imported in tutorials).

Failure modes: corrupted file, unsupported format (HEIC needs an
extra library), file too big to fit in RAM. The library will raise
exceptions; you catch them.

### 2.2 Resize

Take a 4032 × 3024 grid and produce a 224 × 224 grid. Why? Because
the ML model you'll use was trained on 224 × 224 images. Feed it
anything else and you get garbage or a crash.

There are multiple resize algorithms (nearest, bilinear, bicubic,
Lanczos). The default is fine for our purpose. Don't fall down that
rabbit hole.

Memory implication: you decode the full 36 MP image into RAM
*briefly*, then resize down. The resized image is tiny (~150 KB). So
the trick is: decode, resize, discard the original — don't hold all
36 MP arrays in memory at once.

### 2.3 Color space conversion

You'll occasionally need to convert between RGB and grayscale, or
between RGB and the model's expected normalization. The model
documentation tells you which. You just call the conversion function.

### 2.4 Normalization

Models don't want raw 0–255 pixel values. They want floats, usually
in the range [0, 1] or [-1, 1], often with the *channel mean* of the
training data subtracted. The model's documentation gives you the
exact numbers (the "ImageNet mean" — `[0.485, 0.456, 0.406]` — shows
up everywhere; if you see those numbers, that's it).

You don't have to know why. You apply the recipe the model docs give
you. Same as how you don't need to know why HTTP uses TCP — you just
follow the spec.

That's it. Decode, resize, color, normalize. **Four steps. Often
collapsed into one helper function called something like
`preprocess()` or `processor()` that the model's library ships with.**

---

## 3. Duplicate detection — three completely different problems

The word "duplicate" hides three separate problems. Knowing which one
you're solving tells you which technique to use.

### 3.1 Exact duplicates

Two files with the **same bytes**. Same photo, same camera, no
re-encoding. Detection is trivial: compute a cryptographic hash
(SHA-256, MD5) of the file bytes. Two files with the same hash are
byte-identical. Probability of collision: zero in practice.

Use when: you want to skip re-uploading a file you've already
uploaded. Always do this first, it's almost free.

### 3.2 Near duplicates (perceptual)

Same photo, but the bytes differ. Examples: someone resized it to
share on WhatsApp (so it's been re-encoded at a different JPEG
quality), or it's been cropped slightly, or rotated. The pixels are
*almost* the same when you look at them, but the byte hash is
completely different.

Detection: **perceptual hashing**. The idea is dumb-simple and
genius:

1. Resize the image to something tiny like 8×8.
2. Convert to grayscale (so color shifts don't matter).
3. Compute some simple summary of those 64 pixels (the average, or a
   discrete cosine transform of them).
4. Threshold each pixel against the summary — 1 if above, 0 if below.
5. You now have a 64-bit number.

Two visually-similar images produce nearly-identical 64-bit numbers.
You compare two images by counting the bits that differ (this is
called **Hamming distance**). If fewer than, say, 5 bits differ,
they're "the same photo."

The library that does all of this is called `imagehash`. You give it
a Pillow image, it gives you the 64-bit hash. You don't have to
implement any of step 1-5 — but you should understand WHY it works,
because then the threshold tuning makes sense.

Use when: dedup before storing.

### 3.3 Semantic duplicates ("same scene, different photo")

Two completely different photos of the same dog from different
angles. Or two screenshots of the same web page taken at different
times. The pixels are not "the same image," but the *content* is the
same.

This needs an **ML model** to recognize what's in the image. That's
what CLIP is for, and that's the bridge into the next section.

For PicLocker, you don't strictly need to dedup at this level — the
brief asks for "visually the same photo," which is §3.2 territory.
But you'll *use* the same machinery (image embeddings) for search, so
you get this capability for free.

---

## 4. ML — the only concepts you actually need

Forget loss functions, backprop, optimizers, learning rates, train/
val/test splits. None of that is relevant to *using* a model. Here's
what is.

### 4.1 What a model is, mechanically

For our purposes: a model is a big function. It takes an input
(numbers — your normalized image grid) and produces an output
(numbers — could be a probability, a class label, or a vector). The
function has billions of internal parameters that were set by
training, and you'll never touch them. Loading a model = loading
those parameters from disk into RAM.

You feed input. You get output. That's it. The forward pass.

### 4.2 Embeddings

This is **the** concept that makes the project work, and it's
beautiful.

An **embedding** is a list of numbers — typically 512 or 768 of them —
that represents the **meaning** of something. The model produces it.
Two things with similar meanings produce similar lists of numbers.

So if you embed a photo of a dog, you get a 512-number vector. If you
embed another photo of a dog, you get a different 512-number vector
that is *close* to the first one (in some mathematical distance
sense). If you embed a photo of a calculator, you get a vector that
is *far* from both.

Embeddings turn semantic similarity ("are these photos *about* the
same thing?") into a math problem ("are these vectors close to each
other?").

### 4.3 Cosine similarity

How do you measure "close" between two 512-number vectors? The most
common answer: **cosine similarity**. It's a number between -1 and 1.

- 1.0 = pointing in the same direction = "the same"
- 0.0 = perpendicular = "unrelated"
- -1.0 = opposite directions = "opposite"

The math is one line and NumPy has a primitive for it. You will not
implement it; you will call it. But know the range, because tutorials
will say things like "filter results where similarity > 0.25" and you
need to know that's reasonable, not magical.

### 4.4 CLIP — the specific model you'll use

CLIP (Contrastive Language–Image Pre-training, by OpenAI, 2021) does
one specific magic trick:

> It produces embeddings for **images** AND **text** in the *same*
> vector space.

Why this is a big deal: you can embed the photo of a dog, embed the
text *"a dog"*, and the two vectors will be close. You can embed the
photo and the text *"a calculator"* and they'll be far.

This is exactly what natural-language image search is. A user types
"sunset," you embed the text, you compare against the pre-computed
embeddings of all the photos in your library, you return the top N
photos whose vectors are closest to the text vector.

You never train CLIP. You download it (one of several public
versions, ~150 MB to ~600 MB). You load it. You call `encode_image()`
on a preprocessed image and get a vector. You call `encode_text()` on
a string and get a vector. That's the whole API.

The library that makes this nice in Python is **sentence-transformers**
(or `transformers` directly if you want more control). Their CLIP
example is ~5 lines of code. Read it.

### 4.5 What "running inference on CPU" means

Inference = the forward pass = "I have a trained model, give me an
output for this input." You can do it on a GPU (fast) or a CPU
(slower but everyone has one).

For PicLocker, CPU is fine because:
- The model is small (CLIP-base is ~150 MB).
- You're processing photos at the rate they appear, not in
  bulk-training scale.
- Per-image inference on CPU is ~100ms-1s. For 1,000 photos that's
  ~10 minutes — acceptable for a one-time backfill.

"CPU inference" in code just means: don't put `.to("cuda")` anywhere.

---

## 5. Putting it together — the mental flow of PicLocker

You can now read this and it should make sense:

1. New photo lands in the watched folder.
2. Read its bytes. Compute its SHA-256. Already in DB? Skip.
   *(That's §3.1 — exact dup check.)*
3. Decode it into a pixel grid with Pillow.
   *(That's §2.1.)*
4. Make a small thumbnail copy of the grid for the perceptual hash.
   Compute the pHash. Compare against your DB of pHashes. Close to an
   existing one? Skip the upload, record the relationship.
   *(That's §2.2 + §3.2.)*
5. Make another small copy of the grid sized for CLIP (224×224).
   Normalize it the way CLIP wants. Feed it to CLIP. Get back a
   512-number embedding vector. Store the vector in your search
   index, tied to the photo's ID.
   *(That's §2.2 + §2.4 + §4.4.)*
6. Upload the *original* photo bytes (not the resized ones — those
   were only for the model) to your PersonalS3 bucket.
7. Done with this photo.

Later, when the user searches "sunset":

1. Embed the text "sunset" with CLIP's text encoder. You get a 512-
   number vector.
2. Cosine-similarity-compare it against every photo's stored vector.
   Sort descending. Take top 20.
   *(That's §4.3.)*
3. For each of those 20 photos, generate a presigned PersonalS3 URL.
4. Render an HTML page with 20 `<img src="...">` tags pointing at the
   presigned URLs.
5. The browser fetches the actual image bytes directly from
   PersonalS3, not through your server.

Notice how small the "ML" footprint is. Two function calls
(`encode_image`, `encode_text`) and one math operation (cosine
similarity). Everything else is plain systems programming you already
know — files, hashes, databases, HTTP, HTML.

---

## 6. The 4 things to learn before you write your first line

Not "watch a 12-hour Udemy course." Specifically these four reads,
roughly 30–60 minutes each:

1. **Pillow basics.** Read the official Pillow tutorial up to the
   point where you've seen `Image.open()`, `.resize()`,
   `.convert("RGB")`, `.save()`. Stop there. You don't need filters,
   draw, ImageOps yet.
2. **`imagehash` README.** It's short. Read the section on what
   pHash is, how to compute one, and what Hamming distance means in
   their API. You're done.
3. **sentence-transformers' CLIP example page.** Find the snippet
   titled something like "Image Search" or "CLIP." Read it twice.
   The first time it'll feel dense. The second time you'll realize
   it's six lines doing exactly what §5 describes. Look up any
   unfamiliar function in their API docs.
4. **NumPy cosine similarity / dot product.** One Stack Overflow
   answer's worth. Know that `(a @ b) / (||a|| * ||b||)` is the
   formula and that `np.dot` + `np.linalg.norm` are the primitives.
   `sklearn.metrics.pairwise.cosine_similarity` also exists if you
   want a one-liner.

If you read those four things in order, you have everything you need
for the ML+image side of PicLocker. The rest is systems work, which
you already have the muscles for.

---

## 7. Confidence-building exercises (no code, just thinking)

Do these in your head or on paper before you touch a keyboard. They'll
expose any gaps in the mental model above.

1. *"I have two JPEG files. They look like the same photo to me. Their
   byte hashes differ. What might be true?"* (Answer: one was
   re-encoded, cropped, re-saved at different quality, or had EXIF
   data stripped. Bytes differ, pixels nearly identical.)
2. *"Why do I resize images to 224×224 before feeding them to CLIP,
   and not 800×600 (a more 'photographic' size)?"* (Answer: the model
   was trained on a specific input shape; deviating gives wrong
   results or errors.)
3. *"I have a CLIP embedding for a photo of my cat. I want to find
   'photos similar to this one.' What do I compute?"* (Answer: cosine
   similarity between this embedding and every other photo's
   embedding. Rank by descending similarity.)
4. *"I have 10,000 photos. Each embedding is 512 floats = 2 KB. How
   much disk does my search index take?"* (Answer: 10,000 × 2 KB =
   20 MB. Trivially small. Justifies storing them on local disk.)
5. *"I want search to return in < 200 ms over 10,000 photos. What's
   the bottleneck?"* (Answer: 10,000 cosine similarities is ~5 ms
   in NumPy if you batch it. Easy. Bottleneck becomes loading the
   embeddings from disk — which is why you keep them in RAM after
   first load.)
6. *"I detect that a photo is a near-duplicate of one already in my
   library. What do I do — skip it entirely? Store a pointer? Replace
   the existing one with this one? Ask the user?"* (Answer: design
   decision from §8 of the brief. You decide and defend it.)

If those felt comfortable, you are ready.

If any of them felt fuzzy — that's exactly what to re-read above.

---

## 8. Things you do NOT need to learn

Crossing these out so you don't get sucked in:

- ❌ Neural network architecture (CNNs, transformers, attention).
  You're using a pre-trained model; you don't need to know what's
  inside.
- ❌ How to train a model. Not this project.
- ❌ Fine-tuning. Not this project.
- ❌ GPU programming, CUDA, ONNX optimization. CPU is fine here.
- ❌ Computer vision theory (edge detection, SIFT, SURF, HOG). You
  used to need these. Pre-trained embeddings make most of it
  obsolete for this use case.
- ❌ Image augmentation (rotation/flip/blur for training). You're
  not training.
- ❌ Quantization, distillation, pruning. Same reason.

Anything you read about that mentions these concepts is for
*building* models, not using them. Close the tab.

---

## 9. How to start the new chat (so this S3 conversation stays clean)

Two paths. Pick one.

### Option A — fresh Claude Code session in a new project directory

```
mkdir -p ~/Projects/piclocker
cd ~/Projects/piclocker
git init
claude
```

That gives you a brand-new conversation in an empty repo, with no
PersonalS3 context bleeding in. In that fresh chat, your opening
message can be something like:

> *"I'm starting a project called PicLocker. The full brief is at
> `~/Downloads/piclocker-problem-brief.md`. My prerequisite notes
> (what I do and don't know) are at
> `~/Downloads/piclocker-prerequisites-learning.md`. Read both, then
> ask me what I want to design first."*

Claude in the fresh session will read those two files and you're off.

### Option B — clear context in the current session

In the current Claude Code session, type `/clear` to wipe conversation
context. Then `cd` somewhere else (so the working-directory context
changes) and start with the same kind of opening message as above.

Option A is cleaner. Option B is faster.

---

## 10. The honest pep talk

You said *"I don't have any idea how to detect objects in an image or
how to build an ML model."* True six hours ago. After reading this doc
+ the four 30-minute reads in §6, that statement won't be true anymore.

You will not be a computer-vision researcher. You will be a competent
**user** of computer vision, which is the actual job in 99% of
real-world ML work today. The people building the models are <1% of
the industry. The other 99%+ are doing exactly what you're about to
do: pick a pre-trained model, write the systems plumbing around it,
ship a product.

The systems plumbing — async pipelines, multipart uploads, dedup
strategy, CI/CD, idempotency under crash — is the *hard* part of this
project. And that's the part you're already comfortable in. The ML
part is the *easy* part. You just hadn't been told that yet.

Now go.
