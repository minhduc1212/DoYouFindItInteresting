"""
extract_article.py — Parallel, high-detail article summarizer
─────────────────────────────────────────────────────────────
  • Parallel chunk extraction   → ThreadPoolExecutor
  • Context carry-over overlap  → tail of chunk N prepended to chunk N+1
  • Auto-retry w/ backoff       → resilient against transient API errors
  • Strict output normalization → handles any LLM format deviation
  • Ideas as structured list    → each idea: {title, paragraph}
  • Smarter consolidation       → preserves ALL unique evidence
  • Detailed QA report          → sentence count per idea + title preview

Output shape
────────────
{
  "title":       str,
  "source_url":  str,
  "source_type": str,
  "ideas": [
      {"title": "Short idea heading", "paragraph": "6-10 sentence prose..."},
      ...
  ],
  "content": str,          # ideas joined as ### heading\\n paragraph (compat)
  "terms":   [(str, str)]
}
"""

import json
import re
import os
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
import dotenv

dotenv.load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# Model registry
# ─────────────────────────────────────────────────────────
MODEL_CONFIG: dict[str, dict] = {
    "nvidia/llama-3.3-nemotron-super-49b-v1": {
        "max_input_chars": 500_000,
        "max_tokens":      8192,
        "max_workers":     4,
    },
    "google/gemma-4-31b-it": {
        "max_input_chars": 400_000,
        "max_tokens":      8192,
        "max_workers":     4,
    },
    "deepseek-ai/deepseek-r1": {
        "max_input_chars": 500_000,
        "max_tokens":      8192,
        "max_workers":     2,
    },
}
DEFAULT_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1"

OVERLAP_CHARS = 600

SYSTEM_PROMPT = (
    "You are an expert research analyst and technical writer. "
    "Extract structured data from articles and write rich, exhaustive, "
    "publication-quality analytical summaries. "
    "Output ONLY raw valid JSON — no markdown, no code fences, no extra text."
)

# ─────────────────────────────────────────────────────────
# Chunking
# ─────────────────────────────────────────────────────────

def smart_chunk(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    while len(text) > max_chars:
        idx = text.rfind("\n\n", 0, max_chars)
        if idx == -1:
            idx = max(text.rfind(". ", 0, max_chars),
                      text.rfind(".\n", 0, max_chars))
        if idx == -1:
            idx = max_chars
        chunks.append(text[:idx].strip())
        text = text[idx:].strip()
    if text:
        chunks.append(text)
    return chunks


def attach_overlap(chunks: list[str], overlap_chars: int = OVERLAP_CHARS) -> list[str]:
    if len(chunks) <= 1:
        return chunks
    result = [chunks[0]]
    for i in range(1, len(chunks)):
        tail = chunks[i - 1][-overlap_chars:]
        dot  = tail.find(". ")
        if dot != -1:
            tail = tail[dot + 2:]
        context = (
            "WARNING: CONTEXT FROM PREVIOUS SECTION (do NOT summarize or extract again):\n"
            "--------------------------------------------------------------------------\n"
            f"{tail.strip()}\n"
            "--------------------------------------------------------------------------\n"
            "Use the context above ONLY to resolve references in the article below.\n\n"
        )
        result.append(context + chunks[i])
    return result


# ─────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────

def call_api(
    client: OpenAI,
    model: str,
    prompt: str,
    max_tokens: int,
    retries: int = 3,
    backoff: float = 2.0,
) -> str:
    for attempt in range(1, retries + 1):
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.15,
            )
            return r.choices[0].message.content or ""
        except Exception as exc:
            wait = backoff ** attempt
            log.warning("API error (attempt %d/%d): %s — retrying in %.1fs",
                        attempt, retries, exc, wait)
            if attempt == retries:
                raise
            time.sleep(wait)
    return ""


def parse_json(raw: str) -> dict:
    """Extract JSON object from raw LLM output, repair trailing commas."""
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$",          "", raw).strip()
    m   = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", m.group(0))
        try:
            return json.loads(cleaned)
        except Exception:
            return {}


def count_sentences(text: str) -> int:
    return len(re.findall(r"[.!?]+", text))


# ─────────────────────────────────────────────────────────
# Output normalizer
# Converts ANY LLM response shape → canonical ideas list
# ─────────────────────────────────────────────────────────

def _normalize_ideas(data: dict, chunk_idx: int = 0) -> list[dict]:
    """
    Accept whatever the LLM returned and always produce:
        [{"title": str, "paragraph": str}, ...]

    Handles every known deviation:
      • Correct:   data["ideas"] = [{"title":..., "paragraph":...}]
      • Old fmt:   data["content"] = "Para1\\n\\nPara2"  (no ideas key)
      • Flat str:  data["ideas"] = "some text"
      • Bad keys:  {"heading":..., "text":...} / {"idea":..., "content":...}
      • Mixed:     some items correct, some dicts with wrong keys
    """
    # ── Case 1: proper ideas list ────────────────────────
    raw_ideas = data.get("ideas")
    if isinstance(raw_ideas, list) and raw_ideas:
        normalized: list[dict] = []
        for i, item in enumerate(raw_ideas, 1):
            if not isinstance(item, dict):
                continue
            # Tolerate alternate key names the LLM might use
            title = (
                item.get("title")
                or item.get("heading")
                or item.get("idea")
                or item.get("name")
                or f"Idea {chunk_idx}.{i}"
            )
            paragraph = (
                item.get("paragraph")
                or item.get("content")
                or item.get("text")
                or item.get("summary")
                or item.get("body")
            )
            if paragraph and str(paragraph).strip():
                normalized.append({
                    "title":     str(title).strip(),
                    "paragraph": str(paragraph).strip(),
                })
        if normalized:
            return normalized

    # ── Case 2: ideas is a plain string (LLM forgot the list) ──
    if isinstance(raw_ideas, str) and raw_ideas.strip():
        return _split_content_string(raw_ideas, chunk_idx)

    # ── Case 3: old-style "content" string, no ideas key ────
    content = data.get("content") or data.get("text") or data.get("summary") or ""
    if isinstance(content, str) and content.strip():
        return _split_content_string(content, chunk_idx)

    return []


def _split_content_string(text: str, chunk_idx: int = 0) -> list[dict]:
    """
    Convert a plain multi-paragraph string into ideas list.
    Tries to detect ### headings; falls back to paragraph splitting.
    """
    text = text.strip()
    ideas: list[dict] = []

    # ── Try: ### Heading\\nParagraph format ──────────────
    sections = re.split(r"\n#{1,3}\s+", text)
    if len(sections) > 1:
        for i, section in enumerate(sections, 1):
            lines = section.strip().splitlines()
            if not lines:
                continue
            title     = lines[0].strip().rstrip("#").strip() or f"Idea {chunk_idx}.{i}"
            paragraph = " ".join(lines[1:]).strip()
            if paragraph:
                ideas.append({"title": title, "paragraph": paragraph})
        if ideas:
            return ideas

    # ── Fallback: split on blank lines ───────────────────
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    for i, para in enumerate(paragraphs, 1):
        ideas.append({
            "title":     f"Idea {chunk_idx}.{i}",
            "paragraph": para,
        })
    return ideas


def _normalize_terms(data: dict) -> list[list]:
    """Extract and validate terms list from any response shape."""
    raw = data.get("terms") or data.get("glossary") or data.get("definitions") or []
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            term, defn = str(item[0]).strip(), str(item[1]).strip()
            if term and defn:
                result.append([term, defn])
        elif isinstance(item, dict):
            term = str(item.get("term") or item.get("name") or "").strip()
            defn = str(item.get("definition") or item.get("description") or
                       item.get("meaning") or "").strip()
            if term and defn:
                result.append([term, defn])
    return result


# ─────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────

EXTRACT_PROMPT = """\
Analyze the article{part_note} and return ONLY a valid JSON object.

━━━━ REQUIRED JSON STRUCTURE ━━━━
{{
    "title":       "Exact article title",
    "source_url":  "{source_url}",
    "source_type": "{source_type}",
    "ideas": [
        {{
            "title":     "Short specific heading, 5-10 words",
            "paragraph": "6-10 sentence analytical prose"
        }}
    ],
    "terms": [["Term", "2-4 sentence definition."]]
}}

━━━━ ideas RULES ━━━━
1. Extract EVERY distinct idea, finding, event, mechanism, or argument — omit nothing.
2. Each object in "ideas" has exactly two keys: "title" and "paragraph".
3. "title": 5-10 words, names the specific concept.
   GOOD → "Sparse Attention Reduces Quadratic Memory Cost"
   BAD  → "Key Finding" / "Overview" / "Important Point"
4. "paragraph": analytical prose with this 4-part structure (no labels/headers):
     PROBLEM → MECHANISM → EVIDENCE → SIGNIFICANCE
5. SENTENCE RULE: paragraph = MINIMUM 6, MAXIMUM 10 sentences.
   Every sentence must carry unique information. No padding or repetition.
6. If a CONTEXT block appears before the article: use it ONLY to resolve
   cross-references — do NOT extract or summarize content from it.

━━━━ terms RULES ━━━━
• 3-6 terms from THIS part only.
• Each term: ["Term name", "2-4 sentence definition."]
• Sentence 1: precise standalone definition. Sentence 2: mechanism.
• Never use "as mentioned above".

Output ONLY the JSON. No markdown, no explanation.

━━━━ ARTICLE{chunk_label} ━━━━
{content}
"""

CONSOLIDATE_PROMPT = """\
Consolidate the ideas extracted chunk-by-chunk into one clean, exhaustive summary.
Duplicates and near-duplicates must be merged. Nothing unique may be dropped.

━━━━ REQUIRED JSON STRUCTURE ━━━━
{{
    "ideas": [
        {{
            "title":     "Short specific heading, 5-10 words",
            "paragraph": "6-10 sentence analytical prose"
        }}
    ],
    "terms": [["Term", "2-4 sentence definition."]]
}}

━━━━ CONSOLIDATION RULES ━━━━
1. MERGE overlapping ideas into one authoritative entry.
2. KEEP every unique fact, mechanism, data point, or example.
3. "paragraph" structure: PROBLEM → MECHANISM → EVIDENCE → SIGNIFICANCE
4. SENTENCE RULE: paragraph = MINIMUM 6, MAXIMUM 10 sentences.
   Keep the most evidence-rich sentences. Remove restatements.
5. "title": 5-10 words, specific concept name — no generic labels.
6. Order: foundational concepts → applications → implications.
7. Merge terms: 6-12 unique, best definition wins near-duplicates.

Output ONLY the JSON. No markdown, no explanation.

━━━━ RAW IDEAS ━━━━
{raw_ideas}

━━━━ RAW TERMS ━━━━
{raw_terms}
"""

# ─────────────────────────────────────────────────────────
# Worker
# ─────────────────────────────────────────────────────────

def _extract_chunk(
    idx: int,
    total: int,
    chunk: str,
    source_url: str,
    source_type: str,
    client: OpenAI,
    model: str,
    max_tokens: int,
) -> dict:
    part_note   = f" (Part {idx} of {total})" if total > 1 else ""
    chunk_label = f" — Part {idx}/{total}"    if total > 1 else ""
    log.info("Pass 1 — chunk %d/%d  (%s chars)", idx, total, f"{len(chunk):,}")

    prompt = EXTRACT_PROMPT.format(
        part_note=part_note,
        source_url=source_url,
        source_type=source_type,
        chunk_label=chunk_label,
        content=chunk,
    )
    raw  = call_api(client, model, prompt, max_tokens)
    data = parse_json(raw)

    if not data:
        log.error("Chunk %d — JSON parse failed entirely.", idx)
        return {"idx": idx, "data": {}}

    ideas = _normalize_ideas(data, chunk_idx=idx)
    terms = _normalize_terms(data)

    if not ideas:
        log.warning("Chunk %d — no ideas extracted after normalization.", idx)

    return {
        "idx":   idx,
        "data":  {
            "title":  data.get("title", ""),
            "ideas":  ideas,
            "terms":  terms,
        },
    }


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def _ideas_to_content(ideas: list[dict]) -> str:
    """Flatten to ### heading + paragraph string (backward compat)."""
    return "\n\n".join(
        f"### {idea['title']}\n{idea['paragraph']}"
        for idea in ideas
    )


# ─────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────

def extract_article_data(
    content: str,
    source_url:       str      = "",
    source_type:      str      = "Article",
    model:            str      = DEFAULT_MODEL,
    chunk_size_chars: int      = 20_000,
    overlap_chars:    int      = OVERLAP_CHARS,
    max_workers:      int|None = None,
) -> dict:
    t0 = time.perf_counter()

    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=os.environ.get("NVIDIA_API_KEY", "YOUR_NVIDIA_API_KEY"),
    )
    cfg               = MODEL_CONFIG.get(model, {"max_input_chars": 400_000, "max_tokens": 8192, "max_workers": 3})
    max_content_chars = min(int(cfg["max_input_chars"] * 0.75), chunk_size_chars)
    workers           = max_workers or cfg.get("max_workers", 3)

    raw_chunks = smart_chunk(content, max_content_chars)
    chunks     = attach_overlap(raw_chunks, overlap_chars) if overlap_chars > 0 else raw_chunks
    total      = len(chunks)
    log.info("Model: %s | chunks: %d | overlap: %d chars | workers: %d",
             model, total, overlap_chars, workers)

    # ── Pass 1: parallel extraction ──────────────────────
    results: list[dict] = [{}] * total

    with ThreadPoolExecutor(max_workers=min(workers, total)) as pool:
        futures = {
            pool.submit(
                _extract_chunk, idx, total, chunk,
                source_url, source_type, client, model, cfg["max_tokens"],
            ): idx
            for idx, chunk in enumerate(chunks, 1)
        }
        for future in as_completed(futures):
            try:
                res = future.result()
                results[res["idx"] - 1] = res["data"]
            except Exception as exc:
                log.error("Chunk failed: %s", exc)

    # ── Aggregate ────────────────────────────────────────
    final_title = ""
    all_ideas:  list[dict] = []
    all_terms:  list[list] = []
    seen_terms: set[str]   = set()

    for idx, data in enumerate(results, 1):
        if not data:
            continue
        if idx == 1 and data.get("title"):
            final_title = data["title"]
        all_ideas.extend(data.get("ideas", []))
        for term in data.get("terms", []):
            name = term[0].strip().lower()
            if name not in seen_terms:
                all_terms.append(term)
                seen_terms.add(name)

    # ── Pass 2: consolidate ───────────────────────────────
    if total > 1 and all_ideas:
        log.info("Pass 2 — consolidating %d ideas...", len(all_ideas))
        c_prompt = CONSOLIDATE_PROMPT.format(
            raw_ideas=json.dumps(all_ideas,  ensure_ascii=False),
            raw_terms=json.dumps(all_terms,  ensure_ascii=False),
        )
        try:
            c_data = parse_json(call_api(client, model, c_prompt, cfg["max_tokens"]))
            consolidated = _normalize_ideas(c_data, chunk_idx=0)
            if consolidated:
                all_ideas = consolidated
            c_terms = _normalize_terms(c_data)
            if c_terms:
                all_terms = c_terms
        except Exception as exc:
            log.warning("Consolidation failed (%s) — using raw extraction.", exc)

    elapsed = time.perf_counter() - t0

    # ── QA report ────────────────────────────────────────
    print(f"\n{'═'*62}")
    print(f"  QA REPORT  {'(consolidated)' if total > 1 else '(single pass)'}")
    print(f"  Elapsed      : {elapsed:.1f}s")
    print(f"  Chunks       : {total}  (overlap: {overlap_chars} chars)")
    print(f"  Ideas        : {len(all_ideas)}")
    print(f"  Terms        : {len(all_terms)}")
    print(f"{'─'*62}")
    bad = 0
    for i, idea in enumerate(all_ideas, 1):
        n  = count_sentences(idea["paragraph"])
        ok = 6 <= n <= 10
        if not ok:
            bad += 1
        flag = "✅" if ok else "⚠️  expected 6-10"
        print(f"  #{i:02d} {flag}  ~{n:2d} sent  │ {idea['title'][:46]}")
    print("  All ideas within sentence rule ✅" if bad == 0
          else f"  {bad} idea(s) outside sentence rule ⚠️")
    print(f"{'═'*62}\n")

    return {
        "title":       final_title,
        "source_url":  source_url,
        "source_type": source_type,
        "ideas":       all_ideas,
        "content":     _ideas_to_content(all_ideas),
        "terms":       [tuple(t) for t in all_terms],
    }


# ─────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    sample_content = """For two years, this drug was a miracle. It was introduced in 1996 to treat HIV. And by 1998, 75,000
patients across the country were taking up to 20 of them every day. It's called ritonavir, and it turned a certain death
into a manageable condition. This particular pill is on its way to quality control to
a dissolution tester. Here, analysts monitor
each batch of capsules, checking that they do
dissolve in around 30 minutes, which is quickly enough
to be absorbed properly. It's a rigorous precaution for a drug that for two years and
240 consecutive lots has never failed.
(grim music) But now an analyst sees something unusual. This capsule hasn't dissolved properly. So they follow protocol and
trigger an emergency shutdown. (alarm blaring) They destroy the entire batch and deep clean the production line to eliminate any possible
traces of contamination. But the next day, at quality control, the same thing happens. On the line the clear capsules
are turning white and cloudy, technicians at the nearby
research and development lab study the paste under a microscope and find they're filled with
millions of tiny needles. They're crystals, but no
one has seen them before. They need a control to
compare the needles against, so they make some of their
own ritonavir in the lab, but to their horror, it
also comes out cloudy. So they try again, but all
attempts yield the same result: a white paste every time.
(subdued music) The researchers are stumped. They had been making
ritonavir for two years. They knew its exact chemical composition and every part of the
process used to make it, so they check all the
input ingredients again, all the settings, every
temperature setting and procedure. But all of it seems to be done correctly. Yet at the factory, the cloudy capsules are appearing
more and more frequently. Within a week, every tablet produced by either the lab or the
factory comes out cloudy. Abbott needs to halt all production of ritonavir immediately. But they can't just cut off the supply because people need these tablets. - [Narrator] "We called on as
many resources as we could. We tried everything. We conducted countless experiments. We rebuilt facilities and new lines. We looked at alternative sites to see if we could start
clean in a new environment." (gentle music) - And they found an alternative
site, a factory in Italy. They start ritonavir production there, and to their relief, all the pills passed the dissolution test. This is great news. But it also means that Chicago must have
been making a mistake. So a team of scientists flies over to look at what the Italians
are doing differently. They check everything, the
pressure, temperature, humidity, the exact weight of all the chemicals, but it all matches perfectly with what they're doing in Chicago. None of it makes any sense. But at least Italy can
keep making the medicine. (phone ringing)
(soft brooding music) But when the Chicago team
returns home, they get a call. It's from Italy. Within days after their visit, one of the tablets fails
the dissolution test. - [Narrator] "There was no gradual trend. There was no early warning. In a matter of weeks,
maybe five or six weeks, every place the product was became contaminated with the crystals. We did not know how to detect it. We did not know how to test for it. We did not know what caused it. We did not know how to prevent it. We did not know how to get rid of it. And we kept asking the
question, 'Why now?'" - They were witnessing a rare disaster. It had happened before, and
in theory could happen again to just about any drug
or chemical compound. It spreads like a disease, but the thing that's getting
infected is the medicine. One day you can make it,
the next it's gone forever. - [Narrator] "It is frightening
that this could happen to any drug that we've taken
on, which we're dependent." - And the scariest part is you can't predict if it will
happen, when it will happen, or to which medicine or compound. Overnight, drugs we all rely
on might just disappear. So what was happening inside
those ritonavir capsules? What were those crystals inside? They appeared to be an
entirely new compound, but when they tested them, everything indicated they were ritonavir. It sounds impossible, but something similar had
actually been the center of a heated debate 170 years earlier. (mellow music) - [Casper] In his Paris laboratory, chemist Justus von Liebig
was reading a paper. It was about a newly discovered compound, and what elements it was made of. This kind of work was at the cutting edge
of chemical research. Research he knew better than almost anyone because he had personally
pioneered most of it. This had made him highly
respected in his field, but he also had a reputation for being difficult to work with. He was arrogant, hot-tempered,
and didn't suffer fools. And the more he read this paper, the more incensed he got, because to him, it was clearly written by
a fool, Friedrich Wöhler. So we headed over to the lab at Imperial to recreate what Wöhler
claimed to have discovered. - So I've got it here wrapped in foil because it is a bit photo-sensitive. - [Casper] It's a bit like,
like, little rocks in there. - Yeah. - Beige powder, okay. Made of one silver, one
nitrogen, one oxygen, and one carbon.
- Exactly. - (laughs) You wanna light it up? - Yeah, sure, let's do it. You seem quite excited. - I am quite excited. Yeah. Not much is happening. Oh, it's melting a little, or it's, like, it is getting a little discolored. - [Dr. Kafizas] Yes, it is. - I guess the issue was he said, "Okay, I found this beige powder and I know exactly what it's made of, one silver, one carbon, one
nitrogen, and one oxygen." He publishes this.
(curious music) The paper reaches Liebig, and he is like, "There's no way, because I've
just discovered that compound. And when I tried to put a flame to it, it behaves completely differently." And we've got some of that right here too. (serious music) Should we try to burn this one? - Yeah. I made some fresh this morning. Let's just see how a small amount behaves. So we're gonna go with, I don't know, maybe a few milligrams. I've left it a bit moist. When it's in its moist-
(compound snaps) Oh!
- Oh, my God. I didn't expect that.
- Yeah! - It's so loud.
(Dr. Kafizas laughs) - It's very sensitive. I'm sorry about that.
- That is crazy. - [Dr. Kafizas] And that
was just a small amount. - Oh my God, my ears. What? I was not ready for that. - I wasn't ready for that either. I made it moist so that it's less likely to self-detonate, but clearly I was wrong. - Clearly Wöhler had made a mistake. These can't possibly be made
of exactly the same elements. So Liebig wrote a paper
slamming Wöhler's work, calling him a "hopeless analyst" and saying he should go
back, check his work, and publish again when
he's found his mistake. And Wöhler does exactly that. He checks his work but finds no mistakes. So now he's even more
sure that he's correct. So he writes up his
results in a second paper, but Liebig wasn't having any of this and replies with another
paper saying he must be wrong. So this public back-and-forth
continues for two years, with each side becoming
more and more convinced that the other is out of their mind, until finally they agreed to meet on neutral ground in Frankfurt to put this whole thing
to bed once and for all. They would replicate each other's work and let the results speak for themselves. But when they did, they were stunned. Before we continue, I
want to quickly thank SoFi for sponsoring this part of the video. You know, one of the simplest
ways to build wealth over time is by earning compound
interest on your money. There's this quote from
Albert Einstein that says, "Compound interest is the
eighth wonder of the world. He who understands it, earns it; he who doesn't, pays it." And yet many people don't put their money in a savings account,
which kind of makes sense because most banks give
you next to nothing, a fraction of a percent worth of interest. And at that rate, you can't
even keep up with inflation. But with today's sponsors,
SoFi, you can change that. SoFi is an all-in-one finance app that lets you bank, borrow, and invest. When you open a SoFi
checking and savings account and set up an eligible direct deposit, you earn a competitive APY. You don't have to pay any account fees. That means your money isn't just sitting there, it's working. And every dollar you put in can
earn more and more interest. And over time, that really adds up. Einstein called it the
eighth wonder for a reason. Of course, the exact amount depends on several factors like
your starting capital, the time period, the interest rate, and any additional deposits. So check if it's right for you. But right now, SoFi is also
offering a special signup bonus. If you set up a new
high-yield savings account with an eligible direct
deposit of $1,000 or more, well then you can get either
$50 or $400 cash bonus. So start putting your money to work by heading over to sofi.com/ve. You can scan this QR code or click the link in the description. I wanna thank SoFi for sponsoring
this part of the video. And now back to what was
happening with Liebig and Wöhler. (soft music) - They were both right?
- Yeah. - Like, they both had a compound that was made of exactly
one carbon, one nitrogen, one oxygen, and one silver atom. And one could be boring as hell (laughs) and the other one can,
well, blow up your face. (compound snaps)
- Oh! (compound bangs) - Whoa! (laughs) - This was surprising because at the time a compound was thought
to be just the atoms that made it up and nothing more. But now this whole
conception had to change. Von Liebig and Wöhler had discovered that the way those atoms
are arranged also matters. At the time, they had no way
to work out that ordering, but today we can. (inquisitive music) When you shine light on a molecule, its electric field tugs on
the electrons and nuclei. They get pulled back and forth as the field changes direction. This can stretch, squeeze, and bend the bonds in the molecule as the atoms oscillate back and forth. But each bond responds
differently to the light depending on how strong it is and the mass of the atoms it connects. It's like each bond is
a boat on the ocean. If the waves are small and rapid, they won't rock it very much. And if the waves are very slow, like the tides coming in and out, that also won't rock the boat very much. The boat just gets lifted up and down. It's only when the waves
are just the right size that the boat gets tossed around. And because of this, each
bond will react strongest to a specific frequency of
light, which we can measure. By hitting the molecule with a range of infrared frequencies, we get a spectrum like this with peaks that tell us
when bonds are reacting. This acts like a
fingerprint for the molecule and tells us which bonds are there. Wöhler's compound has a broad peak, which corresponds to bending an N double-bonded to C
double-bonded to O group. Liebig's compound, on the other hand, has a spectrum that looks like this, with these two prominent peaks, one at high frequency
and one at low frequency. These correspond to
stretching a double bond between a carbon and a nitrogen and a single bond between
a nitrogen and an oxygen. We now know that Wöhler's
compound was silver cyanate, and it looks like this. The carbon, nitrogen, and oxygen are joined with those
two strong double bonds, which is why it's so stable. In contrast, Liebig's
compound, silver fulminate, looks like this. The silver is bonded
to the carbon instead, so the other elements
are arranged this way. The bond between the carbon
and nitrogen is a triple bond, but the oxygen and nitrogen
are very weakly connected. And this single bond
is very easy to break, and once it does, the atoms can rearrange
into much more stable gases, which is why it's so explosive. They had discovered isomers. That it's not just the atoms in a molecule that dictate how it behaves,
but its bonds as well. So naturally the scientists at Abbott suspected something similar
might be happening to ritonavir. They knew that the spectrum of ritonavir should look like this. So they put a sample of white
paste into a spectrometer, expecting to see something
completely different. But instead they saw this, the same peaks. The paste had all the
same bonds as ritonavir, so it must be ritonavir. But they also noticed it
wasn't exactly the same. There were these small
deviations between the two. The arrangement of the atoms was the same, but something about the
bonds had changed slightly. - Well, it turns out there's another way to change the properties,
and I can show you how with probably the most
delicious demo I'll ever do, because this, of course,
is a piece of chocolate. It's nice, it's shiny, it's durable, and it has that nice
snap when you crack it. But you'll notice that if you've ever let
your chocolate melt, then it never returns
to being quite the same. Suddenly it melts in your
hand when you pick it up, you know, it's dull, it's bendy, and it doesn't quite taste the same. You're not imagining this. There really is a subtle difference, and I can explain what's happening with a little help from
my friend Chris over here. - Hey.
- Hello. So Chris runs his own YouTube
channel, Chris Young Cooks, and this is way overkill for
what we need here probably, because he was the head development chef at a three-Michelin star restaurant. - Yes. (subdued music) - We've got some nice
shiny chocolate here. But look what happens
when we turn up the heat. (heat gun whirs) Oh yeah, that goes quite quick. Oh, that is surprisingly satisfying. - We obviously melted some of
the chocolate, no surprise. But this is what happens, right? You leave it somewhere warm, the chocolate gets above body temperature, it starts to melt, and
then as it cools back down, it's gonna harden again. - So you've got the chocolate. - [Chris] That looks like
heat-damaged chocolate, right? - [Casper] I know. - Like, you've seen this,
you've opened a chocolate bar, maybe it was left in your car
sitting in a sunny window. Touch the edge, like, you can feel, feel how that's just soft-
- Yeah. - and kind of sticky. - Immediately. - Compare it to a nicely
tempered piece of chocolate. Like, you can pick that
up with your bare hands, it will eventually melt in your
hand, but much more slowly. - Now if this ever
accidentally happens to you, we'll show you how to get it back to the nice and shiny form. But what's interesting here is that we didn't change
any of the ingredients and yet the properties changed completely. Chocolate is made of
three main ingredients. There are other minor ones as well, but three main ones to focus on. It's got cocoa solids, that's
what gives it its color, there are sugar, of course, for sweetness, and then there is cocoa butter. That's what gives it its texture. (gentle music) And this cocoa butter is the culprit. It's a fat made from
three long carbon chains bonded together in the middle
to make this sort of Y shape. And that Y shape can form
together to form solids. But there are multiple ways
they can stack together. There are many forms the crystal can take, each with different properties. And so we call these polymorphs. Chocolate actually has six polymorphs. The dull chocolate is mostly Form IV, and that has a melting point
of around 27 degrees Celsius. While the shiny chocolate,
which is the one we want, is mostly Form V, and that
has a higher melting point of around 34 degrees Celsius. - So the challenge and the
art of chocolate making is managing these polymorphs to get the right form of crystal by managing both temperature
and, importantly, time. The nice thing about chocolate
is you can start over. You just need to heat it
back up to 45 to 50 Celsius to wipe the memory-
- Okay. - of the wrong crystals. That's hot enough to melt
out all of the crystals, but not too hot to start changing the flavor of the chocolate, evaporating a lot of
the volatile aromatics. - [Casper] After around 10 minutes at roughly 50 degrees Celsius, all the crystals should have fully melted. - So at this point, we're
trying to cool it back down to the temperature where
crystals start to form again. And that's gonna start
at about 34 Celsius. You'll start getting Form
V crystals forming at 34, as we cool even lower, we start to get Form IV and Form III. Those can all form at these temperatures. And that's okay. We want all
of these crystals initially. We want-
- Oh, really? - Yeah, we want to have sort of a shotgun of nucleation going on because we wanna make sure
we get lots of everything. - That's surprising. - It does seem surprising. - Because we just want Form V, right? - We do just want Form V. The trick is, if we just
come down to the temperature where Form V forms, so if we just went to like
32 degrees, 33 degrees, and just waited there, you'd
be waiting a very long time and you'd get a very random process of when does that crystal form, and maybe only a few crystals would form. And so they would get very large. - Ah.
- By bringing the temperature all the way down to 27, we get lots of nucleation really fast. The downside, of course, is we get the crystals
we don't want as well, but we get lots of Form V, and we get lots of small Form V. - Yeah. - So once we have that starting to form, we can select for the ones we want just by raising the temperature back up. And melting the Form III and Form IV, leaving us with only
Form V, but, importantly, lots of Form V.
- Right. After holding the chocolate at around 32 degrees
Celsius for 5 to 10 minutes, we can pour it into the mold. - Okay, I think we're
gonna be okay here, so. - Oh. I don't know what I was expecting, but I was not expecting
it to go like this. It really comes out as a sort of sheet. - One of the things here is I do have some trapped air bubbles. - Yep. - Oh, yeah. - It's like a liquefaction.
- Yeah, yeah. - [Chris] So at this point, seems like we're done, right?
- Yeah. - But actually now we need to lock in that crystal pattern that
we've created, right? - Yep.
- Like, as it cools down, there's liquid oil in there and we're gonna drop back
down through the temperature where Form IV and Form III can form. - Yep.
- So what we need to do is we need to come down through that temperature
relatively quickly so that we get mostly Form V growing and lock them in by getting
rid of most of the liquid oil. So we really need to get
this down to about 12 C. - [Casper] So we put it in the fridge and waited for around 20 to 30 minutes. - Get the door closed.
- Great. If we did this correctly,
it should be mostly Form V, which means all the molecules should have stacked tightly together, resulting in a shiny and snappy bar. (tray cracking)
Ah! Ooh! That was satisfying. - They're just barely hanging on. - Wow! - And you can see they're nice. - Perfect.
- Shiny. - This is all Form V? - This is all Form V, and
we've got a nice shiny surface. Got a couple spots where maybe the molds could have been polished
a little bit more, but give it a snap, just see how that is. (chocolate snaps)
- Ooh. It's a very good snap. - [Chris] Yeah, that's a nice. - It's very sturdy. - That's a good chocolate bar. - Delicious.
- That is how you temper a chocolate bar. - Amazing.
(curious music) - But the stacking of the
molecules in the crystals also changes something else. Since each molecule is
surrounded by other molecules, it changes how the bonds inside can move. This is what the scientists at Abbott had seen in the spectrum. The needles they had
seen under the microscope were a new polymorph of ritonavir, and a more stable one at that. Form I crystals looked like this instead. Now at first this might
seem like good news. It was still ritonavir, even
if it looked a bit different. It's just like how dull chocolate, even if it's not quite as
nice, is still chocolate. But the problem was this new
polymorph was far too stable. - Ritonavir Form II is substantially more stable than Form I. And the way we know it's more stable is because it's less soluble. But if that crystal structure happens to be much more stable, then it won't dissolve properly. And then it's a bit like you
haven't taken the drug at all. - But with chocolate, we can
change which polymorph we have. We just had to heat it up to
switch it from shiny to dull, and then by cooling it down
again in a specific way, we could get back to shiny. So you might expect that Abbott could just do something
similar with ritonavir. And they tried, but the problem was that no amount of heating or cooling could turn Form II back into Form I. They were stuck. We can see what's happening
by taking a look at this here. See, each polymorph has
different energy levels. And in the case of chocolate
that looks something like this, where Form IV has a higher energy level and Form V a lower one, and they're separated with
this sort of hill in between. Now, after heating up the chocolate bar, we were mostly left with Form IV. So let's drop this little ball in there, and then you'll see it
will slowly settle down into that valley. But not to the more stable Form V. And that's because there's
this little hill in between. But now imagine adding some heat to this. It's like giving the ball
a little bit of a kick. And you can see that the ball will suddenly start to move around. And if I give it enough of a kick, whoop, it will roll down into Form V. And now it is stuck there. Now you could keep adding more heat and you could get it back
over the hill back to Form IV, but then you would just end
up with a mess of both forms, because whenever you start
cooling it down again, you know, the ball could
just randomly settle in one of the two valleys. So that's what happened when we melted the
chocolate uncontrollably. We just got a mixture of these two forms. But with ritonavir, the
situation is a little different. The hill between the two
forms is now much taller, but the Form II valley
is also much deeper. So once the ball does get down there, it's basically impossible
to get it back out of there, which is why no matter what
the scientists at Abbott tried, they couldn't get back to Form I. - But this still doesn't
explain why Form II was suddenly everywhere. Nothing had changed in their procedures. The barrier between the two
forms should still be there. So it shouldn't have been possible to make this much Form II at all. And yet, 300 years earlier, legends of such a transformation spread across northern Europe. (gothic music) - It was a bitter winter morning, and it had been like this for months. The organist was on
his way to a cathedral. The cold had been messing
with the organ pipes. It's gone out of tune again. But that wasn't what the
congregation thought. There were stories of other organs getting sick with warts or
leprosy eating away at the pipes. Some thought it was the
devil attacking the organ to punish an unfaithful flock. It was even said that
when it was very quiet, you could hear these organs screaming and groaning in pain from the lesions. Nonsense, of course, it was just the metal
contracting and expanding. (subdued music) Except these pipes
weren't just contracting, they were cracked. And others are indeed covered in what looks like these lesions, black growths all over the organ. (dark music) Now, originally when this happened, people thought that this
was the work of Satan. Of course, that's not what was going on, and we can explain what
was actually happening. So we've got some normal tin right here, which is what those organ
pipes were made out of. It kind of looks silver,
it feels pretty strong, and it's sort of the form we're used to. - Exactly. - But here we have a slightly
different form of tin. You can look at it, it's a bit more gray, it's a bit more crumbly. And at room temperature, normally the silvery tin
is sort of more stable. But if you cool tin down to something like below
13 degrees Celsius, and ideally way colder, then it can transform into
this new kind of gray tin. And we're gonna see what happens when we put it on top of the silver tin. - [Dr. Kafizas] We want to try and get it to around minus 30 degrees Celsius. - [Casper] Yep. - And what better to get
us to those temperatures is dry ice.
- Okay. - So dry ice is frozen carbon dioxide. And that is around minus
78 degrees Celsius. - [Casper] Yep. Now we've taken a thermo flask and filled it up with dry ice, and then put a platform on top
on which we'll put our tin. This should cool it down to
around minus 30 degrees Celsius. Now we left this here for around 14 hours, and what you'll see is that initially there's a very tiny speck of tin that suddenly transformed into gray tin, and then it spreads from there almost like an infectious disease, which is why this is
also known as tin pest. And because gray tin is
less dense, the tin expands. And so if you look closely, you can see it start to
tear apart the metal. Now, normally it takes a lot of energy to transform some silver
tin into gray tin, but once you get a tiny bit of gray tin, something strange happens, because now it acts as a nucleation site that other tin can attach to, and it effectively brings
that hill way down. It lowers the activation energy. And so now it becomes very easy to switch from silver tin to gray tin. And so it starts to spread,
it starts to take over. And the same thing was
happening to those organ pipes. Once you got a lesion
on one of those pipes, well then it would grow
and spread everywhere. Little flakes would come off the pipes and seed all the others,
and it would spread. And that's also exactly what
happened with ritonavir. Once a tiny bit of Form II appeared, it acted as a nucleation site, lowering that massive activation energy and causing all the Form I
to crystallize into Form II. Tiny seed crystals then broke off, could become airborne, and spread, attaching themselves to people's clothes and making it to other parts
of the production line, effectively seeding them so that when new
ritonavir was synthesized, it contained these seed crystals and turned the entire
capsules into Form II. And because everyone likely had these seed crystals on their clothes, when the Chicago team flew over to Italy, they seeded that factory too. And in this way, soon not a single place was
able to manufacture Form I. - [Derek] Ritonavir is
arguably the most dramatic case of what we now call a
disappearing polymorph. The YouTube channel Reactions
made a great video about this that involves lots of physical demos, so I highly recommend you check it out. - [Narrator] "When this happened to us, we conducted an extremely
thorough investigation to see if there was something that we did which would have caused this. While we've speculated on the cause of this
chemical transformation, we do not have conclusive
proof of what happened." - It might be that a mistake
on the production line caused some chemicals to dry out. This might have created a new crystal similar in shape to Form II ritonavir, which acted like a seed. Or it might have just been bad luck that a seed crystal formed
on its own purely by chance. - Even if you have a seed crystal, if there are some dust particles or some scratches in the recipient where actually crystals
can start to nucleate, that can induce, then,
different crystal structures. So it happens that in some
pharmaceutical companies where they produced the same
polymorph for years and years, that suddenly there is, I would say, a hair or some other particle that, kind of, gets into the process and will change the entire
crystallization of the compound, and is then very difficult to control. - And once a more stable
form has appeared, it can spread and quickly
seed the entire planet. - It might be that you will never, ever get the
initial polymorph again. - After five months of
research, Abbott's researchers held a press conference
to share their findings. (intense music) - [Narrator] "Good afternoon. My colleagues and I are here today to explain what has happened,
why it has happened, how we've responded to the problem, and what we're going to
do to correct the problem. Sometime during this summer, the semi-solid formulation of ritonavir began to change into a crystal form, a transformation that we believed was a scientific and
chemical impossibility. - [Narrator] "You are a
large multinational company. Your scientists are obviously smart. How could this happen?" - [Narrator] "A company's
size and the collective IQs of their scientists have no
relationship to this problem. This phenomenon is, I
believe, unpredictable. We are, in some sense,
the victim of bad luck. There are many mysteries of
nature that we've not solved. Hurricanes, for example, continue to occur and often
cause massive devastation. There is nothing that we can do today to prevent a hurricane
from striking any community or polymorphism from striking any drug. Science cannot provide a
solution to all our problems." (curious music) - Now, here's a good question. Is everything polymorphic? So nobody had discovered a
polymorph of aspirin, right? So it had been around, it's
one of the earliest drugs. It had been crystallized in industry for what, 130, 140 years? And so can you say, "Because nobody had discovered a polymorph of aspirin, therefore..." No. Right? The only problem is I discovered Form II of aspirin. (laughs) By accident. Right? - It turns out over half of all compounds are known to be polymorphic,
and there could be more. - The number of polymorphs is proportional to the amount of time and money you spend
researching that compound. - In fact, nowadays we know there are not two forms of
ritonavir, but at least five. So are new cases of
disappearing polymorphs something to worry about? - It's quite, quite rare. We certainly know a lot more than we did when ritonavir occurred, but I wouldn't be surprised
to see it happen again. - If there's a 1% chance
the world's gonna end, you're gonna do something about it, right? If there's a 1% chance
a plane is gonna crash, you're not gonna fly, right? So, so yeah. So we're at that situation
where it might only be in that order of 1%, but if it happens, it's gonna cost you a hell of a lot more than a few weeks of
research on polymorphs. Ritonavir was one of the red flags that caused a lot of regulatory activity and a lot of scientific
activity around polymorphs. - Nowadays, pharmaceutical companies can spend hundreds of thousands to millions of dollars
screening for polymorphs. In the end, there was no way of getting Form I ritonavir
back successfully. There were attempts, but
all were incredibly costly, and they risked being infected again. So instead, Abbott went back to an older liquid formulation of the drug and abandoned Form I entirely. - [Narrator] "Our initial
activities were directed towards eliminating Form
II from our environment. We finally accepted that we could not. Our subsequent activities were directed towards figuring out how
to live in a Form II world. Nature would appear to favor it." (curious music) - The liquid formulation was not ideal. It had worse side effects, and not all patients could
tolerate it well, but it worked. - [Narrator] "It is frightening
that this could happen to any drug that we've taken
and on which we're dependent, even though it is not that common. This time, it has happened to Abbott and to the tens of thousands of people taking the semi-solid capsule. Thankfully, we had the liquid
formulation as a safety net. Next time it may happen to another drug that may not have the safety net." (curious music continues)...
    """

    result = extract_article_data(
        content=sample_content,
        source_url="https://example.com/article",
        source_type="Article",
        model=DEFAULT_MODEL,
        chunk_size_chars=20_000,
        overlap_chars=600,
    )

    if result:
        print(f"\n📰  {result['title']}")
        print(f"    {result['source_url']}\n")
        for i, idea in enumerate(result["ideas"], 1):
            print(f"{'─'*62}")
            print(f"  [{i:02d}] {idea['title']}")
            print(f"{'─'*62}")
            print(idea["paragraph"])
            print()
        print(f"\n📚 TERMS ({len(result['terms'])})")
        for term, definition in result["terms"]:
            print(f"\n  {term}\n  {definition}")