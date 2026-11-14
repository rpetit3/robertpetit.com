// Collects Content-Security-Policy violation reports while the policy is in
// report-only mode. Reports land in the function log in the Netlify UI.
export default async (request) => {
  if (request.method === "POST") {
    console.log("csp-report", await request.text());
  }
  return new Response(null, { status: 204 });
};