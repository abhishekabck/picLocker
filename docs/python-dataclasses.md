# Python Dataclasses — a working reference

> You met one in `ingest.py` (`FileFacts`). This is the mental model + the
> API + the gotchas, with runnable examples and the PicLocker reasoning for
> why it's there.

---

## 1. The problem dataclasses solve

A plain "bag of data" class makes you write the same boilerplate three times:

```python
class FileFacts:
    def __init__(self, path, sha256, size):
        self.path = path
        self.sha256 = sha256
        self.size = size

    def __repr__(self):
        return f"FileFacts(path={self.path!r}, sha256={self.sha256!r}, size={self.size!r})"

    def __eq__(self, other):
        return (self.path, self.sha256, self.size) == (other.path, other.sha256, other.size)
```

You typed `path`, `sha256`, `size` **four times each**. Add a field → edit four
places → forget one → a silent bug. `@dataclass` writes all of that for you
from the field declarations:

```python
from dataclasses import dataclass

@dataclass
class FileFacts:
    path: str
    sha256: str
    size: int
```

That's the *entire* equivalent of the class above. The decorator reads the
annotated class attributes and generates `__init__`, `__repr__`, and `__eq__`.

---

## 2. What it actually generates

From the 3-line version above you get, for free:

```python
f = FileFacts("a.jpg", "abc123", 4096)     # __init__(self, path, sha256, size)
print(f)        # FileFacts(path='a.jpg', sha256='abc123', size=4096)   <- __repr__
f == FileFacts("a.jpg", "abc123", 4096)     # True   <- __eq__ compares field-by-field
```

The **type hints are required** — they're how the decorator discovers the
fields. (They're not enforced at runtime; `@dataclass` doesn't check types.
`size: int` is documentation + field-discovery, not validation.)

---

## 3. Defaults — and the one gotcha that bites everyone

Simple defaults work like function arguments:

```python
@dataclass
class Config:
    bucket: str
    threshold: int = 5          # default
    policy: str = "keep"
```

Fields **with** defaults must come **after** fields **without** (same rule as
function args), or you get a `TypeError` at class-definition time.

**The mutable-default trap.** This is *illegal* and dataclasses will refuse it:

```python
@dataclass
class Bad:
    exts: list = []     # ValueError: mutable default ... is not allowed
```

Why it's banned: a bare `[]` default would be **shared across all instances**
(the classic Python mutable-default bug). Use `field(default_factory=...)` —
a zero-arg callable that produces a **fresh** value per instance:

```python
from dataclasses import dataclass, field

@dataclass
class Good:
    exts: list = field(default_factory=list)        # new [] every instance
    seen: dict = field(default_factory=dict)
    threshold: int = 5
```

Rule of thumb: **immutable default → write it directly** (`int`, `str`, `None`,
tuples). **Mutable default → `default_factory`** (`list`, `dict`, `set`,
objects).

---

## 4. `field()` — per-field control

`field()` configures one field beyond a plain default:

```python
from dataclasses import dataclass, field

@dataclass
class Item:
    name: str
    tags: list = field(default_factory=list)
    _cache: dict = field(default_factory=dict, repr=False)   # hidden from __repr__
    id: int = field(default=0, compare=False)                # ignored by ==
```

Useful `field()` options:
- `default_factory=...` — fresh mutable default (§3).
- `repr=False` — keep a noisy/secret field out of `__repr__`.
- `compare=False` — exclude from `__eq__`/ordering (e.g. a cache or a timestamp).
- `init=False` — not a constructor argument (you set it in `__post_init__`).
- `metadata={...}` — arbitrary dict for your own tooling; dataclasses ignore it.

---

## 5. Methods, properties, `__post_init__`

A dataclass is a **normal class** — you can add regular methods and
`@property`. That's exactly what `FileFacts` does:

```python
@dataclass
class FileFacts:
    sha256: str
    size: int

    @property
    def s3_key(self):                 # derived value, computed on demand
        return f"photos/{self.sha256}"

    def is_large(self):
        return self.size > 100 * 1024 * 1024
```

`s3_key` isn't a *stored* field (no annotation), so it's not in `__init__` or
`__repr__` — it's just a method that derives from the fields. That's why the
S3 key format lives in **one** place.

`__post_init__` runs **right after** the generated `__init__` — for validation
or computing fields from other fields:

```python
@dataclass
class Box:
    width: int
    height: int
    area: int = field(init=False)     # not a constructor arg

    def __post_init__(self):
        if self.width <= 0:
            raise ValueError("width must be positive")
        self.area = self.width * self.height
```

---

## 6. The decorator parameters (`@dataclass(...)`)

```python
@dataclass(frozen=True, order=True, slots=True)
class Point:
    x: int
    y: int
```

- **`frozen=True`** — instances are **immutable**: assigning `p.x = 5` raises
  `FrozenInstanceError`. Also makes the class **hashable** (usable as a dict key
  / set member), because its hash can't change. Use for value objects you don't
  want mutated.
- **`order=True`** — generates `<`, `<=`, `>`, `>=` comparing fields as a tuple
  in declaration order (so you can `sorted()` them). `eq=True` is the default.
- **`slots=True`** (3.10+) — uses `__slots__`: less memory per instance, faster
  attribute access, and blocks accidental new attributes. Nice for objects you
  create in bulk (e.g. one per photo in a 10k ingest).
- `eq=False` — skip `__eq__` (rarely wanted).

---

## 7. Converting to dict / tuple

```python
from dataclasses import asdict, astuple, fields

f = FileFacts("abc", 4096)
asdict(f)     # {'sha256': 'abc', 'size': 4096}   (recurses into nested dataclasses)
astuple(f)    # ('abc', 4096)
[fld.name for fld in fields(f)]   # ['sha256', 'size']  — introspect the fields
```

`asdict` is handy for serialising to JSON or passing as `**kwargs` to a DB
insert. `fields()` lets you loop over the schema programmatically.

---

## 8. When to use a dataclass — and when not

**Use a dataclass when:** you have a bundle of related values that travel
together, and you want clean construction, a readable `repr`, and value
equality — *without* hand-writing boilerplate. (`FileFacts`: the seven facts
about one file, computed once, passed as one object.)

**Reach for something else when:**
- **`typing.NamedTuple`** — you want an *immutable* record that's also a real
  tuple (indexable, unpackable) and ultra-light. `frozen=True` dataclass is the
  more featured cousin; NamedTuple is leaner.
- **`dict`** — the keys are dynamic/unknown at code-time (genuinely arbitrary
  data). If you know the fields, a dataclass beats a dict: attribute access
  (`f.sha256` not `f["sha256"]`), typos caught, autocomplete, a real `repr`.
- **Pydantic `BaseModel`** — you need *runtime type validation/coercion* (e.g.
  parsing untrusted JSON from an API). Dataclasses do **not** validate types.
  FastAPI request bodies → Pydantic; internal value objects → dataclass.
- **A normal class** — the object is mostly *behaviour* (lots of methods, little
  state), not a data bundle.

---

## 9. Why `FileFacts` is a dataclass in PicLocker

Look at what it replaced: `ingest_file` used to compute seven loose locals —
`data_bytes`, `sha256`, `size`, `disk_mtime`, `image_key`, `phash`, `ctype` —
and thread them through every helper as separate arguments. The dataclass:

1. **Bundles** them — `gather_facts(path) -> FileFacts` computes everything
   once; helpers take one `facts` argument instead of seven.
2. **Derives** `s3_key` / `s3_path` as `@property` — the key format exists in
   exactly one place, can't drift.
3. **Reads well in logs/debugging** — `print(facts)` shows every field via the
   free `__repr__`.

(It's deliberately *not* `frozen` here because it carries `data: bytes` and
we don't need hashability; if you ever wanted to use facts as a cache key,
`frozen=True` + dropping the raw bytes would make it hashable.)

---

## 10. Gotchas checklist

- **Type annotations are mandatory** — a class attribute with no annotation is
  *not* a field (it becomes a plain class variable). `x = 5` ≠ `x: int = 5`.
- **Mutable defaults → `field(default_factory=...)`**, never `= []`/`= {}`.
- **Defaulted fields come after non-defaulted** ones.
- **No runtime type checking** — `FileFacts(size="big")` happily stores a
  string. Use Pydantic if you need enforcement.
- **`frozen=True` blocks all assignment**, including inside methods — set
  everything via `__init__`/`__post_init__` (use `object.__setattr__` if you
  truly must mutate a frozen instance in `__post_init__`).
- **Inheritance:** subclass fields append after parent fields; the
  defaulted-after-non-defaulted rule applies across the whole MRO.
