// Collects Content-Security-Policy violation reports while the policy is in
// report-only mode. Reports land in the Pages function log in the Cloudflare
// dashboard.
export const onRequest = async ({ request }) => {
  if (request.method === "POST") {
    console.log("csp-report", await request.text());
  }
  return new Response(null, { status: 204 });
};