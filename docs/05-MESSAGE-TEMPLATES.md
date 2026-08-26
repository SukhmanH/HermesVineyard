# 05 — Bilingual Message Templates

Canonical copy for every user-facing message. At build time these become
`templates/es.yaml` and `en.yaml` (`pa.yaml` in Phase 2) with `{placeholders}` filled by
`vineyard-mcp` and rendered by the agent. Spanish is Mexican-register, plain, short sentences,
emoji as visual anchors (crew reads fast on phones in sunlight). English is manager-brief style.

**Rule (docs/01 §D8 + §4): these templates are a floor, not a ceiling.** Hermes leads, so it is
free to add to any message here — a warning the template has no field for, a note to one worker, a
reordering because today is unusual. What it may **not** do is restate a computed fact in its own
words: the spray verdict, an REI time, a rate, a block's acreage, and the confirmation card render
from tool-returned values through these templates, every time. Facts are rendered; judgement is
Hermes's. Everything Hermes adds beyond the template is logged (docs/01 §3.1).

Follow-up questions, acknowledgements, and anything conversational are Hermes's own words by
default — the wordings in §2 and §3 are known-good starting points, not a script.

**Channel** is noted per message: 📢 **group** (whole crew at once) or 💬 **1:1** (private).
Rationale in docs/01 §D1.

**Voice (🔊).** Messages marked 🔊 are also sent as a Spanish voice note via Edge TTS (docs/01 §7.1)
to contacts with `voice_replies=1` — **in addition to the text, never instead of it.** Text stays
scrollable, quotable, and re-readable; voice reaches people for whom reading is the harder path.
Write the spoken variant as a plain sentence without emoji or layout ("Buenos días. Hoy sí se puede
fumigar en Penticton, de seis a nueve y media. Bloque tres cerrado hasta las dos.") — the visual
formatting below is for the eye and reads badly aloud.

## 1. Morning brief

**ES → 📢 crew group 🔊 (`morning_brief_es`)**
```
🌅 Buenos días equipo — {fecha}

{por cada sitio:}
📍 *{sitio}*
🌡️ Máx {tmax}° / Mín {tmin}°   💧 Humedad {rh}%
💨 Viento {viento} km/h {dir} (ráfagas {rafagas})
🌧️ Lluvia {prob}%

🚜 ¿Se puede fumigar hoy en {sitio}? *{SÍ/NO}*
{si SÍ:} ✅ Mejor horario: {inicio}–{fin}
{si NO:} ❌ {motivo, ej: "viento fuerte toda la tarde"}

{si hay REI activo:}
🚫 *NO ENTRAR*: {Bloque X} hasta {día} {hora} ({producto})

{si riesgo de helada:}
❄️ *OJO: riesgo de helada esta noche (mín {tmin}°)*

Escribe *CLIMA* para actualizar · *AYUDA* si necesitas algo
```

**EN → 💬 manager DMs (`morning_brief_en`)** — same data, compact:
```
🌅 Morning brief — {date}
{per site:} {Site}: {tmax}°/{tmin}°, wind {w} km/h {dir} (gusts {g}), rain {p}%, RH {rh}%
   Spray window: {YES {start}–{end} / NO — {reason}}
{REI active: 🚫 {Block} re-entry {day} {time} ({product})}
{Frost: ❄️ frost risk tonight — min {t}° at {site}}
{Data caveat if degraded: ⚠️ based on {Open-Meteo fallback / yesterday's cached} data}
```

## 2. Spray-log follow-up questions (ES, 💬 1:1)

Asked only for missing fields, bundled so a normal report needs **≤2 follow-up messages**. The
missing-field list comes from `draft_spray_log`, not from the model's judgement. Weather at
application is auto-prefilled from the cached forecast for the block's site at the reported time —
the worker just confirms it in the summary card.

| Field missing | Question |
|---|---|
| product | ¿Qué producto aplicaste? (el nombre en la etiqueta — o mándame *foto de la etiqueta* 📸) |
| block | ¿En qué bloque? (ej: *bloque 3*) |
| block ambiguous | ¿Bloque *{code} — {name}* ({acres} acres)? Responde *sí* o dime cuál. |
| rate | ¿Cuánto aplicaste? (ej: *8 kg/ha* o *total 25 kg*) |
| times | ¿De qué hora a qué hora? (ej: *6:00 a 9:30*) |
| target pest | ¿Contra qué? (ej: *oídio / cenicilla*) |
| REI unverified product | La etiqueta dice el *REI* (horas sin entrar). ¿Cuántas horas dice? |

**Confirmation card (`spray_confirm_es`)** — nothing commits without this. Shown when
`draft_spray_log` returns an empty `missing_fields`; «SÍ» releases the `confirm_token` to
`commit_spray_log` (docs/02 `drafts`).
```
📋 Voy a guardar esto:
🧪 {producto} — {tasa}
📍 Bloque {code} ({acres} acres) · {fecha}, {inicio}–{fin}
🎯 Contra: {plaga}
🌡️ {temp}°, viento {viento} km/h {dir}  (según pronóstico — ¿correcto?)
⏳ NO ENTRAR hasta: {rei_fin}

¿Está bien? Responde *SÍ* para guardar, o dime qué corregir.
```
Saved ack: `✅ Guardado. Gracias {nombre} 👍  ⏳ Recuerda: nadie entra al Bloque {code} hasta {rei_fin}.`

## 3. Task log (ES, 💬 1:1)

Follow-ups (only if missing): «¿En qué bloque?» · «¿Cuántas horas le dedicaron?» ·
«¿Quiénes trabajaron en esto?» · «¿Cuántas hileras terminaron?»
Confirm: `📋 {tarea} — Bloque {code} · {horas} h · {trabajadores} · {cantidad}. ¿SÍ?`
Ack: `✅ Anotado. Gracias {nombre} 💪`

## 4. Alerts & reports

**REI warning ES (`rei_alert_es`)** → 📢 **crew group** 🔊, on spray commit:
`🚫 *NO ENTRAR — Bloque {code}*  Se aplicó {producto} hoy a las {hora}. Entrada permitida: *{día} {hora_fin}*. Avisa a tus compañeros.`
All-clear → 📢 group: `✅ Ya se puede entrar al Bloque {code} ({producto}, REI cumplido).`

**REI warning EN (`rei_alert_en`)** → 💬 managers:
`🚫 REI: Block {code} sprayed with {product} at {time} by {applicator}. Re-entry {day} {end_time} ({rei}h).`

**Frost ES** → 📢 group 🔊: `❄️ *ALERTA DE HELADA* — esta noche mín {t}° en {sitio}. {instrucción del manager}`
**Frost EN** → 💬 managers: `❄️ FROST ALERT — {site} overnight min {t}°C ({source}). Wind machines / sprinklers call is yours.`

**EOD manager report EN (`eod_report_en`)** → 💬 managers + email:
```
📊 EOD — {date}
✅ Work today:
  {Block}: {task} — {workers} ({hours} h) {qty}
  (or: — no tasks logged today)
🧪 Sprays:
  {Block}: {product} {rate} by {applicator}, {start}–{end} → re-entry {day} {time}
⏳ REI active tomorrow: {list or none}
🌤️ Tomorrow: {per site: hi/lo, wind, rain} → spray window {YES hrs / NO reason}
🏡 New listings ({n}): {price} — {acres} ac — {area} — {short title} {url}
⚠️ Flags: {workers with no log; degraded weather; job failures; unverified products used}
🧭 Hermes notes: {standing-duty findings and notable decisions — docs/03 §1.1, docs/01 §3.1.
   e.g. "Held the midday update — verdict unchanged." / "B7 got sulfur twice in 6 days, worth a
   look." / "Asked Miguel twice about Tuesday's hours, no reply yet."}
📎 {Fri: workbook attached to email / 1st: compliance workbook emailed}
```
The 🧭 line is where Hermes reports as a manager rather than as a form: what it noticed, what it
decided on its own, and what it is still chasing. Empty is a valid value; padding it is not.

**Weather-down ES** → 📢 group: `⚠️ Hoy no tengo datos del clima (falla técnica). *No fumiguen* sin consultar a su manager. Les aviso cuando vuelva.`
**Weather-down EN** → 💬 managers: `⚠️ Weather source down (both providers). Morning brief degraded; spray verdict withheld (fail-safe NO). Investigating.`

**Emergency ack ES** → 💬 worker: `🆘 Recibido. Ya avisé a los managers — te van a llamar. Si es grave llama al *911*.`
**Emergency relay EN** → 💬 all managers + owner: `🆘 EMERGENCY from {name} ({phone}): "{original}" → EN: "{translation}". Sent {time}. CALL THEM NOW.`

**Gateway-down EN** → **email only** (WhatsApp is what's broken):
`⚠️ Hermes WhatsApp gateway disconnected at {time}. No messages are being sent or received. Re-pair per docs/04 §8.`

## 5. Appendix — Meta template wording (not used on the Baileys path)

Retained **only** for the migration path in docs/01 §D1. On Baileys there is no 24-hour service
window, no template pre-approval, and no per-message cost, so none of this is needed. If the bot's
number is banned twice, or the business later wants the official API's reliability guarantees,
these are the five templates to submit (category **Utility**, languages es_MX + en).

| Name | Body (es_MX / en) |
|---|---|
| `daily_brief` | «Reporte diario del viñedo — {{1}}: {{2}}. Responde CLIMA para más detalle.» / "Daily vineyard report — {{1}}: {{2}}. Reply for details." |
| `rei_alert` | «Aviso de seguridad: NO ENTRAR al bloque {{1}} hasta {{2}} (aplicación de {{3}}).» / "Safety notice: do NOT enter block {{1}} until {{2}} ({{3}} application)." |
| `frost_alert` | «Alerta de helada para {{1}}: mínima prevista {{2}}. Instrucciones: {{3}}.» / "Frost alert for {{1}}: forecast low {{2}}. Instructions: {{3}}." |
| `eod_report` | "End-of-day operations report {{1}}: {{2}}. Reply for the full report." (en only) |
| `generic_alert` | «Aviso del sistema Hermes: {{1}}» / "Hermes system notice: {{1}}" |

Migration note: the official API cannot post to the crew's existing group (docs/01 §D1), so
migrating also means reverting §1 and §4 broadcasts from 📢 group back to 1:1 fan-out.

## 6. Commands (no-LLM fast path, ES/EN by contact language)

Matched by keyword **before** any LLM call, so they work during a provider outage:

`CLIMA/WEATHER` → current brief · `AYUDA/HELP` → how-to card · `CORREGIR/FIX` → correction flow ·
`EXPORT` (managers) → Excel on demand · `HOLA/HI` → greeting + consent record ·
`ALTO/STOP` → pause non-safety messages (REI/frost/emergency always delivered).
