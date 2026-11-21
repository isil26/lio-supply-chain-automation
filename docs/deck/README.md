# Deck export

Open `docs/deck/index.html` in Chrome or another Chromium browser.

## Present

- Press `Right Arrow`, `Page Down`, or `Space` to advance.
- Press `Left Arrow`, `Page Up`, or `Backspace` to go back.
- Use `Home` / `End` to jump to the first / last slide.

The deck is self-contained: no external assets or fonts are loaded.

## Export to PDF

1. Open `index.html` locally or serve the repository at loopback.
2. Press `Ctrl/Cmd+P` or choose **Print**.
3. Set the destination to **Save as PDF**.
4. Set layout to **Landscape**.
5. Set paper size to **16:9** if available. Otherwise choose **Custom**: 16 inches wide by 9 inches high.
6. Set margins to **None** and disable headers and footers.
7. Enable **Background graphics** so the dark theme exports correctly.
8. Save the PDF.

The print stylesheet renders each slide as a full 16:9 landscape page. Chromium's print preview is the preferred export path.
