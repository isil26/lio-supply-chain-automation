# Manti dashboard design demo

Open `index.html` in a browser. The standalone demo needs no build, account or credentials.

- **Dashboard** shows the Saturday 19:25 box forecast and a replay of supplier correspondence through 20:44 CET. Forecast details lets a reviewer change expected box counts or restore the baseline. The Collector’s refund exposure is €120 per missing preorder. The €32 per late Standard box is an unconfirmed assumption.
- Choose one of five products, select a supplier and read its source email. **Approve**, **Decline** and **Negotiate** prepare distinct editable replies. Saving a named decision records a draft locally. **Open in email app** hands it to the reviewer’s configured mail client for manual sending.
- **Activity Log** reuses the dashboard layout. Select a decision to see its reviewer, replay time, forecast snapshot, original supplier email and saved draft. Decisions are stored in this browser. Reviewer names are self-entered.

Edit `scenario.js` for forecast inputs, recommendations and reply templates, `evidence.js` for supplier evidence, and `styles.css` for layout and colors. The Manti mark is reproduced from the main website’s `MantiLogo` in `web/src/SupplyMap.tsx`.
