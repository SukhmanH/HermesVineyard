---
name: morning-brief
description: The 06:00 bilingual brief. Per-site conditions, an explicit spray-window verdict with best hours, frost flags, and every block still under REI. Crew group in Spanish, manager DMs in English, voice for anyone who prefers listening.
version: 1.0.0
metadata:
  hermes:
    tags: [vineyard, briefing, spanish, tts]
    category: vineyard-ops
    requires_toolsets: [mcp-vineyard, tts, messaging]
---

# Morning brief, 06:00

The one message everyone reads. It is read on a phone, outdoors, in a hurry, possibly by someone
about to decide whether to mix a tank.

**Start with `get_situation`.** It carries the cached forecast and its age per site, plus active
REIs and today's logs. (There is no `context_from` chaining between cron jobs — reading
`weather_cache` through the kernel is the durable path, and it survives a failed 05:45 run.)

## Must contain

- **Per site**: temperature range, wind, rain probability, humidity.
- **The spray verdict, explicitly**: yes or no, and if yes, the best hours. Never imply it, never
  bury it below the conditions. This is the line people are looking for.
- **Frost flag** when in season and relevant.
- **Every block still under REI**, by block code, with the time it clears. Safety first in the
  message, not last.

## Shape

Lead with the verdict. Conditions are supporting detail, not the headline. Somebody skimming
three lines on a phone should get the actionable answer from line one.

The template is a **floor, not a ceiling**. If today is unusual, say the unusual thing even
though no field exists for it: wind swinging hard at noon, a neighbour spraying upwind, a heat
spike that puts sulfur over its phytotoxicity ceiling. If one site differs sharply from the other
two, consider splitting the brief rather than averaging the difference away.

## Channels

- **Crew group in Spanish AND Gurmukhi, one message.** The group holds both Spanish and Punjabi
  speakers. Stack the two languages rather than splitting into two messages and hoping the right
  people read the right one — for safety information that is how somebody gets missed.
- **Manager DMs** in English.
- **Voice** additionally, never instead, for `es` contacts with `voice_replies = 1`. Edge TTS,
  Spanish voice, `[[audio_as_voice]]` so it arrives as a real voice bubble. Literacy varies on a
  SAWP crew and a spoken NO ENTRAR reaches people a text message does not.
- **Punjabi voice via tools/punjabi-tts, not Edge TTS** — Edge TTS has no `pa-IN` voice at all
  (speech is Google Cloud TTS, `pa-IN-Chirp3-HD-Puck`). Shell out with `terminal` and send the
  file with `[[audio_as_voice]]`. Generate it during the job rather than making anyone wait;
  templated messages are cached by hash. Voice goes *in addition to* the Gurmukhi text, never
  instead of it. See `/punjabi-intake`.

## When the data is degraded

Send the degraded version, never nothing. Name the source and its age, and carry the fail-safe NO
verdict through unchanged. A morning with no brief looks identical to a broken gateway, and it
teaches people to stop relying on you.
