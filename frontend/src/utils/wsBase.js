export function getWsBase() {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const port = window.location.port ? `:${window.location.port}` : '';
  return `${proto}://${window.location.hostname}${port}/ws`;
}
