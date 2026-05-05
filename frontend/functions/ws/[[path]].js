export async function onRequest(context) {
  const url = new URL(context.request.url);
  url.hostname = 'api.kickanalytics.live';
  url.protocol = 'https:';
  return fetch(url.toString(), context.request);
}
