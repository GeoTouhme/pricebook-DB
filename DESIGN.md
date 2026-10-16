# Dashboard design

This is a store operations tool. The owner should understand the selected period,
main result and next action without reading a manual.

- Follow the Seline reference: warm paper canvas (`#fafaf9`), white cards,
  stone hairlines (`#e8e6e5`), ink text (`#0c0a09`), muted text (`#78716c`),
  and cyan (`#3ba6f1`) as the single accent. Use neutrals for secondary chart
  series; identify series by labels as well as color. Preserve dark mode with
  warm charcoal surfaces and the same cyan accent.
- Self-host Inter for 14px body/UI text and Inter Tight (the available Roobert
  substitute) for weight-400 headings. No external font requests at runtime.
  Fonts and their OFL licenses live under `static/fonts/`.
- Use a 1200px content width, 10px card radii, 24px card padding (16px on mobile),
  pill buttons, and 6px input radii. Keep headings at useful dashboard sizes,
  section spacing compact, and body/helper text readable. Cyan-filled primary
  buttons use ink text for contrast. Avoid gradients and decorative shadows.
- Adapt the reference to an operational dashboard: real charts stay legible,
  and navigation, source warnings, save receipts, and review steps remain clear.
  Marketing heroes, testimonials, mascot stickers, and grayscale screenshot
  effects do not belong in the working data views.
- Use short sentence-case labels and concrete actions. Put source definitions,
  audit fields and repeated explanations in field help or expandable details.
  Keep blockers, data gaps and unverified physical stock visible at the decision.
- Put period filters, business measures and the main chart first. Source row
  counts, matching diagnostics and downloads are supporting details.
- Sales $ and Scan Sales are separate source measures, never additive revenue.
  Missing dates remain gaps; invoices are not confirmed payments. No profit or
  physical-stock claims without the corresponding evidence.
- Preserve invoice units and PACK UPC matching. Display labels may change;
  source column names, UPC text, exports and stored values must retain meaning.
- Keep the expanding, pinnable sidebar. Use short, interruptible feedback,
  respect reduced motion, and avoid long animation delays when filtering data.
- Upload controls and backend validators share a 20 MB limit. Validation,
  review confirmations, persistent save receipts and backups remain in place.
- Check desktop and mobile, light and dark themes, keyboard focus, long product
  names, missing values and empty selections. Use native Streamlit widgets.
