// The only Loop Map backend paths the browser may reach through
// app/api/loop-map/[[...path]]. The playbook and snapshot routes on
// api/routers/loop_map.py are deliberately absent.
const UUID = "[0-9a-fA-F-]{36}";

const ALLOWED_GET = [/^$/];
const ALLOWED_POST = [
  new RegExp(`^${UUID}/steps/\\d{1,3}/(complete|undo)$`),
  new RegExp(`^${UUID}/laps/(complete|reset)$`),
  new RegExp(`^${UUID}/notes$`),
  new RegExp(`^notes/${UUID}/resolve$`),
];

export function isAllowedLoopMapPath(method: "GET" | "POST", suffix: string): boolean {
  return (method === "GET" ? ALLOWED_GET : ALLOWED_POST).some((re) => re.test(suffix));
}
