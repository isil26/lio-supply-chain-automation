// Managed watchers build the candidate before stopping the current service.
// Ordinary frontend builds and the independently packaged replay use no live gateway.
if (process.env.SOONY_LIVE_UPSTREAM && process.env.SOONY_MAC_MAIL_MODE === 'live' &&
    process.env.VITE_SOONY_HOSTED_REPLAY !== '1') {
  const { accounts } = require('../deploy/vercel/accounts.cjs');
  const backendToken = process.env.SOONY_BACKEND_TOKEN;
  if (!process.env.SOONY_USERS_JSON || !accounts() || !backendToken ||
      process.env.SOONY_LIVE_UPSTREAM_TOKEN !== backendToken) {
    throw new Error('The live release requires configured accounts and the updated backend watcher.');
  }
}
