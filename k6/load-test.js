import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  vus: 30,
  duration: "10m",
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<3000"],
  },
};

export default function () {
  const baseUrl = __ENV.LABFORGE_URL || "http://localhost:8000";
  const headers = { "X-User-Id": `load-user-${__VU}`, "Content-Type": "application/json" };
  const launch = http.post(
    `${baseUrl}/api/sessions`,
    JSON.stringify({ labId: "foundry-lab-01" }),
    { headers }
  );
  check(launch, { "lab launch accepted": (response) => response.status === 201 });
  sleep(1);
}
