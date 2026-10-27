# Transcript Editing Instructions (for manual use with any AI)

> **Purpose of this file:** this is a copy-pasteable instruction block for
> Stage 0 of the text-based video editor project. No automation yet — you
> paste these instructions into any AI chat (ChatGPT, Claude, etc.), together
> with a VTT transcript and a plain-language editing request, and the AI
> replies with a structured, timestamp-safe result you can inspect by hand.
> Once this manual loop feels reliable, the same rules become the system
> prompt for the automated backend (see the architecture discussed for the
> `video_text_editor` project: VTT → AI cut decisions → deterministic
> normalize/merge → FFmpeg render).

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

   Cues are separated by a blank line. This is **auto-generated YouTube
   caption data**, so be aware of its quirks:
   - Cues frequently **overlap in time** with their neighbors (e.g. one cue
     runs 00:00:03.600 → 00:00:09.480 while the next runs
     00:00:05.359 → 00:00:09.480). This is normal for auto-captions, not an
     error you need to fix.
   - Text may contain transcription mistakes, stray tags like `[музыка]`
     (music), or fragments of other languages picked up by auto-translate.
     Do not "correct" these unless the instruction explicitly asks you to.
   - The transcript you receive might be an **original**, or it might be an
     **already-edited transcript from a previous round** (see "Iteration"
     below). Treat both cases identically — just apply the new instruction
     on top of whatever transcript you are given.

2. **INSTRUCTION** — a plain-language description of what to change, e.g.
   "remove the sponsor section", "cut the intro before the subject starts
   talking", "remove this repeated explanation", "delete the stray
   `[музыка]`-only cues".

### Two ways this gets used

**If you have file read/write access to this project folder** (Claude
Code, Claude Desktop with the folder attached, etc.) — I may give you
short commands by name, "step 1" or "step 2", instead of re-explaining
each time:
- **"Step 1"** means: do exactly what "Step 1 — Generate a readable
  outline" below describes.
- **"Step 2"** (or just a plain editing instruction) means: apply the
  instruction and produce `REMOVED`/`CHANGE_LOG` per "Expected output
  format" below, writing it to a file as well as replying in chat.

**If you don't have file access** (e.g. plain ChatGPT/Gemini web chat) —
ignore the step names; just use the TRANSCRIPT + INSTRUCTION template at
the bottom of this file and reply normally in chat.

### Step 1 — Generate a readable outline

When asked to do "step 1":

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
   - **The common mistake that breaks this:** auto-caption cues routinely
     overlap their own neighbors in time (cue N might run 01:10–01:15 while
     cue N+1 runs 01:12–01:18). If you pick paragraph A's end from "the
     last cue that feels like it belongs to A" and paragraph B's start from
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
4. For each paragraph/sub-paragraph, write a heading with a short
   descriptive title and its start/end timestamps. These should still be
   real cue timestamps from the transcript (never invented or rounded),
   but per rule 3, the shared boundary between two neighbors is a single
   chosen value, not independently "whichever cue felt right" on each
   side. Follow the heading with a short prose summary (2-6 sentences) of
   what is actually said in that span, in your own words. This is a
   human-reading summary, not a cue-by-cue transcription.
5. Write the result to `workspace/outline.md`, in **exactly** this
   format — the app parses it automatically to build a navigable view
   with click-to-seek timestamps, so the heading pattern must match
   exactly:

   ```markdown
   # Transcript Outline

   ## <Title> (HH:MM:SS.mmm - HH:MM:SS.mmm)

   <prose summary>

   ### <Sub-title> (HH:MM:SS.mmm - HH:MM:SS.mmm)

   <prose summary>

   ## <Next title> (HH:MM:SS.mmm - HH:MM:SS.mmm)

   <prose summary>
   ```

   `##` for top-level paragraphs, `###` for sub-paragraphs, each followed
   by `(start - end)` with a hyphen or en dash.

6. Also show the outline in your reply, so I can see it without opening
   the file.

#### Step 1 worked example — fixing an overlap before it happens

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
with Melsik"). Auto-captions often fuse a question and the start of its
answer into one cue like this. You can't split a cue's text in half, so
pick **one of its own real edges** as the shared boundary and accept that
the whole cue goes to one side:
```
## Dylan looks Armenian (00:03:15.100 - 00:03:44.200)
## Training with Melsik and Edmond Tarverdyan (00:03:44.200 - 00:04:...)
```
Here `00:03:44.200` is reused as both A's end and B's start — a real cue
timestamp, not invented, and no overlap. The app's own merge logic (not
your job) will route the "Did you train..." cue's text to whichever
paragraph makes more sense once cuts are applied — you don't need to
agonize over getting a bundled cue's content perfectly split, you just need
to **never state two different, overlapping timestamps** as the boundary.

**Step 1 never changes the transcript, and never proposes cuts.** It only
reads and describes — if I haven't given an editing instruction, don't
imply or suggest removals in the outline.

### Your task (Step 2 — editing)

Decide which **whole cue blocks** should be removed to satisfy the
instruction, then produce the output described below. **If I haven't
asked for a change, don't make one** — no instruction means no cuts, and
nothing in the transcript gets touched or reworded regardless.

### Hard rules — do not break these

1. **Never invent, round, or recalculate a timestamp.** Every timestamp you
   output must be copied character-for-character from a cue that existed in
   the input TRANSCRIPT.
2. **Only remove whole cue blocks.** Do not split a cue or try to cut out a
   sub-string of a cue's text while keeping the rest — with overlapping
   auto-caption timestamps there is no reliable sub-cue boundary to cut at.
   If the instruction clearly targets only part of a cue, remove the
   smallest set of whole cues that covers the targeted content, and say so
   in `CHANGE_LOG`.
3. **Don't touch anything the instruction didn't ask about.** No rewording,
   no translation, no fixing typos/auto-caption errors, no reordering, no
   merging cues. Surviving cues must be byte-identical to the input
   (timestamp and text), minus the ones you removed.
4. **Preserve original order.** Never reorder cues.
5. **If you are not confident which cues match the instruction, do not
   guess.** List the ambiguity under `QUESTIONS` instead of silently
   deciding.
6. **Do not compress gaps.** After removing cues, do **not** shift the
   remaining timestamps earlier to "close the gap." Keep every surviving
   timestamp exactly as it was in the input — gap-closing happens later in
   the deterministic rendering step, not by you.
7. **If the instruction gives a target output length** (e.g. "make it about
   15 minutes"), you MUST account for cue overlap before reporting or
   relying on how much you've removed:
   - Because input cues overlap, the sum of each removed cue's own
     `(end - start)` **overcounts** how much unique video time you've
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
[музыка] В скором времени молодому

00:03:32.200 --> 00:03:35.497
дарованию было отправлено предложение,

00:03:34.159 --> 00:03:36.400
от которого нельзя было отказываться.

00:03:35.497 --> 00:03:39.040
[музыка]

00:03:36.400 --> 00:03:41.319
На турнире K1 в Швеции в главном событии
```

**Instruction:** "Remove cues that are only a `[музыка]` tag with no real
speech."

**Output:**
```
## REMOVED

00:03:35.497 --> 00:03:39.040 | "[музыка]" | Cue contains only a music tag, no speech

## CHANGE_LOG

- Cues removed: 1
- Time removed (merged, non-overlapping): 3.5s
- Resulting approx. output length: original minus 3.5s
- Notes: left the first cue's "[музыка]" prefix alone because it also contains real speech
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
<what to remove/change this round>

TRANSCRIPT:
<paste the VTT cues here>
```
