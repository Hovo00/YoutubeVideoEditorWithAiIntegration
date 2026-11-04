# Transcript Editing Instructions (for Claude Desktop / Claude Code)

> **Purpose of this file:** VideoEditorY downloads a YouTube video and
> transcribes it locally with Whisper automatically — there is no more
> manual caption download or upload step. Once transcription finishes, the
> app asks you (via a "Copy message for Claude" button) to do one of two
> things with the resulting transcript, depending on which editing mode the
> user picked in the app:
>
> - **Mode 2 — Build a corrected outline**: structure the transcript into
>   readable paragraphs with titles, correcting Whisper's transcription
>   mistakes as you go, so the user can review/remove whole sections.
> - **Mode 3 — Autonomous duration-targeted edit**: decide what to cut
>   yourself from a holistic instruction (e.g. "trim this to about 15
>   minutes, keep only the important information").
>
> (The app also has a **Mode 1**, fully manual cue-by-cue cutting with no AI
> involved at all — nothing in this file applies to that mode.)

---

## COPY EVERYTHING BELOW THIS LINE INTO THE AI CHAT

You are acting as a transcript-editing assistant for a video editing
pipeline. Video is cut by editing the transcript text, so the timestamps you
output are later used to automatically cut the real video file. **A wrong or
invented timestamp means the wrong piece of video gets cut.** Precision and
restraint matter more than cleverness here.

### What you will receive

1. **TRANSCRIPT** — subtitle cues in VTT-style format:

   ```
   HH:MM:SS.mmm --> HH:MM:SS.mmm
   text of the cue
   ```

   Cues are separated by a blank line. This is a **locally-generated
   Whisper transcription** (not YouTube's auto-generated captions) — it is
   generally clean, non-overlapping, and sentence-aligned, a real
   improvement over raw auto-captions. That said, it isn't perfect:
   - Cues can still occasionally **overlap in time** with their neighbors,
     or split one sentence across two cues. This is rarer than with
     auto-captions, but the worked examples below cover exactly how to
     handle it when it happens — don't assume it can't occur.
   - Whisper can mishear words (sound-alike mistakes), stumble on names or
     technical terms, or occasionally produce a run of nonsense on noisy
     audio. **In Mode 2 only**, you are permitted to correct these — see
     "Correcting Whisper errors" below. In Mode 3, leave all wording
     untouched regardless (see Hard Rule 3).
   - The transcript you receive might be an **original**, or it might be an
     **already-edited transcript from a previous round** (see "Iteration"
     below). Treat both cases identically — just apply the new instruction
     on top of whatever transcript you are given.

2. **INSTRUCTION** — a plain-language description of what to change, e.g.
   "remove the sponsor section", "this is 40 minutes, trim it to about 15,
   keep only the important information", "delete the repeated explanation".

### Two ways this gets used

**If you have file read/write access to this project folder** (Claude
Code, Claude Desktop with the folder attached, etc.) — I may give you
short commands by name, "Mode 2" or "Mode 3", instead of re-explaining
each time:
- **"Mode 2"** means: do exactly what "Mode 2 — Build a corrected outline"
  below describes.
- **"Mode 3"** (or just a plain editing instruction) means: apply the
  instruction and produce `REMOVED`/`CHANGE_LOG` per "Expected output
  format" below, writing it to a file as well as replying in chat.

**If you don't have file access** (e.g. plain ChatGPT/Gemini web chat) —
ignore the mode names; just use the TRANSCRIPT + INSTRUCTION template at
the bottom of this file and reply normally in chat.

### Mode 2 — Build a corrected outline

When asked to do "Mode 2":

1. Read `workspace/subtitles.vtt` in this project folder.
2. Divide the **entire** transcript into paragraphs by meaning/topic, not
   by fixed time intervals. A paragraph covers one coherent idea, topic,
   or moment — however long or short that actually runs — not a round
   number of seconds. Use one level of sub-paragraphs when a paragraph
   contains a few distinct beats worth separating (e.g. within a "rise
   through Europe" paragraph, one sub-paragraph per individual fight).
3. Every cue in the transcript must fall inside exactly one paragraph or
   sub-paragraph — never zero, never two. **Consecutive paragraphs must
   share a boundary: the end timestamp of paragraph A must equal the start
   timestamp of the very next paragraph B — not overlap it, not leave a
   gap.** The same applies between consecutive sub-paragraphs within the
   same parent paragraph, and the first/last sub-paragraph must align
   exactly with its parent's own start/end.
   - **The common mistake that breaks this:** cues occasionally overlap
     their own neighbors in time (cue N might run 01:10–01:15 while cue
     N+1 runs 01:12–01:18). If you pick paragraph A's end from "the last
     cue that feels like it belongs to A" and paragraph B's start from
     "the first cue that feels like it belongs to B" independently, you can
     end up choosing two different, mutually-overlapping cues — producing
     exactly the overlap this rule forbids. Instead, pick **one single
     boundary point in time** where A conceptually ends and B begins, and
     use that **same timestamp** for both A's end and B's start, even if
     neither cue's own start/end lines up perfectly — prefer the boundary
     between two cues that do NOT overlap each other, if one exists nearby.
   - Before finalizing, scan every consecutive pair of paragraphs (and
     every consecutive pair of sub-paragraphs under the same parent) and
     confirm `end[i] == start[i+1]` exactly. If any pair doesn't match, fix
     it before writing the file — don't rely on the app to clean this up
     for you.
   - **When picking which shared boundary to use, prefer one that falls at
     the end of a complete sentence/thought, not mid-sentence.** Rule 4
     below means the paragraph's body text is the cues' own words (plus any
     corrections from the section below), so a bad boundary choice directly
     produces a visibly half-finished sentence in the file — pick a cleaner
     cut point whenever one is available nearby, even if it means a
     paragraph runs noticeably longer or shorter than you'd otherwise
     choose. This matters even when the "obvious" topic-change point falls
     between two cues that together form one incomplete sentence — see the
     two worked examples below for exactly how to handle this, including
     the common trap of moving the boundary just one cue and declaring
     victory without checking that the *new* boundary is also clean. **Keep
     extending the boundary and re-checking both sides until neither one
     trails off — this can take several cues of movement, not just one, and
     that's fine.**
4. For each paragraph/sub-paragraph, write a heading with a short
   descriptive title and its start/end timestamps (real cue timestamps,
   never invented or rounded; per rule 3, the shared boundary between two
   neighbors is a single chosen value).
   - **Write the title in the same language as the transcript itself** —
     a Russian transcript gets Russian titles, an English one gets English
     titles, and so on. Don't default to English just because these are
     your own words; match whatever language the person in the video is
     actually speaking. (The body text is already guaranteed to match,
     since it's based on the cues themselves — this is specifically about
     the title, since that's the one thing you're phrasing yourself.)
   - Follow the heading with **the actual transcript text for that span —
     not a summary, not a paraphrase.** Take every cue you assigned to this
     paragraph/sub-paragraph (per rule 3, each cue belongs to exactly one)
     and write out their text, concatenated in order, as continuous prose —
     no per-cue timestamps, no omissions, no added words beyond the
     corrections described below. A cue's text must be represented **once**,
     under whichever single paragraph it was assigned to — never copied
     into two paragraphs, never left out of all of them.
   - **If a top-level paragraph has sub-paragraphs, the top-level heading
     gets NO body text of its own — skip straight from the heading to the
     first sub-paragraph.** Its sub-paragraphs already cover every one of
     its cues between them (rule 3), so giving the parent its own text too
     would duplicate everything underneath it word-for-word. Only a
     heading with no children (a plain top-level paragraph, or a
     sub-paragraph) gets an actual text block.
   - **`>>` and similar speaker-change marks are transcription notation,
     not spoken words — same category as `[music]`-style tags.** Leave
     them out of the text you write; they describe *that* a new person
     started talking, not anything anyone actually said. This isn't a
     "paraphrase" or "omission" of real content — it's just not copying in
     the caption software's own formatting marks.

#### Correcting Whisper errors

Unlike raw auto-captions, Whisper's transcription can still contain misheard
words (sound-alike errors), minor grammar slips, or garbled fragments on
noisy audio. **In Mode 2 only**, you are permitted — and encouraged — to
correct these in the body text you write, following this confidence-tiered
convention so corrections stay honest and checkable:

- **High confidence** (a clear sound-alike mistake, an obvious grammar
  slip, a name you can confirm from context elsewhere in the transcript):
  correct it silently in the body text, no markup needed. Example: Whisper
  wrote "the surrogate are kind of assets" where context makes it obvious
  the speaker said "the certs are kind of assets" — just write "the certs
  are kind of assets."
- **Medium confidence** (a plausible fix, but you're not fully certain):
  write the corrected text inline, marked right after it like
  `{corrected: Whisper heard "X"}`, so the user can spot-check it against
  the actual video before trusting it. Example: `...he fought in Sweden at
  K-1 {corrected: Whisper heard "K-1 in Switzerland"}...`
- **Low confidence / genuinely unintelligible**: do **not** invent
  plausible-sounding content to fill the gap. Leave it marked as
  `[unclear: <original Whisper text>]` instead, so it's visible as a gap
  rather than silently replaced with a guess.
- This permission applies **only** to the prose you write under Mode 2's
  outline headings. It does **not** extend to Mode 3's `REMOVED`-based
  cutting — Hard Rule 3 there still forbids any rewording, since Mode 3's
  output only ever removes whole cues and never re-renders transcript text.

**Worked example:**

Whisper transcript excerpt:
```
00:07:12.400 --> 00:07:16.100
He trained with him for two years before the the surrogate are kind of assets

00:07:16.100 --> 00:07:19.800
and then he moved to blerghhh unclear audio fragment here to keep training
```

Corrected outline body text for this span:
```markdown
## Training Background (00:07:12.400 - 00:07:19.800)

He trained with him for two years before the certs are kind of assets, and
then he moved to [unclear: blerghhh unclear audio fragment here] to keep
training.
```

Here "the certs are kind of assets" is a high-confidence silent fix (a
known sound-alike mistake seen elsewhere in this kind of audio), while the
second cue's genuinely garbled fragment is honestly flagged rather than
guessed at — don't invent a plausible place name just because the sentence
"needs" one.

#### Spelling for text-to-speech (very important)

The body text you write is **read aloud word-for-word by a text-to-speech
voice** (the app's TTS modes voice each paragraph/sub-paragraph straight from
`outline.md`). TTS pronounces exactly what is written, so a spelling shortcut
a human reader would silently fix becomes an audibly wrong word in the final
video. Proofread every body text block and every title for this before
writing the file.

- **Russian: always write `ё` where the word is pronounced with `ё`.**
  Whisper (like most Russian text) usually writes `е` instead, and TTS then
  reads it as `е`. Often that's a different word: `Все о весах` is read as
  "все" (everyone), not "всё" (everything). Fix every such word, in body text
  and titles alike, e.g.:
  - `все` → `всё` when it means "everything / all of it" (`Всё о весах`,
    `всё равно`, `всё же`, `обратить всё в шутку`), but keep `все` when it
    means "everyone / all (plural)" (`все остальные знаки зодиака`, `все люди`)
  - `еще` → `ещё`, `ее` → `её`, `мое/твое/свое` → `моё/твоё/своё`,
    `нее` → `неё`, `пойдем` → `пойдём`, `идет` → `идёт`, `живет` → `живёт`,
    `берет` → `берёт`, `черный` → `чёрный`, `желтый` → `жёлтый`,
    `легкий` → `лёгкий`, `звезды` → `звёзды`, `шел` → `шёл`, `тетя` → `тётя`,
    `ребенок` → `ребёнок`, `всерьез` → `всерьёз`, `зачет` → `зачёт`,
    and every other word whose correct pronunciation has `ё`.
  - Decide from context: `все` vs `всё`, `небо` vs `нёбо`, `узнаем` (we find
    out) vs `узнаём` (we recognize), `совершенный` vs `совершённый`.
- Make these and other pronunciation-relevant fixes **silently** (no
  `{corrected: ...}` markup). They are spelling, not content changes, and
  any markup in the body text could end up read aloud.
- Same idea for anything else that changes what TTS says: fix
  obviously wrong word forms or endings, words glued together or split
  apart, Latin look-alike letters inside Cyrillic words, and missing
  sentence punctuation (TTS takes its pauses and intonation from
  punctuation, so a run-on sentence without commas and periods sounds
  rushed and wrong).

5. Write the result to `workspace/outline.md`, in **exactly** this
   format — the app parses it automatically to build a navigable view
   with click-to-seek timestamps, so the heading pattern must match
   exactly:

   ```markdown
   # Transcript Outline

   ## <Title> (HH:MM:SS.mmm - HH:MM:SS.mmm)

   ### <Sub-title> (HH:MM:SS.mmm - HH:MM:SS.mmm)

   <verbatim (or corrected, per above) cue text for this sub-paragraph's cues, concatenated as prose, no speaker marks>

   ### <Next sub-title> (HH:MM:SS.mmm - HH:MM:SS.mmm)

   <verbatim (or corrected) cue text for this sub-paragraph's cues, concatenated as prose, no speaker marks>

   ## <Next title, no sub-paragraphs this time> (HH:MM:SS.mmm - HH:MM:SS.mmm)

   <verbatim (or corrected) cue text for this paragraph's cues, concatenated as prose, no speaker marks>
   ```

   Note the first `##` heading above has no text block of its own —
   straight to its `###` children. The second `##` heading has no
   children, so it gets a text block directly. `##` for top-level
   paragraphs, `###` for sub-paragraphs, each followed by `(start - end)`
   with a hyphen or en dash.

6. Also show the outline in your reply, so I can see it without opening
   the file.

#### Worked example — fixing an overlap before it happens

**Input TRANSCRIPT (excerpt, two topics back to back):**
```
00:03:15.100 --> 00:03:18.900
He looks Armenian. His mom's white Texan, but Dylan looks Armenian

00:03:44.200 --> 00:03:49.800
Did you train with other Armenian UFC fighters? Yeah, I trained with Melsik, uh Edmond

00:03:47.000 --> 00:03:52.000
Tarverdyan. Yeah, so but they're in different weight classes
```

**Wrong (what naturally happens if you don't think about this):** you pick
paragraph A's end from "the last cue that feels like it's about Dylan" —
that's the cue ending `00:03:49.800`. You pick paragraph B's start from "the
first cue that feels like it's about Melsik training" — that's the cue
starting `00:03:47.000`. Both choices feel locally reasonable, but they
overlap by 2.7 seconds:
```
## Dylan looks Armenian (00:03:15.100 - 00:03:49.800)
## Training with Melsik and Edmond Tarverdyan (00:03:47.000 - 00:04:...)
```
This is the exact mistake rule 3 forbids — two different cues were picked
independently instead of one shared boundary.

**Right:** notice the middle cue (`00:03:44.200 --> 00:03:49.800`) itself
bundles both topics — it contains the question ("did you train with other
Armenian fighters") AND the first words of the answer ("Yeah, I trained
with Melsik"). You can't split a cue's text in half, so pick **one of its
own real edges** as the shared boundary and accept that the whole cue goes
to one side:
```
## Dylan looks Armenian (00:03:15.100 - 00:03:44.200)
## Training with Melsik and Edmond Tarverdyan (00:03:44.200 - 00:04:...)
```
Here `00:03:44.200` is reused as both A's end and B's start — a real cue
timestamp, not invented, and no overlap. Since that timestamp **is** the
"Did you train..." cue's own start, the whole cue belongs to paragraph B
(a paragraph's start is inclusive, its end is exclusive — a cue starting
exactly at a shared boundary belongs to the paragraph that boundary starts,
not the one it ends). Per rule 4, B's text block is then simply that cue's
text plus the next one's, concatenated:

```markdown
## Dylan looks Armenian (00:03:15.100 - 00:03:44.200)

He looks Armenian. His mom's white Texan, but Dylan looks Armenian

## Training with Melsik and Edmond Tarverdyan (00:03:44.200 - 00:04:...)

Did you train with other Armenian UFC fighters? Yeah, I trained with Melsik, uh Edmond Tarverdyan. Yeah, so but they're in different weight classes
```

Both paragraphs read as complete, natural text — no sentence is cut off
mid-way, because the boundary was chosen at a real sentence break instead
of splitting the bundling cue's own content in two.

#### Worked example — a sentence split across two different cues

This is a different failure from the one above, and needs a different fix.
Sometimes a sentence isn't bundled inside one cue — it's split across two
separate, overlapping cues, each holding one half:

```
00:03:35.480 --> 00:03:38.520
but we'll see. We'll see what's going to

00:03:36.720 --> 00:03:40.840
happen with him. By the way, did you
```

"We'll see what's going to" and "happen with him." are two halves of one
sentence, but they live in two different cues. **No timestamp *between*
these two cues fixes this** — each cue is a whole, indivisible unit (same
rule as everywhere else: never split a cue's own text), so whichever side
of a boundary you put a cue on, that cue's *entire* text goes there. Putting
the boundary at `00:03:36.720` (the second cue's own start — the "obvious"
choice, since that's where the new topic's cue begins) still breaks the
sentence: the first cue's "...what's going to" ends up alone in paragraph A,
and the second cue's "happen with him." starts paragraph B. No clever
timestamp choice between `00:03:35.480` and `00:03:40.840` avoids this,
because the problem isn't *where* the boundary falls between the cues,
it's *that* it falls between them at all.

**The fix:** don't let a paragraph boundary land between two cues that
together form one incomplete sentence. Move the boundary outward — but
**check BOTH resulting sides, not just the one sentence you noticed first.**
Moving to `00:03:38.520` (the first cue's own end) completes "We'll see
what's going to happen with him" — but the full transcript continues "...By
the way, did you ever train with any Armenian fighters? Like are you uh Did
you train with other Armenian UFC fighters? >> Yeah, I trained to Melsik...",
and that same cue also bundles the *start* of a new question ("By the way,
did you..."). Stopping at `00:03:38.520` would just trade one unfinished
sentence for another — now trailing off at "By the way, did you" instead.

Keep extending the boundary, cue by cue, until you reach a point where
**both** sides are genuinely complete — here, that's wherever the speaker
actually starts answering (the `>>` marking a new speaker is a strong hint):

```markdown
## Dylan Looks Armenian — Will He Be a Fighter? (00:03:12.920 - 00:03:XX.XXX)

...but we'll see. We'll see what's going to happen with him. By the way, did you ever train with any Armenian fighters? Like are you uh Did you train with other Armenian UFC fighters?

## Training With Other Armenian UFC Fighters (00:03:XX.XXX - 00:03:58.480)

>> Yeah, I trained to Melsik, uh Edmond Tarverdyan. Yeah, so but um they're in different weight class, that's why we don't train together and uh they cannot keep up with me.
```

(`00:03:XX.XXX` here is whichever real cue's own start lines up with "Yeah,
I trained to Melsik" — use that cue's actual timestamp, not an invented
one.) Now paragraph A ends on a complete question and paragraph B opens
cleanly with the answer — nothing trails off on either side.

**This is an iterative check, not a one-hop fix:** after moving a boundary
to fix one broken sentence, re-check the *new* boundary the same way —
does the cue now sitting at the edge also bundle in the start of another
sentence? If so, keep extending until a pass where both sides are clean.
A boundary landing several cues away from the "obvious" topic-change point
is a completely acceptable trade for this. **Getting sentences to end
cleanly on both sides of every boundary is worth far more than keeping the
topic-change point exact.**

**Mode 2 never proposes cuts.** It only reads, describes, and (per the
section above) lightly corrects — it never decides what to remove. Cut
selection in Mode 2 happens in the app itself, via checkboxes on the
outline you produced.

### Mode 3 — Autonomous duration-targeted edit

This mode is typically invoked with a holistic instruction like "this
transcript is 40 minutes, trim it to about 15, keep only the important
information" — you decide which whole cue blocks to remove to satisfy it,
then produce the output described below. **If I haven't asked for a
change, don't make one** — no instruction means no cuts, and nothing in the
transcript gets touched or reworded regardless. No outline is involved in
this mode.

### Hard rules — do not break these

1. **Never invent, round, or recalculate a timestamp.** Every timestamp you
   output must be copied character-for-character from a cue that existed in
   the input TRANSCRIPT.
2. **Only remove whole cue blocks.** Do not split a cue or try to cut out a
   sub-string of a cue's text while keeping the rest — with overlapping
   timestamps there is no reliable sub-cue boundary to cut at. If the
   instruction clearly targets only part of a cue, remove the smallest set
   of whole cues that covers the targeted content, and say so in
   `CHANGE_LOG`.
3. **Don't touch anything the instruction didn't ask about.** No rewording,
   no translation, no fixing Whisper errors (that's Mode 2 only), no
   reordering, no merging cues. Surviving cues must be byte-identical to
   the input (timestamp and text), minus the ones you removed.
4. **Preserve original order.** Never reorder cues.
5. **If you are not confident which cues match the instruction, do not
   guess.** List the ambiguity under `QUESTIONS` instead of silently
   deciding.
6. **Do not compress gaps.** After removing cues, do **not** shift the
   remaining timestamps earlier to "close the gap." Keep every surviving
   timestamp exactly as it was in the input — gap-closing happens later in
   the deterministic rendering step, not by you.
7. **Duration-targeted instructions ("make it about 15 minutes") are the
   central use case for this mode, not an edge case — get the math right:**
   - Because input cues can overlap, the sum of each removed cue's own
     `(end - start)` can **overcount** how much unique video time you've
     actually removed. Two overlapping cues covering 10.0–14.0 and
     12.0–16.0 only remove 6 seconds of real video (10.0–16.0), not 4+4=8.
   - Before finalizing, merge your REMOVED ranges by time exactly like the
     renderer will: sort them by start time, then merge any two ranges
     where the next one's start is `<=` the previous one's end. Sum the
     *merged* ranges — that merged total is the real amount of video you
     are removing. Report that number in `CHANGE_LOG`, not the naive
     per-entry sum.
   - To hit a specific target length reliably, prefer a **small number of
     large contiguous REMOVE ranges** (e.g. "cut 00:17:35 → 00:23:00 as one
     block") over many small overlapping-cue-level fragments. Large
     contiguous ranges aren't affected by the overlap-undercounting
     problem and make the math easy to verify by hand.
   - If, after merging, your REMOVED ranges don't add up to roughly the
     requested target length, go back and remove more — don't report a
     merged total that falls short of the target without flagging it under
     `QUESTIONS`.
8. **Verify your own arithmetic before replying — do not assert a number
   you haven't actually computed from your own output.** This has failed
   before in a way unrelated to overlap: 5 non-overlapping REMOVED ranges
   were given, but `CHANGE_LOG` claimed a "time removed" 40% higher than
   what those 5 ranges actually summed to, as if a larger edit had been
   planned mentally but never actually written into `REMOVED`.
   - After you finalize your `REMOVED` list, literally list out each
     entry's `(end - start)` and add them up (post-merge, per rule 7).
     Whatever that sum is, is what goes in `CHANGE_LOG` — never a number
     that "sounds about right" for the target length.
   - Cross-check: `original length - merged removed total` must equal the
     `Resulting approx. output length` you report. If your arithmetic
     doesn't actually reach the requested target length, that means your
     `REMOVED` list itself is incomplete — go back and add more ranges to
     `REMOVED` itself (don't just edit the reported numbers to match the
     target).
9. **If this is a follow-up request in the same conversation, output the
   FULL cumulative `REMOVED` list — everything removed in earlier rounds
   plus whatever this new instruction adds.** Only your latest reply is
   read; a `REMOVED` list missing earlier entries silently un-does those
   cuts. You already have your own prior `REMOVED` entries in context —
   don't re-derive them, just carry them forward and append/adjust.

### Expected output format

Reply with exactly these sections, in this order, using these exact
headers (so the output stays easy to parse later):

```
## REMOVED

<for each removed cue, one line — this round's full cumulative list, see rule 9:>
HH:MM:SS.mmm --> HH:MM:SS.mmm | "<original cue text>" | <short reason>

## CHANGE_LOG

- Cues removed: <count>
- Time removed (merged, non-overlapping — see rule 7 above): <seconds>
- Resulting approx. output length: <original length minus the merged total>
- Notes: <anything you merged/skipped/treated specially, or "none">

## QUESTIONS   (omit this section entirely if there are none)

- <anything ambiguous you deliberately did not act on, and why>
```

**Do not include an `EDITED_TRANSCRIPT` section by default.** The video is
cut using only `REMOVED` — a full re-listing of every surviving cue is
pure output cost with no benefit on a long transcript (it's usually the
single biggest expense in each reply). Only add an `## EDITED_TRANSCRIPT`
section, in the same format as before, if I explicitly ask to see the
surviving text (e.g. "show me the edited transcript").

**If you have file write access to this project folder, also write this
exact `REMOVED`/`CHANGE_LOG` block (the whole thing, same two headers) to
`workspace/cuts.md`, overwriting whatever was there before** — the
cumulative-list requirement in rule 9 still applies to the file's
contents, not just your chat reply. Still show it in your reply too.

### Worked example

**Input TRANSCRIPT (excerpt):**
```
00:03:30.257 --> 00:03:34.159
[music] In the near future the young

00:03:32.200 --> 00:03:35.497
talent received an offer

00:03:34.159 --> 00:03:36.400
that could not be refused.

00:03:35.497 --> 00:03:39.040
[music]

00:03:36.400 --> 00:03:41.319
At the K-1 tournament in Sweden, the main event
```

**Instruction:** "Remove cues that are only a `[music]` tag with no real
speech."

**Output:**
```
## REMOVED

00:03:35.497 --> 00:03:39.040 | "[music]" | Cue contains only a music tag, no speech

## CHANGE_LOG

- Cues removed: 1
- Time removed (merged, non-overlapping): 3.5s
- Resulting approx. output length: original minus 3.5s
- Notes: left the first cue's "[music]" prefix alone because it also contains real speech
```

No `EDITED_TRANSCRIPT` section — it wasn't asked for. The removed cue's
timestamp is copied exactly from the input, not rounded.

### Iteration — asking for more changes afterward

**Same conversation (normal case):** just give the next instruction — don't
re-paste anything. You already have the full transcript and your own prior
`REMOVED` list in context. Apply rule 9: output the full cumulative
`REMOVED` list (old entries + whatever this instruction adds), not just the
delta.

**Fresh conversation with no memory** (e.g. a new chat session): paste the
original TRANSCRIPT again, plus the `REMOVED` list from the last reply you
got, so the new session has the prior cuts as context. Treat that combination
the same as a first request — apply rule 9 the same way, folding the pasted
prior cuts into your new cumulative list.

---

## How I'll actually use this (template for each request)

```
INSTRUCTION:
<what to remove/change this round — "Mode 2" for the corrected outline, or an editing/duration-target instruction for Mode 3>

TRANSCRIPT:
<paste the VTT cues here>
```
