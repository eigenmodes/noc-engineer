# Task: insert screenshots into the Rafiki capability document

You are editing two static HTML files in this folder. Both contain the same
4 screenshot slots on page 2. Apply every change to BOTH files.

| File | Layout |
|---|---|
| `rafiki-long.html` | Pages 1 and 2 stacked as one long page (for email) |
| `rafiki-two-pages.html` | Two separate 1240×1880 pages (prints as a 2-page PDF) |

## Inputs

The owner gives you screenshot files. Put each in `screenshots/` with this exact name:

| Slot | Role (Hebrew label) | Expected screenshot | File name |
|---|---|---|---|
| 1 | שירות לקוחות | Customer question + bot answer (Mattermost DM) | `1-customer-service.png` |
| 2 | ניטור אנומליות | Anomaly alert (Mattermost team channel) | `2-anomaly-monitoring.png` |
| 3 | דוחות ותובנות | Daily incident summary (Mattermost team channel) | `3-daily-report.png` |
| 4 | טיפול בתקלות | Jira ticket with the bot's findings | `4-incident-handling.png` |

If the owner gives screenshots without saying which is which, classify each one by
its content using the table above. If one cannot be classified, ask; do not guess.
If two fit the same slot, ask which one to use.

## Steps (per slot N)

1. Find the comment `<!-- SCREENSHOT N (...) -->`.
2. Replace the `<div class="shot-placeholder" data-slot="N" ...>...</div>` that follows it
   (the whole div, including its icon and text) with:
   `<img class="shot" src="screenshots/<file name>" alt="<short Hebrew description>">`
3. Replace the text inside `<span class="caption" data-slot="N">` with ONE Hebrew sentence
   describing what Rafiki found in that screenshot, based only on what is visible in it.
   Example: `זיהה ירידה בתוצר בשרת X, 40 דקות לפני הפנייה הראשונה.`
4. Leave any slot without a screenshot unchanged.

## Rules

- Do not change anything outside the SCREENSHOT SLOTS START/END markers.
- Keep `class="shot"`: it sizes the image to the frame (560px high, `object-fit: contain`).
- Do not invent facts in captions. If the screenshot does not show a clear finding, write
  a neutral caption describing what it shows.
- Before inserting, check each screenshot for customer names, IP addresses, server names,
  tokens or personal data. If any are visible, stop and ask the owner whether to mask them.
  Mask by drawing solid rectangles over the area (e.g. with Pillow); never blur text lightly.
- Hebrew text, RTL. Keep the existing tone: short, plain, no hype.

## Done when

- Every provided screenshot sits in its slot in both files.
- Each filled slot has a one-sentence caption.
- Opening both files in a browser shows the images inside the frames, nothing overflowing.
