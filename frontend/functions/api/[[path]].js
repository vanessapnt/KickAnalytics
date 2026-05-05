export async function onRequest(context) {
  const url = new URL(context.request.url);
  url.hostname = 'api.kickanalytics.live';
  return fetch(url.toString(), context.request);
}
