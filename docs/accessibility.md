# Accessibility, privacy and trust

## For the senior: nothing to learn

- **Nothing to wear, press or charge.** Making tea is the signal.
- When Kettle does ask, it asks in the most familiar ways: a **phone call** ("press 1 if you're fine") and a **big glowing button** in the kitchen. The button fills most of the screen, and the space bar or the physical ESP32 button also work. You can also just **say "I'm fine"** (browser speech recognition, where available).
- **"I'm away today"** pauses Kettle in one tap, and the circle is told.
- The kitchen display uses huge type and high contrast, and never shows anything alarming. A neighbour's "thinking of you" shows as warm light.

## For the circle: calm, clear, one thumb

- Alerts take over the screen as an `alertdialog` with focus moved to the first action, an `aria-live="assertive"` announcement and vibration. The actions are three stacked buttons at least 58 px tall, in thumb reach.
- Every alert says **why** ("No kettle by 12:07. Usually 10:21.") and that the person was asked first.
- Base font is 18 px, and colour contrast is at least 4.5:1 for all text (tokens in `web/shared/kettle.css`; ink on cream is 15.9:1). `prefers-reduced-motion` is respected everywhere.
- Gender-neutral by design: the pronouns for the person in the circle are configurable (`she`/`he`/`they`) and every template uses them.

**Automated audit (axe-core 4.14, WCAG 2.0/2.1 A + AA + best practice), Nov 7 2026:**

| Screen | Violations | Passing checks |
|---|---|---|
| Circle app: home | 0 | 39 |
| Circle app: "Can you knock?" alert | 0 | 42 |
| Circle app: join form | 0 | 41 |
| Kitchen display | 0 | 32 |

To reproduce: `npm pack axe-core`, then `scripts/snap.py <url> out.png --inject axe.min.js --eval "axe.run().then(r => JSON.stringify(r.violations))" --long`. Automated checks catch about a third of accessibility problems. We have **not** yet tested with screen-reader users or seniors; that's part of the pilot.

## Privacy and transparency

- **Raw power readings never leave the home.** This is enforced in code: the cloud has no endpoint, message type or table for them, and drops them if a device sends any. The edge keeps about 10 minutes of trace in memory, for the local display only.
- The circle sees only moments ("kettle on at 7:48"), and the app says so on every screen.
- The person owns their circle, is always asked first, and can pause at any time.
- Every decision is explainable: no black-box model, and the rule and the numbers are in the alert.
- Clear limits: **not a medical device, not an emergency service.** The app says to call 911 in an emergency.
