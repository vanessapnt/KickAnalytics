const BASE = 'https://github.com/vanessapnt/KickAnalytics/releases/download/pipeline-data-v1';

export async function onRequest(context) {
  const url = new URL(context.request.url);
  const filename = url.pathname.replace('/pipeline-data/', '');
  const response = await fetch(`${BASE}/${filename}`, {
    redirect: 'follow',
    headers: { 'User-Agent': 'Cloudflare-Pages' },
  });
  const newHeaders = new Headers(response.headers);
  newHeaders.set('Access-Control-Allow-Origin', '*');
  return new Response(response.body, {
    status: response.status,
    headers: newHeaders,
  });
}
