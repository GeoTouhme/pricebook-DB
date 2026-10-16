# Dashboard design

This is a store operations tool. The owner should understand the selected period,
main result and next action without reading a manual.

- Keep the existing system font and navy text (`#172554`), blue accent (`#2563eb`),
  white canvas (`#ffffff`) and pale surfaces (`#f1f5f9`, selection `#dbeafe`).
  Native controls and custom navigation use the same accent. Preserve dark mode.
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
