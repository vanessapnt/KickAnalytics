export function getWsBase() {
  if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const port = window.location.port ? `:${window.location.port}` : '';
    return `${proto}://${window.location.hostname}${port}/ws`;
  }
  return 'wss://api.kickanalytics.live/ws';
}
