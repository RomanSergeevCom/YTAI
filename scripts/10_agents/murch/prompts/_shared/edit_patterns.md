---
artifact: edit-patterns
inputs: [review_analysis, chapters]
outputs: [tactical edit suggestions per chapter]
---

# Edit patterns — what to do when something feels off

Library of common YouTube edit problems and Murch's preferred fix. Reference
from Review (Workflow 4) and Pre-Edit (Workflow 3).

## Problem: Long talking-head, no visual variation

**Symptom:** ≥10 sec of speaker in identical frame, no gesture, no cut, no B-roll.

**Why it fails:** Blink reflex resets attention every 2-7 sec. By 10+ sec
of static shot, ~25-40% of viewers have looked away (phone notif, second tab).

**Fix priority:**
1. **B-roll insert with audio bridge.** 2-3 sec of related visual under
   continuous dialogue. Cheapest, safest.
2. **Zoom-in cut on emotional beat.** 1.2-1.5× zoom on the same shot at the
   moment of strongest word. Adds visual change without B-roll asset.
3. **Hard cut to second angle** (if multi-cam). Best, but requires footage.
4. **Last resort: trim the segment.** If no visual asset exists and there's
   no second angle — speaker said it less efficiently than needed.

## Problem: Cut visible / "feels like edit"

**Symptom:** Viewer notices the cut. Eye jumps. Continuity break felt
emotionally even if not technically broken.

**Why it fails:** Cut on dialogue silence + same framing = brain registers
discontinuity. The eye is searching for cause.

**Fix:**
1. **Move cut into motion.** Find a head turn, gesture, blink — make cut
   1-3 frames inside the motion. Eye accepts.
2. **L-cut (audio leads).** Move the audio of the new shot to start ~0.4
   sec before the visual cut. Hides the visual transition.
3. **Add transitional B-roll**, even 0.8 sec. Reset.

## Problem: Chapter ends without payoff

**Symptom:** Chapter has setup and middle but no clear payoff line / moment.
Viewer doesn't feel "I just learned X".

**Why it fails:** Story arc unfulfilled. Brain didn't get the cognitive
closure → engagement drops at chapter boundary, retention dies at next chapter.

**Fix:**
1. **Find the payoff inside the chapter.** Often it's there but buried.
   Pull a key_quote from the transcript that's the *implicit* payoff and
   bring it forward — re-cut so it lands at chapter close.
2. **Reorder.** Move the chapter to a different position in the story arc
   where its weakness becomes less visible (e.g., between two stronger
   chapters using sandwich effect).
3. **Cut the chapter.** If no payoff exists in the material — kill it.
   The Hook of the next chapter will land harder without this wandering.

## Problem: Music too loud / too quiet

**Symptom:** «Слышу музыку громче чем speaker'а» / «не понимаю что говорит».

**Fix (no music expertise needed):**
- Dialog needs to be -6 to -3 dB louder than music in mixed segments.
- Sidechain ducking under music: drop music by -4 to -6 dB when speech is
  detected. Most editors have a sidechain template.

But: **flag** this to Roman, don't try to mix it yourself. Suggest the editor
adds sidechain. Stop your contribution at "music is sitting too forward".

## Problem: Pacing feels slow

**Symptom:** Long shots, slow speakers, "explain-y" middle section.

**Murch counter-intuitive insight:** Pacing slowness is rarely about shot
length. It's about **emotional flatness**. A 30-sec static shot of someone
saying something *meaningful* feels fast. A 5-sec cut between mundane
moments feels slow.

**Fix priority:**
1. **Find the emotional moment** in the slow section and amplify it (zoom,
   linger, music swell).
2. **Cut the mundane bridge.** If the section is just connecting beats
   between two strong moments — trim 30-50%, B-roll bridge the connection.
3. **Add stakes/curiosity in voiceover.** If the segment is informational
   without emotion — voiceover question can frame it ("Why does this matter?")
   and re-engages the brain.

## Problem: Hook is weak

**Symptom:** Retention drops sharply at 0:15 → 0:30.

**Fix:** Hook chapter is a whole discipline. Pull strongest 8-12 seconds
from anywhere in the video — best key_quote, most surprising fact, biggest
emotional moment. Open with that. Then signal "here's what we'll cover"
in agenda.

The cold-open formula:
- Sec 1-2: visual hook (action, surprising frame)
- Sec 3-7: spoken hook (the strongest claim/quote/question)
- Sec 8-12: agenda / what this video answers
- Sec 13-15: format & speaker intro (very brief)

## Problem: B-roll cliché

**Symptom:** Dubai skyline B-roll every 30 seconds. City drone every chapter.

**Why it fails:** Audience pattern-matches to "promo video" template. Trust
drops. Retention drops.

**Fix:**
1. **Diverse B-roll palette.** Person at desk > city drone. Hand gesture
   close-up > skyline. Specific detail > generic mood.
2. **B-roll must support point being made.** If speaker says "we close
   deals in 47 minutes" — B-roll of clock face beats B-roll of skyscraper.
3. **Less B-roll, more talking-head with multi-cam.** Especially YTRF/YTFP
   (medical/charitable) where authentic talking-head signals authority.

## Problem: Talking-head + screen cue overlap badly

**Symptom:** Screen cue (number, graph, text) appears while speaker still
talking — viewer reads instead of listening; or speaker stops, screen cue
hangs in awkward silence.

**Fix:**
1. **Lead the screen cue by 0.4-0.7 sec.** Visual appears slightly before
   the spoken word that introduces it. Eye prepares.
2. **Hold screen cue for 1-2 sec after relevant dialogue ends.** Brain
   needs cognitive processing time — don't whip it away on the syllable.
3. **Animate the entry** (slide / fade-in over 0.3 sec). Helps brain parse
   "new information just arrived".

## Per-channel pattern overrides

| Channel | Pacing | Cut style | B-roll density |
|---|---|---|---|
| YTCR | Medium-fast (interview rhythm), broker audience tolerates 12-15 sec talking-head | Cut on motion + occasional whip pan for energy | Medium — office / property / Dubai-but-specific |
| YTCG | Medium (info-density high), entrepreneur audience reads notes | Hard sync cuts okay; clear chapter breaks | Low — screen recordings + on-location footage |
| YTRF | Slow-medium (medical, complex info needs absorption time) | Soft transitions, no whip pan, dignified | High medical animation, low people-B-roll |
| YTFP | Slow (emotional weight, family stories) | Hold on faces, hold on hands, accept silence | Low B-roll — let the family carry the frame |
| YTUVI | Slow-medium (high-end aesthetic, gemmology needs visual time) | Macro detail shots between talking-head | Very high — every claim with macro of the actual stone |

If a channel's rhythm doesn't match this — **flag it as a question** rather
than push the channel default.
