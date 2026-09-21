/**
 * Relay Yahoo Finance untuk Trading Agent TIO.
 *
 * Tujuan: VPS Anda (mis. IP Tencent) diblokir Yahoo (HTTP 429), tetapi
 * Cloudflare tidak. Worker ini meneruskan permintaan chart Yahoo, sehingga
 * VPS cukup memanggil Worker ini.
 *
 * Deploy (gratis, ~3 menit):
 *   1. Buat akun di https://dash.cloudflare.com  (gratis).
 *   2. Workers & Pages -> Create -> Worker -> beri nama (mis. "yf-relay").
 *   3. Ganti seluruh isi editor dengan file ini -> Deploy.
 *   4. (Opsional, disarankan) Set variabel rahasia RELAY_TOKEN:
 *        Settings -> Variables -> Add variable -> Encrypt -> RELAY_TOKEN=<rahasia_anda>
 *   5. Salin URL Worker (mis. https://yf-relay.<akun>.workers.dev) ke .env:
 *        MARKET_DATA_PROVIDER=yahoo_relay
 *        YAHOO_RELAY_URL=https://yf-relay.<akun>.workers.dev
 *        YAHOO_RELAY_TOKEN=<rahasia_anda>   (jika RELAY_TOKEN diset)
 *
 * Uji cepat di browser:
 *   https://yf-relay.<akun>.workers.dev?symbol=BBCA.JK&range=5d&interval=1d&token=<rahasia>
 */
const YF_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/";
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Autentikasi opsional agar Worker tidak dipakai orang lain.
    if (env.RELAY_TOKEN) {
      const token = url.searchParams.get("token");
      if (token !== env.RELAY_TOKEN) {
        return json({ error: "unauthorized" }, 401);
      }
    }

    const symbol = url.searchParams.get("symbol");
    if (!symbol) return json({ error: "missing 'symbol' param" }, 400);

    const range = url.searchParams.get("range") || "3mo";
    const interval = url.searchParams.get("interval") || "1d";
    const target =
      YF_BASE +
      encodeURIComponent(symbol) +
      `?range=${encodeURIComponent(range)}&interval=${encodeURIComponent(interval)}`;

    try {
      const resp = await fetch(target, { headers: { "User-Agent": UA } });
      const body = await resp.text();
      return new Response(body, {
        status: resp.status,
        headers: {
          "content-type": "application/json; charset=utf-8",
          "access-control-allow-origin": "*",
          "cache-control": "public, max-age=30",
        },
      });
    } catch (err) {
      return json({ error: String(err) }, 502);
    }
  },
};

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
